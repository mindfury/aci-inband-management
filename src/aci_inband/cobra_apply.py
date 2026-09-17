"""Build and commit the ACI 5.2 managed-object tree with Cobra."""

from __future__ import annotations

from typing import Any

from .config import InbandConfig


class CobraUnavailable(RuntimeError):
    """Raised when the APIC-matched Cobra packages are not installed."""


def _cobra() -> dict[str, Any]:
    try:
        from cobra.mit.access import MoDirectory
        from cobra.mit.request import ConfigRequest
        from cobra.mit.session import LoginSession
        from cobra.model import fv, fvns, infra, mgmt, phys, pol, vz
    except ImportError as exc:
        raise CobraUnavailable(
            "Cobra is not installed. Run scripts/install_cobra.py against the target APIC first."
        ) from exc
    return locals()


def connect(apic: str, username: str, password: str, verify_ssl: bool = True):
    cobra = _cobra()
    session = cobra["LoginSession"](
        apic.rstrip("/"), username, password, secure=verify_ssl
    )
    directory = cobra["MoDirectory"](session)
    directory.login()
    return directory


def _require_existing(directory, dn: str):
    mo = directory.lookupByDn(dn)
    if mo is None:
        raise RuntimeError(f"required existing ACI object was not found: {dn}")
    return mo


def build_tree(directory, config: InbandConfig):
    c = _cobra()
    fv, fvns, infra = c["fv"], c["fvns"], c["infra"]
    mgmt, phys, pol, vz = c["mgmt"], c["phys"], c["pol"], c["vz"]

    root = pol.Uni("")
    tenant = fv.Tenant(root, config.tenant)
    context = fv.Ctx(tenant, config.vrf)
    bd = fv.BD(tenant, config.bridge_domain)
    fv.RsCtx(bd, tnFvCtxName=context.name)
    fv.Subnet(bd, ip=config.subnet_gateway, scope=config.subnet_scope)
    for l3out in config.l3outs:
        fv.RsBDToOut(bd, tnL3extOutName=l3out)

    management_profile = mgmt.MgmtP(tenant, config.management_profile)
    inband = mgmt.InB(management_profile, config.epg, encap=config.encap)
    mgmt.RsMgmtBD(inband, tnFvBDName=config.bridge_domain)
    for contract in config.provided_contracts:
        vz.RsProv(inband, contract)
    for contract in config.consumed_contracts:
        vz.RsCons(inband, contract)
    for node in config.nodes:
        mgmt.RsInBStNode(
            inband,
            node.target_dn,
            addr=node.address,
            gw=node.gateway,
        )

    if config.access_policy:
        ap = config.access_policy
        infra_root = infra.Infra(root)
        vlan_pool = fvns.VlanInstP(infra_root, ap.vlan_pool, allocMode="static")
        fvns.EncapBlk(
            vlan_pool,
            config.encap,
            config.encap,
            allocMode="static",
        )
        domain = phys.DomP(root, ap.physical_domain)
        infra.RsVlanNs(domain, tDn=str(vlan_pool.dn))
        aaep = infra.AttEntityP(infra_root, ap.aaep)
        infra.RsDomP(aaep, tDn=str(domain.dn))
        port_group = infra.AccPortGrp(infra_root, ap.port_policy_group)
        infra.RsAttEntP(port_group, tDn=str(aaep.dn))

        # Interface profiles must already be mapped to the intended leaf nodes.
        # Reusing them avoids silently changing switch-profile topology.
        for interface in ap.interfaces:
            _require_existing(
                directory, f"uni/infra/accportprof-{interface.interface_profile}"
            )
            profile = infra.AccPortP(infra_root, interface.interface_profile)
            selector = infra.HPortS(profile, interface.selector, type="range")
            infra.PortBlk(
                selector,
                interface.block,
                fromCard=str(interface.card),
                toCard=str(interface.card),
                fromPort=str(interface.port),
                toPort=str(interface.port),
            )
            infra.RsAccBaseGrp(selector, tDn=str(port_group.dn))

    return root


def apply(directory, config: InbandConfig) -> str:
    c = _cobra()
    request = c["ConfigRequest"]()
    request.addMo(build_tree(directory, config))
    directory.commit(request)
    return str(request)


def verify(directory, config: InbandConfig) -> list[str]:
    dns = [
        f"uni/tn-{config.tenant}/ctx-{config.vrf}",
        f"uni/tn-{config.tenant}/BD-{config.bridge_domain}",
        f"uni/tn-{config.tenant}/mgmtp-{config.management_profile}/inb-{config.epg}",
    ]
    missing = [dn for dn in dns if directory.lookupByDn(dn) is None]
    if missing:
        raise RuntimeError("post-commit verification failed; missing: " + ", ".join(missing))
    return dns
