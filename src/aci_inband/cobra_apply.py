"""Translate the JSON input into Cisco ACI managed objects and commit them.

This is the file to read if you normally configure ACI through the APIC GUI or
Postman and want to understand what Cobra is doing.  Cobra is not a different
configuration interface: it is a Python representation of the same APIC
Management Information Tree (MIT) exposed by the REST API.

The mapping is approximately::

    GUI form field  -> APIC managed object/attribute -> Cobra Python object

For example, creating a bridge domain named ``inb`` in tenant ``mgmt`` creates
an ``fvBD`` object at ``uni/tn-mgmt/BD-inb``.  In Cobra that becomes::

    tenant = fv.Tenant(root, "mgmt")
    bridge_domain = fv.BD(tenant, "inb")

The first argument is always the parent object.  Cobra calculates the full DN
from that parent and the object's naming properties.  Keyword arguments such as
``encap="vlan-3999"`` are APIC attributes, just as they are in REST JSON.
"""

from __future__ import annotations

from typing import Any

from .config import InbandConfig


class CobraUnavailable(RuntimeError):
    """Raised when the APIC-matched Cobra packages are not installed."""


def _cobra() -> dict[str, Any]:
    """Import Cobra lazily and return the imported names in a dictionary.

    Why import here instead of at the top of the file?

    * ``--plan`` only validates input and should work before Cobra is installed.
    * Cisco does not publish one universal ``acimodel`` package on PyPI.  The
      matching packages must come from the target physical APIC.
    * A clear error is more helpful than Python's raw ``ModuleNotFoundError``.

    Package guide for GUI/Postman users:

    * ``cobra.mit`` contains login, query, and commit mechanics.
    * ``cobra.model`` contains generated Python classes for APIC object classes.
    * The short module names match APIC class prefixes: ``fvBD`` is ``fv.BD``;
      ``mgmtInB`` is ``mgmt.InB``; ``infraAccPortGrp`` is
      ``infra.AccPortGrp``.
    """
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
    """Log in to APIC and return Cobra's handle to the object tree.

    Postman equivalent:

    ``POST {{apic}}/api/aaaLogin.json`` with an ``aaaUser`` JSON body.

    ``MoDirectory`` is the object used for both GET-like lookups and POST-like
    commits.  ``secure=True`` tells Cobra to validate the APIC TLS certificate;
    the CLI only turns this off when the operator explicitly supplies
    ``--insecure``.
    """
    cobra = _cobra()
    session = cobra["LoginSession"](
        apic.rstrip("/"), username, password, secure=verify_ssl
    )
    directory = cobra["MoDirectory"](session)
    directory.login()
    return directory


def _require_existing(directory, dn: str):
    """Perform a REST GET by DN and stop if a prerequisite is absent.

    We use this before adding selectors to leaf interface profiles.  The script
    intentionally refuses to invent a leaf-to-interface-profile association;
    choosing the wrong leaf there could disrupt a production fabric.
    """
    mo = directory.lookupByDn(dn)
    if mo is None:
        raise RuntimeError(f"required existing ACI object was not found: {dn}")
    return mo


def build_tree(directory, config: InbandConfig):
    """Build the desired APIC object tree in memory; do not send it yet.

    Cobra constructors attach children to parents locally.  At the end, the
    returned ``polUni`` root contains the complete desired change.  ``apply``
    later serializes this tree and sends one APIC configuration request.

    Re-running this function is safe from an ACI object-model perspective:
    APIC POSTs merge/update objects at the same DN rather than creating a second
    object with the same name.  It can still *change* attributes, which is why
    the CLI requires ``--plan`` review and an explicit ``--confirm``.
    """
    c = _cobra()
    fv, fvns, infra = c["fv"], c["fvns"], c["infra"]
    mgmt, phys, pol, vz = c["mgmt"], c["phys"], c["pol"], c["vz"]

    # ---------------------------------------------------------------------
    # ROOT AND MGMT TENANT
    # GUI: Tenants > mgmt
    # REST root: uni
    # ---------------------------------------------------------------------
    # polUni is the root of configuration policy in the APIC MIT.  Passing an
    # empty parent DN is the normal Cobra way to construct this root locally.
    root = pol.Uni("")

    # The built-in mgmt tenant normally already exists.  Describing it here
    # does not delete its other children; it gives our new objects a parent.
    # REST class/DN: fvTenant / uni/tn-mgmt
    tenant = fv.Tenant(root, config.tenant)

    # ---------------------------------------------------------------------
    # VRF, BRIDGE DOMAIN, AND SUBNET
    # GUI: Tenants > mgmt > Networking > VRFs / Bridge Domains
    # ---------------------------------------------------------------------
    # REST class/DN: fvCtx / uni/tn-mgmt/ctx-<vrf>
    context = fv.Ctx(tenant, config.vrf)

    # REST class/DN: fvBD / uni/tn-mgmt/BD-<bridge_domain>
    bd = fv.BD(tenant, config.bridge_domain)

    # GUI field: Bridge Domain > VRF
    # REST child: fvRsCtx, attribute tnFvCtxName
    # ACI models associations as relationship objects instead of storing the
    # referenced VRF name directly on fvBD.
    fv.RsCtx(bd, tnFvCtxName=context.name)

    # GUI: Bridge Domain > Subnets > Gateway IP and Scope
    # REST child: fvSubnet, attributes ip and scope
    # Example ip value: 192.0.2.1/24
    fv.Subnet(bd, ip=config.subnet_gateway, scope=config.subnet_scope)

    # Optional GUI action: Bridge Domain > L3 Configurations > Associated L3Outs
    # Each configured name becomes one fvRsBDToOut relationship.  The script
    # expects the actual L3Out to exist; it does not design routing for you.
    for l3out in config.l3outs:
        fv.RsBDToOut(bd, tnL3extOutName=l3out)

    # ---------------------------------------------------------------------
    # IN-BAND NODE MANAGEMENT EPG
    # GUI: Tenants > mgmt > Node Management EPGs
    # ---------------------------------------------------------------------
    # APIC stores node-management EPGs under a management profile.  The normal
    # profile is named default.
    # REST class/DN: mgmtMgmtP / uni/tn-mgmt/mgmtp-default
    management_profile = mgmt.MgmtP(tenant, config.management_profile)

    # GUI fields: Name and Encapsulation
    # REST class: mgmtInB; encap is written in ACI form, for example vlan-3999.
    inband = mgmt.InB(management_profile, config.epg, encap=config.encap)

    # GUI field: Bridge Domain
    # REST child: mgmtRsMgmtBD, attribute tnFvBDName
    mgmt.RsMgmtBD(inband, tnFvBDName=config.bridge_domain)

    # A node-management EPG can provide/consume contracts like a normal EPG.
    # These relationship objects reference existing contracts by name.
    for contract in config.provided_contracts:
        vz.RsProv(inband, contract)
    for contract in config.consumed_contracts:
        vz.RsCons(inband, contract)

    # GUI: Tenants > mgmt > Node Management Addresses
    #      > Static Node Management Addresses > In-Band Addresses
    #
    # One mgmtRsInBStNode relationship is created per APIC, leaf, or spine.
    # ``target_dn`` identifies the fabric node, while addr and gw are the node's
    # in-band interface values.  The prefix belongs on addr, not on gw.
    for node in config.nodes:
        mgmt.RsInBStNode(
            inband,
            node.target_dn,  # e.g. topology/pod-1/node-101
            addr=node.address,  # e.g. 192.0.2.101/24
            gw=node.gateway,  # e.g. 192.0.2.1
        )

    # ---------------------------------------------------------------------
    # OPTIONAL APIC-FACING LEAF ACCESS POLICY
    # GUI: Fabric > Access Policies
    # ---------------------------------------------------------------------
    # This section is optional because many fabrics already have the required
    # VLAN/domain/AAEP and port policy.  When omitted, only the mgmt tenant
    # objects above are built.
    if config.access_policy:
        ap = config.access_policy

        # REST class/DN: infraInfra / uni/infra
        infra_root = infra.Infra(root)

        # GUI: Pools > VLAN
        # REST: fvnsVlanInstP with one static fvnsEncapBlk child.
        # The start and end are identical because in-band management needs one
        # VLAN, not a range.
        vlan_pool = fvns.VlanInstP(infra_root, ap.vlan_pool, allocMode="static")
        fvns.EncapBlk(
            vlan_pool,
            config.encap,
            config.encap,
            allocMode="static",
        )

        # GUI: Physical and External Domains > Physical Domains
        # REST: physDomP plus infraRsVlanNs pointing to the pool DN.
        domain = phys.DomP(root, ap.physical_domain)
        infra.RsVlanNs(domain, tDn=str(vlan_pool.dn))

        # GUI: Policies > Global > Attachable Access Entity Profiles
        # REST: infraAttEntityP plus infraRsDomP pointing to the domain.
        aaep = infra.AttEntityP(infra_root, ap.aaep)
        infra.RsDomP(aaep, tDn=str(domain.dn))

        # GUI: Interface Policies > Policy Groups > Leaf Access Port
        # infraAccPortGrp does not live directly under uni/infra.  It belongs
        # under the singleton infraFuncP container at uni/infra/funcprof.
        function_profile = infra.FuncP(infra_root)
        port_group = infra.AccPortGrp(function_profile, ap.port_policy_group)
        infra.RsAttEntP(port_group, tDn=str(aaep.dn))

        # GUI: Interfaces > Leaf Interfaces > Profiles > <profile>
        #      > Interface Selectors
        #
        # The interface profile must already be associated with the intended
        # leaf switch profile.  We verify that it exists, then describe only the
        # selector/port block and policy-group relationship to merge into it.
        for interface in ap.interfaces:
            profile_dn = f"uni/infra/accportprof-{interface.interface_profile}"
            _require_existing(directory, profile_dn)

            # Reconstructing an object at an existing DN is how Cobra expresses
            # an update.  APIC merges this selector with other existing selectors.
            profile = infra.AccPortP(infra_root, interface.interface_profile)
            selector = infra.HPortS(profile, interface.selector, type="range")

            # A single-port selector is represented by a range whose start and
            # end card/port values are equal.
            infra.PortBlk(
                selector,
                interface.block,
                fromCard=str(interface.card),
                toCard=str(interface.card),
                fromPort=str(interface.port),
                toPort=str(interface.port),
            )

            # GUI field: Associated Policy Group
            infra.RsAccBaseGrp(selector, tDn=str(port_group.dn))

    return root


def apply(directory, config: InbandConfig) -> str:
    """Serialize and commit the in-memory tree to APIC.

    Postman equivalent: one or more POSTs to ``/api/mo/<dn>.json``.  Cobra's
    ``ConfigRequest`` handles serialization and the authenticated HTTP request.
    APIC validates the complete request and returns an error if a class,
    attribute, target DN, or parent-child relationship is invalid.
    """
    c = _cobra()
    request = c["ConfigRequest"]()
    request.addMo(build_tree(directory, config))
    directory.commit(request)
    return str(request)


def verify(directory, config: InbandConfig) -> list[str]:
    """GET the three anchor objects after commit and fail if any are absent.

    This is deliberately a structural check, not an end-to-end connectivity
    test.  A successful lookup proves APIC accepted the core objects; it does
    not prove the management VLAN is physically carried or routed upstream.
    """
    dns = [
        f"uni/tn-{config.tenant}/ctx-{config.vrf}",
        f"uni/tn-{config.tenant}/BD-{config.bridge_domain}",
        f"uni/tn-{config.tenant}/mgmtp-{config.management_profile}/inb-{config.epg}",
    ]
    missing = [dn for dn in dns if directory.lookupByDn(dn) is None]
    if missing:
        raise RuntimeError("post-commit verification failed; missing: " + ", ".join(missing))
    return dns
