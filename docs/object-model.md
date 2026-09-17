# ACI 5.2 object model

The implementation creates or updates this managed-object hierarchy:

| Purpose | Class | Distinguished name pattern |
|---|---|---|
| Management tenant | `fvTenant` | `uni/tn-mgmt` |
| In-band VRF | `fvCtx` | `uni/tn-mgmt/ctx-<vrf>` |
| In-band BD | `fvBD` | `uni/tn-mgmt/BD-<bd>` |
| BD-to-VRF relation | `fvRsCtx` | child of `fvBD` |
| Gateway/subnet | `fvSubnet` | child of `fvBD` |
| Optional BD-to-L3Out | `fvRsBDToOut` | child of `fvBD` |
| Node management profile | `mgmtMgmtP` | `uni/tn-mgmt/mgmtp-default` |
| In-band management EPG | `mgmtInB` | `.../inb-<epg>` |
| EPG-to-BD relation | `mgmtRsMgmtBD` | child of `mgmtInB` |
| Static node address | `mgmtRsInBStNode` | `.../rsinBStNode-[topology/pod-X/node-Y]` |

When `access_policy` is present, the script also creates a static `fvnsVlanInstP`
and `fvnsEncapBlk`, a `physDomP`, an `infraAttEntityP`, an `infraAccPortGrp`, and
interface selectors beneath existing `infraAccPortP` interface profiles. It does
not create or alter leaf switch profiles: each named interface profile must already
be mapped to the correct leaf.

## Boundary of the solution

This repository can attach the BD to existing L3Outs and attach existing contracts
to the management EPG. It deliberately does not invent an L3Out, external EPG,
routing protocol, or contract filters. Those are topology- and security-policy-
specific and should be designed separately.

