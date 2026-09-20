# Sources and verification boundary

Checked September 20, 2026. Repository main resolved through the GitHub connector to `a5aa41b337c5f7522770225fb9a74121a1150283`, authored September 19, 2026 at 21:34:15 UTC. No repository code was executed, no live daemon or broker configuration was inspected, and no private exchange API call or order was made. This is a source-based implementation design, not a production audit or performance claim.

## Repository evidence

**[R1] Risk constitution.** Full file read in this conversation at pinned unchanged baseline.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/RISK_CONSTITUTION.md

**[R2] September 15 amendments.** Full file; delegated Risk-PASS/MV authority and section 9 count-cap removal.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/AMENDMENTS_2026-09-15.md

**[R3] Operating model.** Full file; Think/Act separation and existing authority.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/OPERATING_MODEL.md

**[R4] Desk roster.** Full file; six-seat floor is repository description, not live Grok product verification.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/DESK.md

**[R5] Ticket schema.** Full file; historical two-digit ID, Schwab-only route and hard scalar/count bounds.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/schemas/ticket.schema.json

**[R6] Example standing rules.** Full file; sample configuration, not evidence of installed settings.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/config/standing_rules.example.json

**[R7] Execution wire.** Selected source lines 1–250 plus targeted code searches; NOT exhaustive whole-file audit or live runtime inspection.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/scripts/temple_flow_wire.py

**[R8] Strategy seam.** Selected source lines 1–210; pure evaluate contract and equity/daily assumptions.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/scripts/temple_flow_strategy.py

**[R9] Bracket helper report.** Full file; historical runtime attestations not independently reproduced.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/BRACKET_HELPER.md

**[R10] Launcher.** Full file; StartInterval 900 in checked-in source, not measured installed daemon cadence.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/deploy/com.templetwo.temple-flow-wire.plist

**[R11] Market-source conventions.** September 19 commit patch read; evidence-only Twelve Data role.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/DATA_CONVENTIONS.md

**[R12] Research market-data DDL.** Full file; not a durable execution journal.

https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/schemas/sqlite_schema.sql

## Official external sources

These pages were retrieved during this work. Recheck account-specific behavior at capability qualification; a general vendor page is not proof of an individual account's permissions.

**[S1] Schwab — SEC approves scrapping $25,000 day-trader minimum.** Published April 16, 2026; describes new rules and Schwab planned June 8 change. Do not infer completion for this user or copy the obsolete threshold as current universal law.

https://www.schwab.com/learn/story/sec-approves-scrapping-25000-day-trader-minimum

**[S2] FINRA — frequent intraday trading.** Current investor explanation of cash/margin requirements and settlement. Account/firm house restrictions remain relevant.

https://www.finra.org/investors/insights/frequent-intraday-trading

**[S3] Schwab — cash-account trading violations.** Funding, settlement and good-faith/free-riding restrictions are distinct from internal strategy caps.

https://www.schwab.com/learn/story/avoid-these-violations-when-trading-cash

**[K1] Kraken fee schedule.** Published entry tier shown as 0.40% maker / 0.80% taker when retrieved. Actual account/pair tier unverified.

https://www.kraken.com/features/fee-schedule

**[K2] Kraken TradeVolume.** Account/pair fee lookup; no authenticated call was made here.

https://docs.kraken.com/api-reference/account-data/get-trade-volume

**[K3] Kraken changelog.** September 8, 2026 fee-array deprecation in AssetPairs; empty arrays are not free execution.

https://docs.kraken.com/exchange/changelog

**[K4] Kraken WS v2 Add Order.** Conditional secondary closes, order parameters and identifiers; capability-specific fill/protection behavior remains to test.

https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/add_order

**[K5] Kraken atomic amends guide.** Attached conditional-close limitation and ordering caveats.

https://docs.kraken.com/exchange/guides/general/amends

**[K6] Kraken cancel-all after timeout.** Cancel operation is not liquidation or a promise to preserve protective orders.

https://docs.kraken.com/api-reference/trading/cancel-all-orders-after-x

**[K7] Kraken trading limits.** Shared weighted transaction counters; message rate and trade turnover are separate concepts.

https://docs.kraken.com/exchange/guides/general/ratelimits

**[K8] Kraken WebSocket introduction.** Beta API uses production trading engine; numeric precision and stream/connection conventions.

https://docs.kraken.com/exchange/guides/websockets/introduction

**[K9] Kraken Instruments.** Reference data, symbols, precisions and trading parameters; instrument visibility is not account eligibility.

https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/instrument

**[K10] Kraken L2 book.** Book snapshot/update/checksum contract.

https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/book

**[K11] Kraken executions.** Execution events, fills and order state.

https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/executions

## User facts and unverified values

Anthony reports $432 idle Schwab cash and says all currently funded capital in the Schwab and Kraken research accounts can be lost without affecting his essential needs. Those are his stated balance and risk preference, not a fresh bank-confirmed snapshot. The Finances account read returned no linked accounts; no total balance, settled funds, Kraken tier or account eligibility was verified. The $100-to-$200 campaign is illustrative. Production prepare must obtain actual balances, adopted holdings, holds, orders and permissions through each account's qualified read path.

## Earlier artifacts

The original Kraken v1 ZIP, spec and bot card were available in this conversation and read in full. Their original bytes are copied under `legacy/`; a SHA-256 and ZIP member comparison are checked by `tools/verify_bundle.py`. See `docs/SUPERSESSION_AND_DECISIONS.md` for what changed. The new build-plan scenarios and timing budgets are requirements, not completed trading experiments.

## Not represented as verified

The full repository's current effective configuration; local-only changes; installed daemon state; complete order history; credentials; API entitlements; account settlement restrictions; current positions or account values; end-to-end live execution; performance; strategy net edge; and any probability of doubling. The package test report is narrower: offline schema, arithmetic, DDL and package-integrity checks on the files shipped here.

No Stack governance or brokerage state was written. The current turn did not obtain a fresh Stack boot read; the live repo and user direction anchor this handoff. Temple Flow ownership stays with Funds-beast and its implementation team, not a general HQ registry.
