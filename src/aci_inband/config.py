"""Load operator-friendly JSON and reject dangerous input before APIC login.

This module deliberately contains no Cobra imports.  A GUI/Postman user can
think of it as the validation normally performed by APIC form fields: it checks
VLAN bounds, address syntax, duplicate nodes, subnet membership, and required
names before the program is allowed to establish an APIC session.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the requested ACI configuration is unsafe or invalid."""


@dataclass(frozen=True)
class NodeAddress:
    """One row from GUI > Static Node Management Addresses."""

    # ACI node identity.  pod 1 / node 101 becomes the target DN
    # topology/pod-1/node-101 used by mgmtRsInBStNode.
    pod_id: int
    node_id: int

    # ``address`` includes the prefix; ``gateway`` is a host address only.
    address: str
    gateway: str

    @property
    def target_dn(self) -> str:
        return f"topology/pod-{self.pod_id}/node-{self.node_id}"


@dataclass(frozen=True)
class AccessInterface:
    """One APIC-facing leaf port selector under an existing interface profile."""

    # The profile must already be associated with the correct leaf switch.
    interface_profile: str
    # ACI names the selector and its port block independently.
    selector: str
    block: str
    # A normal fixed leaf port is card/module 1 and a positive port number.
    card: int
    port: int


@dataclass(frozen=True)
class AccessPolicy:
    """Names used by the optional Fabric > Access Policies configuration."""

    vlan_pool: str
    physical_domain: str
    aaep: str
    port_policy_group: str
    interfaces: tuple[AccessInterface, ...]


@dataclass(frozen=True)
class InbandConfig:
    """Validated desired state consumed by the Cobra object builder.

    ``frozen=True`` prevents accidental mutation after validation.  If a value
    needs to change, edit the JSON and load/validate it again.
    """

    apic_version: str
    tenant: str
    management_profile: str
    vrf: str
    bridge_domain: str
    subnet_gateway: str
    subnet_scope: str
    l3outs: tuple[str, ...]
    epg: str
    vlan: int
    nodes: tuple[NodeAddress, ...]
    provided_contracts: tuple[str, ...]
    consumed_contracts: tuple[str, ...]
    access_policy: AccessPolicy | None

    @property
    def encap(self) -> str:
        return f"vlan-{self.vlan}"


def _required(data: dict[str, Any], key: str) -> Any:
    """Return a required JSON member or raise a readable operator error."""
    if key not in data or data[key] in (None, ""):
        raise ConfigError(f"missing required field: {key}")
    return data[key]


def _name(value: Any, field: str) -> str:
    """Apply the conservative naming rule used by this utility.

    APIC naming rules vary slightly by class.  Restricting these inputs to
    non-empty, whitespace-free names of at most 64 characters avoids producing
    ambiguous DNs and catches the most common copy/paste mistakes.
    """
    value = str(value)
    if not value or len(value) > 64 or any(ch.isspace() for ch in value):
        raise ConfigError(f"{field} must be a non-empty ACI name without whitespace (max 64)")
    return value


def load_config(path: str | Path) -> InbandConfig:
    """Read JSON, validate every field, and return typed configuration."""

    # json.loads converts the text into ordinary Python dictionaries/lists.
    # Nothing in this step contacts APIC or changes the fabric.
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a JSON object")

    # This repo intentionally targets the 5.2 model.  The CLI separately checks
    # the version reported by aaaLogin so an operator cannot accidentally point
    # it at a 6.x fabric merely by supplying a different URL.
    version = str(raw.get("apic_version", "5.2"))
    if not version.startswith("5.2"):
        raise ConfigError("this release is validated for APIC 5.2; set apic_version to 5.2")

    # ACI reserves VLAN 0 and 4095.  int() also accepts a JSON string such as
    # "3999", which is convenient when translating values from a worksheet.
    vlan = int(_required(raw, "vlan"))
    if not 1 <= vlan <= 4094:
        raise ConfigError("vlan must be between 1 and 4094")

    # ip_interface understands an address plus prefix, e.g. 192.0.2.1/24.
    # It gives us both the gateway host address and its containing network.
    subnet_gateway = str(_required(raw, "subnet_gateway"))
    try:
        subnet = ipaddress.ip_interface(subnet_gateway)
    except ValueError as exc:
        raise ConfigError(f"invalid subnet_gateway: {exc}") from exc

    # Build a clean list while tracking uniqueness.  APIC may report conflicts
    # later, but catching them here makes the failure obvious before any POST.
    nodes: list[NodeAddress] = []
    seen_targets: set[tuple[int, int]] = set()
    seen_ips: set[str] = set()
    for index, item in enumerate(_required(raw, "nodes")):
        try:
            pod_id = int(item.get("pod_id", 1))
            node_id = int(item["node_id"])
            address = str(item["address"])
            # When a node omits gateway, use the host portion of subnet_gateway.
            gateway = str(item.get("gateway", subnet.ip))
            node_if = ipaddress.ip_interface(address)
            gateway_ip = ipaddress.ip_address(gateway)
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"invalid nodes[{index}]: {exc}") from exc
        if node_if.version != subnet.version or gateway_ip.version != subnet.version:
            raise ConfigError(f"nodes[{index}] address family does not match subnet_gateway")
        # Every node address and gateway must belong to the BD subnet.  This
        # catches a wrong prefix or a pasted address from another management LAN.
        if node_if.network != subnet.network or gateway_ip not in subnet.network:
            raise ConfigError(f"nodes[{index}] address/gateway must be in {subnet.network}")
        target = (pod_id, node_id)
        if target in seen_targets:
            raise ConfigError(f"duplicate node target: pod {pod_id}, node {node_id}")
        if str(node_if.ip) in seen_ips:
            raise ConfigError(f"duplicate node IP: {node_if.ip}")
        if node_if.ip == subnet.ip:
            raise ConfigError(f"nodes[{index}] cannot use the BD gateway address")
        seen_targets.add(target)
        seen_ips.add(str(node_if.ip))
        nodes.append(NodeAddress(pod_id, node_id, str(node_if), str(gateway_ip)))

    if not nodes:
        raise ConfigError("nodes must contain at least one APIC, leaf, or spine")

    # In the GUI, "Advertised Externally" corresponds to public scope.  Private
    # is the safe default when no L3Out advertisement is requested.
    scope = str(raw.get("subnet_scope", "private"))
    valid_scopes = {"private", "public", "shared", "public,shared"}
    if scope not in valid_scopes:
        raise ConfigError(f"subnet_scope must be one of: {', '.join(sorted(valid_scopes))}")

    l3outs = tuple(_name(v, "l3outs[]") for v in raw.get("l3outs", []))
    if l3outs and "public" not in scope.split(","):
        raise ConfigError("subnet_scope must include public when l3outs are configured")

    # access_policy is optional.  Omitting it means "the required VLAN/domain/
    # AAEP/leaf-port plumbing already exists; configure only the mgmt tenant."
    access = raw.get("access_policy")
    access_policy = None
    if access is not None:
        interfaces = tuple(
            AccessInterface(
                interface_profile=_name(i["interface_profile"], "interface_profile"),
                selector=_name(i["selector"], "selector"),
                block=_name(i.get("block", f"block-{i['card']}-{i['port']}"), "block"),
                card=int(i["card"]),
                port=int(i["port"]),
            )
            for i in access.get("interfaces", [])
        )
        if not interfaces:
            raise ConfigError("access_policy.interfaces cannot be empty")
        if any(i.card < 1 or i.port < 1 for i in interfaces):
            raise ConfigError("access interface card and port must be positive")
        access_policy = AccessPolicy(
            vlan_pool=_name(_required(access, "vlan_pool"), "vlan_pool"),
            physical_domain=_name(_required(access, "physical_domain"), "physical_domain"),
            aaep=_name(_required(access, "aaep"), "aaep"),
            port_policy_group=_name(
                _required(access, "port_policy_group"), "port_policy_group"
            ),
            interfaces=interfaces,
        )

    # Convert mutable JSON lists into immutable tuples and apply defaults for
    # standard ACI names.  The rest of the program never reads raw JSON again.
    return InbandConfig(
        apic_version=version,
        tenant=_name(raw.get("tenant", "mgmt"), "tenant"),
        management_profile=_name(raw.get("management_profile", "default"), "management_profile"),
        vrf=_name(raw.get("vrf", "inb"), "vrf"),
        bridge_domain=_name(raw.get("bridge_domain", "inb"), "bridge_domain"),
        subnet_gateway=str(subnet),
        subnet_scope=scope,
        l3outs=l3outs,
        epg=_name(raw.get("epg", "inb"), "epg"),
        vlan=vlan,
        nodes=tuple(nodes),
        provided_contracts=tuple(
            _name(v, "provided_contracts[]") for v in raw.get("provided_contracts", [])
        ),
        consumed_contracts=tuple(
            _name(v, "consumed_contracts[]") for v in raw.get("consumed_contracts", [])
        ),
        access_policy=access_policy,
    )


def plan(config: InbandConfig) -> dict[str, Any]:
    """Return a reviewable, credential-free description of intended DNs.

    This is what ``--plan`` prints.  It intentionally requires neither an APIC
    password nor Cobra, so it can be attached to a change record for review.
    """
    result: dict[str, Any] = {
        "target": "Cisco APIC 5.2",
        "management_tenant": config.tenant,
        "objects": [
            f"uni/tn-{config.tenant}/ctx-{config.vrf}",
            f"uni/tn-{config.tenant}/BD-{config.bridge_domain}",
            f"uni/tn-{config.tenant}/BD-{config.bridge_domain}/subnet-[{config.subnet_gateway}]",
            f"uni/tn-{config.tenant}/mgmtp-{config.management_profile}/inb-{config.epg}",
        ]
        + [
            f"uni/tn-{config.tenant}/mgmtp-{config.management_profile}/inb-{config.epg}/"
            f"rsinBStNode-[{node.target_dn}]"
            for node in config.nodes
        ],
        "node_addresses": [
            {"target_dn": n.target_dn, "address": n.address, "gateway": n.gateway}
            for n in config.nodes
        ],
        "encap": config.encap,
    }
    if config.access_policy:
        result["access_policy"] = {
            "vlan_pool": config.access_policy.vlan_pool,
            "physical_domain": config.access_policy.physical_domain,
            "aaep": config.access_policy.aaep,
            "port_policy_group": config.access_policy.port_policy_group,
            "interfaces": [i.__dict__ for i in config.access_policy.interfaces],
        }
    return result
