# Prepared campaign preview — paper GO only

**Definition:** `examples/campaign_v2/campaign.paper_100_to_200.json`
**Profile:** `full_loss_research` (optional percentage/count caps **explicitly disabled**)
**Mode:** `paper`. **Economic evidence:** `EXPERIMENTAL_UNPROVEN`
**This preview is not a live Schwab/Kraken grant.** Accepting it authorizes the **paper** executor in an isolated state directory. It does not start launchd, move credentials, transfer funds, or send broker orders.

## Resolved (paper fixture)

| Field | Value |
|---|---|
| Campaign id | `TF-CAMPAIGN-PAPER-DEMO` revision 1 |
| Venue sleeve | `kraken_spot` / `PAPER_KRAKEN` (fake broker) |
| Adopted allocation | **$100** synthetic USD, empty positions |
| Objective | net-return multiple **2** ($100 → $200 **fixture**, not a live balance) |
| Sizing | `funded_weighted_v1` — full eligible cash allowed; **no** 18% / 35% / 2.5% / 4-name restoration |
| Fees as-of | fixture maker 0.40% / taker 0.40% (illustrative, not Anthony's Kraken tier) |
| Protection | native paper stop required on every entry fill |
| Writer | single paper writer permit `paper-writer-1` |
| Per-trade human approval | **false** |
| Borrow / short / derivatives / auto-transfer | **false** |
| Existing live Schwab stops | **untouched** (this path cannot see or cancel them) |

Disabled optional limits (all `enabled: false`, values null): per-position risk, daily loss, peak drawdown, position notional, ticket notional, position count.

## Unresolved (must stay unresolved until a live host read)

| Field | Status |
|---|---|
| Schwab account alias / settled cash / open orders | NOT READ. Do not use $432 or 2026-09-15 snapshot as GO numbers. |
| Kraken account alias / fee tier / balances | NOT READ. |
| Studio launchd ownership | NOT VERIFIED from this MacBook. |
| Live writer cutover | NOT PERFORMED. Legacy wire remains the only possible live sender; v2 must not run beside it. |
| Capability class for live OTO/OCO/amend | DOCUMENTED_ONLY / FIXTURE_TESTED in paper. ACCOUNT_VERIFIED: no. |

## GO meaning

`desk go` against this digest creates **one** paper grant. Repeating GO is idempotent. Subsequent paper fills do not need `approve TF-…`. STOP revokes new entries and keeps accounting. FLATTEN is not armed on live inventory.

A later live campaign requires a new revision with real snapshots, then Anthony's GO on the execution host after WP4/WP6. This handoff is not that GO.

## Engineering vs profitability

Paper cycle passing = mechanical reservation, fill idempotence, protection attach, restart reconstruction. It is **not** evidence that ETHA/IBIT/BTC strategies earn the $200 objective.
