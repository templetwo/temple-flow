# Supersession and decision record

## Current user direction

The September 20 conversation requests a full Funds-beast/Temple Flow restructuring, not just a Kraken feature. Anthony explicitly describes the existing Schwab and Kraken funds as money he can accept losing. The build must support a full-loss campaign and remove repetitive trade approvals and arbitrary inherited caps. This is a design direction, not a verified account snapshot or already-executed policy mutation.

The reported $432 is Schwab cash according to Anthony. It is not total equity, proven settled buying power or a Kraken balance. The $100/$200/zero example specifies a possible campaign, not a live order. No timeframe or guaranteed return was requested.

## Precedence inside this build packet

The new v2 operating model, replacement constitution, contracts and implementation plan govern the proposed build. `legacy/` preserves the original documents unchanged for provenance. On implementation, the accepted deployed campaign and actual venue capabilities govern runtime; this packet is not a self-executing grant.

| v1 statement or earlier discussion | v2 treatment |
|---|---|
| Kraken is a separate CV-only addition; don't replace equity wire | Superseded: both venues migrate to one campaign-operated control model, using incremental extraction rather than a big-bang rewrite. |
| Preserve 2.5%/4.5%/18% as universal risk ceilings | Superseded for v2 full-loss research. Optional bounded-loss profile retains configurable versions only when selected. |
| CV requires a special exemption to ordinary 18% notional cap | Superseded by common campaign sizing/ownership policy; no perpetual MV/CV exception maze. |
| Crypto entry default only outside the equity session | Superseded: continuous eligible Kraken operation; equity permission follows actual sessions/account capabilities. |
| Repeated session renewal/16:00 auto-disarm | Superseded by durable campaign authority. Signal validity is separate from grant life. |
| Per-ticket approval after fresh idea changes | Superseded within an active campaign: fresh machine evaluation may issue a new intent automatically. |
| A profit goal is an optimizer to maximize target-hit probability | Narrowed: target is goal/termination metadata. Do not optimize toward pathological loss-chasing or falsely claim estimated hit probabilities. |
| `capital <= 0` is a sufficient terminal rule | Corrected: no feasible funded order or residual-only state can terminate trading before numerical zero. |
| Cash underutilization by itself proves failure or missed profit | Corrected: distinguish eligible stranded cash, legitimate no-edge, reservations, settlement and holds. |
| Native Kraken mechanics, fee lookup, OTO caveats, deduplication, protection | Retain as technical reference and revalidate the actual capability; these are not arbitrary capital caps. |
| Discretionary flatten must wait for a fresh human card | Superseded where the prepared campaign includes a qualified exit protocol. No repeated card is needed within that accepted authority. |

## Acceptance versus implementation versus live state

“Anthony accepts the direction” is not “every proposed scalar is approved,” “the code is installed,” or “orders were sent.” The builder should resolve facts by reads, make genuine choices visible in one campaign preview, and minimize that one-time activation interaction. Once GO accepts the compiled revision, its normal trades are fully delegated.

## Preserved originals

The previous ZIP and its original spec/card/manifest are included. Their bytes are checked against the original archive in the package verification script. They are not edited to pretend they contained the campaign redesign. New packet integrity is in `MANIFEST.json`; hashes provide content integrity, not proof of economic correctness or strategy performance.
