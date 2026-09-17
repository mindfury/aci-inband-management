# Cisco ACI 5.2 in-band management

An idempotent Cobra SDK utility for provisioning in-band management on an ACI
5.2 fabric that currently relies on out-of-band management.

The tool builds the management-tenant BD, subnet, VRF, `mgmtInB` EPG, and static
node addresses. It can also build the VLAN pool/domain/AAEP/access-port policy
and bind it to selectors under existing leaf interface profiles.

Two equivalent implementations are included:

- A heavily annotated Python/Cobra CLI in `src/aci_inband`.
- An importable Postman collection and example environment in `postman/`.

The inline Python comments explicitly map Cobra constructors to APIC GUI paths,
REST classes, attributes, relationships, and distinguished names.

## Safety model

- TLS verification is on by default.
- Passwords are read from `ACI_PASSWORD` or an interactive prompt, never from JSON.
- `--plan` validates and displays the intended DNs without connecting to APIC.
- A real change requires an explicit `--confirm`.
- Existing leaf interface profiles are required. The script does not change their
  switch-profile association.
- Keep OOB management operational until every in-band address and path is verified.

## Install

Use a virtual environment and retrieve the exact Cobra packages from the target
physical APIC. Cisco distributes Cobra as two matching wheels: `acicobra` (SDK)
and `acimodel` (the APIC object model).

The utility itself requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/install_cobra.py --apic https://apic01.example.com
python -m pip install -e .
```

For a self-signed lab APIC, add `--insecure` only after validating the target.
The wheels are ignored by Git and should not be committed.

## Configure

Copy the example, then replace every example address, node ID, VLAN, and interface
profile/port with values from the target fabric:

```bash
cp examples/config.example.json config.json
aci-inband --config config.json --plan
```

Important fields:

- `subnet_gateway` is the BD gateway in prefix notation.
- Each node `address` is also in prefix notation; `gateway` defaults to the BD gateway.
- Use `subnet_scope: public` only when the subnet is to be advertised through an
  L3Out, and list the existing L3Out under `l3outs`.
- Omit `access_policy` if the VLAN/domain/AAEP/APIC-facing leaf-port policy already
  exists. If included, each `interface_profile` must already be associated with
  the intended leaf through a switch profile.

## Apply

```bash
export ACI_APIC=https://apic01.example.com
export ACI_USERNAME=admin
read -rsp 'APIC password: ' ACI_PASSWORD && export ACI_PASSWORD
aci-inband --config config.json --plan
aci-inband --config config.json --confirm
unset ACI_PASSWORD
```

## Postman

Import these two files into Postman:

- `postman/ACI-5.2-Inband-Management.postman_collection.json`
- `postman/ACI-5.2-Inband-Management.postman_environment.json`

Select the imported environment, replace every example value, and follow the
requests in numeric order. The access-policy folder is skipped unless
`configure_access_policy` is explicitly changed from `false` to `true`.

The collection dynamically builds the node-address, contract, L3Out, and
interface-selector children from JSON-array environment variables. See
[`postman/README.md`](postman/README.md) for the safe run sequence.

Post-change validation should include:

1. Confirm the APIC-facing leaf ports carry the configured VLAN.
2. Ping each in-band address from an authorized management source.
3. Test HTTPS/SSH/SNMP/AAA/NTP as applicable through in-band management.
4. Verify the in-band subnet is present only in the intended routing domain.
5. Leave OOB intact as the recovery path.

Run the local validation suite with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Design notes and references

See [`docs/object-model.md`](docs/object-model.md) for the MO hierarchy.

- [Cisco: Configure In-Band Management in ACI](https://www.cisco.com/c/en/us/support/docs/cloud-systems-management/application-policy-infrastructure-controller-apic/221867-configure-in-band-management-in-aci.html)
  (lab tested on ACI 5.2(8e))
- [Cisco DevNet: ACI Cobra SDK downloads](https://developer.cisco.com/docs/aci/cobra-sdk-downloads/)
  and [Cobra installation](https://cobra.readthedocs.io/en/latest/install.html)
- [CiscoDevNet `ansible-aci`](https://github.com/CiscoDevNet/ansible-aci): reference
  implementations for `mgmtInB`, `mgmtRsMgmtBD`, and `mgmtRsInBStNode`

The L3Out, external EPG, routing protocol, and contract-filter design are outside
this utility because they cannot be derived safely from generic input.
