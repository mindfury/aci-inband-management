# Postman workflow

Import both JSON files in this directory, then select the imported example
environment. Replace every example value before sending a configuration request.

## Safe run order

1. Set `apic`, `username`, and the secret `password` environment values.
2. Replace `subnet_gateway`, `vlan`, and `nodes_json` with the approved design.
3. Leave `configure_access_policy` set to `false` when the required VLAN/domain/
   AAEP/APIC-facing port configuration already exists.
4. Send **Login to APIC**. The test saves the token and refuses a non-5.2 APIC.
5. Review **Preview generated management payload** in the Postman Console. It is
   disabled so it cannot be sent accidentally; its script is the documented,
   expanded version of the builder used by the live request.
6. Send **Create or update in-band management objects**.
7. If access policy is required, set `configure_access_policy=true`, verify every
   entry in `access_interfaces_json`, then run folder 3 in order.
8. Run both requests in folder 4 and inspect every returned child.
9. Perform the physical/routing/service validation checklist in the main README.

## JSON-array variables

Postman environment values are strings, so lists use JSON text:

```json
[
  {"pod_id": 1, "node_id": 101, "address": "192.0.2.101/24"},
  {"pod_id": 1, "node_id": 102, "address": "192.0.2.102/24"}
]
```

The request script defaults each omitted node gateway to the address portion of
`subnet_gateway`. The equivalent optional-list variables are `l3outs_json`,
`provided_contracts_json`, and `consumed_contracts_json`.

## TLS certificates

Do not globally disable certificate verification for production APICs. Import
the issuing CA certificate into Postman under **Settings > Certificates**, or add
the APIC host certificate as appropriate for your organization.
