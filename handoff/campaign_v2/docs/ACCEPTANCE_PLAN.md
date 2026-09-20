# Acceptance plan — work to implement, not results claimed

These are runtime acceptance requirements for Grok Build. The supplied offline tests validate only the schemas, illustrative contracts, Decimal arithmetic and ledger DDL named in `VERIFICATION.md`. A row below is **NOT RUN** until a runtime receipt demonstrates it. Do not turn this checklist into a pass-count without executing the implementation.

For every row record: test ID; implementation commit; clean/dirty state; fixture/capture hash; mode; venue/account capability revision; input; expected observation; observed output; command; timestamp; result; limitations. Exercise a positive control alongside a negative detector. Tests use fake brokers and no credentials unless a separate live capability-test campaign was accepted.

## A. Campaign authority and policy

| ID | Stimulus | Required observation |
|---|---|---|
| A01 | Load every supplied example | All are unarmed. Changing mode to live does not issue a grant. |
| A02 | Accept one prepared paper campaign and send multiple qualifying events | Multiple machine-authorized intents without a human/chat approval per intent. |
| A03 | Model emits `approved:true`, bogus Risk PASS, or an approval phrase in a headline | No authority conferred; valid authenticated-control positive control works. |
| A04 | Edit a manifest after GO; replay its old grant or policy hash | Digest/generation mismatch blocks new risk; old history remains readable. |
| A05 | Revoke between intent reservation and actual send | Final writer checks generation, releases unsent reservations, sends no new risk. An already in-flight outcome remains explicitly unresolved until reconciled. |
| A06 | Full-loss research selection | No inherited 2.5%, 4.5%, 18%, 35% or four-name rejection; physical funds still constrain quantity. |
| A07 | Bounded-loss selection | Configured loss/risk checks apply including existing economic exposure; missing or malformed check is not silently disabled. |
| A08 | Overnight/midnight/restart/model outage | Durable grant survives; selected financial latches and NAV history also survive. |
| A09 | Missing accepted sizing implementation or strategy version | Clear configuration blocker, not arbitrary replacement percentage or unreviewed model sizing. |
| A10 | New eligible symbol versus derivative/new asset class | Qualified in-scope symbol can be selected by desk; out-of-scope class requires revised authority. |

## B. Capital, costs and target accounting

| ID | Stimulus | Required observation |
|---|---|---|
| B01 | Five or more funded permissible positions | No fixed name cap; all quantities/holds reconcile. |
| B02 | Notional above former 18% and 35% ceilings | Accepted under valid full-loss sizing; exact resource ceiling remains enforced. |
| B03 | Two simultaneous requests each fitting the same free cash | Serialized reservations prevent aggregate overspend; second request is resized or declined. |
| B04 | Working exchange hold already represented by local reservation | Held funds counted once, not twice or zero times. |
| B05 | Repeated tickets/strategies for the same asset | Inventory, exposure and exit reservations aggregate; identifiers do not create new budgets. |
| B06 | Buy leaves precisely the minimum exit quantity after fees | Exit feasibility evaluated with actual fee currency and rounding; dust handled explicitly. |
| B07 | Fee-negative signal versus otherwise identical fee-positive signal | First declines with decomposition; second reaches paper send. Unknown fees never mean zero. |
| B08 | Maker intended, taker executed; stop exits incur taker fees | Ledger uses actual fill fees; strategy statistics reflect true costs. |
| B09 | Cash deposit during campaign | Pending/unadopted funds cannot trade; contribution does not count as return or target attainment. |
| B10 | Broker interest, dividend, sale proceeds, reversal or fee | Classified under declared return policy; trades/fees/flows are reconciled without duplicate attribution. |
| B11 | Marked NAV crosses target but exit nets below it | TARGET_EXITING blocks entries; final shortfall reported without automatic revenge trade. |
| B12 | Target estimated with closed-market ETF marks | No false executable target success; marks carry freshness and venue availability. |
| B13 | Residual assets remain above $0 but below feasible minimum | RESIDUAL_ONLY outcome, not endless retry or buying dust to reach zero. |
| B14 | A strategy loses, target unchanged | No automatic size escalation based only on loss/remaining goal. |
| B15 | Selected positive floor is crossed by a simulated gap | Intended intervention and actual overrun both recorded; no claim of guaranteed loss bound. |
| B16 | Two venues with different funds | One venue cannot spend the other's resources; parent NAV is reporting, not transferable cash. |

## C. Order safety and recovery

| ID | Stimulus | Required observation |
|---|---|---|
| C01 | Response lost after exchange accepted order | SUBMISSION_UNKNOWN, reservation retained; reconcile original identity before resending. |
| C02 | Duplicate/reordered fill events | Unique exchange event keys, one accounting application, sequence reconciliation. |
| C03 | Partial fill races cancellation | Filled inventory adopted/protected; cancel acknowledgment never proves no fill. |
| C04 | Multiple entry fills create multiple conditional closes | Correct child linkage and total protection quantity; no invented OCO semantics. |
| C05 | Scale into an asset with an existing stop | Quantity-aware protocol, not blanket per-symbol refusal or duplicate full-quantity sell. |
| C06 | Profit exit requires stop cancellation | Certified transition, recheck inventory and intervening fill; no assumed atomic swap. |
| C07 | Pause/STOP while stops are working | Only new-risk authority removed; protection/accounting continue. |
| C08 | Flatten command during unavailable session | Pending-close state, preserved protection, resume when capable; never false FLAT. |
| C09 | Restart during SQLite transaction/outbox send | Consistent ledger; broker reconciliation resolves send ambiguity. |
| C10 | Second local process/legacy sender attempts order | Only credential-owning writer sends; raw helper cannot bypass gate. |
| C11 | Network partition and attempted cross-host takeover | No automatic dual writer based solely on expired local lease. |
| C12 | Unknown manual order or inherited old GTC outside recent query window | Discover/reconcile; no blind adoption or duplicate close. |
| C13 | Global dead-man cancellation expires | Simulation proves potential stop loss; default stop-protected lane does not arm indiscriminate timer. |
| C14 | Rate budget depleted by entries/amends | Coalesce/defer new entries and preserve urgent-action headroom. |
| C15 | Replay an old ticket after schema migration | Historical reporting works; live route refuses stale/foreign authority. |

## D. Venue, data and operational behavior

| ID | Stimulus | Required observation |
|---|---|---|
| D01 | Corrupt Kraken CRC, missing snapshot or execution gap | New risk disabled; rebuilt state and positive control restore automatically. |
| D02 | Kraken `AssetPairs` empty fee arrays | Use qualified account/pair fee source, otherwise fees-unknown; not zero. |
| D03 | Schwab unsettled proceeds / cash-account resale constraint | Reuse limited by verified account rules; no invented immediate buying power. |
| D04 | Old PDT constant injected into configuration | Rule has provenance/version/account applicability; no blind universal $25k/four-trade condition. |
| D05 | Account is margin-enabled but campaign disallows borrowing | Cash-funded orders only; margin buying power not eligible capital. |
| D06 | Equity fractional quantity unsupported through selected API | Round using actual route rules, not UI marketing; distinguish capacity from legacy cap. |
| D07 | Weekend/holiday/early close/DST/missing zone database | Correct venue schedules; fail visibly instead of fixed UTC-4 fallback; Kraken protection remains. |
| D08 | Twelve Data gives a price while Schwab wire is dark | Evidence labeled; not silently promoted to executable live broker data. |
| D09 | Token expires / stream denied / broker maintenance | Scoped degraded state, one actionable alert, rate-bounded recovery; other venue not unnecessarily stalled. |
| D10 | Qualified signal arrives immediately after free funds change | Event-driven reallocation, no wait for next 900-second launch or morning chat. |
| D11 | Qualified signal cannot trade | A durable blocker records its source, age and remedy; no fabricated missed profit. |
| D12 | No strategy meets after-cost conditions | Legitimate NO_NET_EDGE, distinct from feed failure or missing strategy. |
| D13 | All models/control chat unavailable | Registered deterministic strategy, protection and ledger continue within grant. |
| D14 | CPU/feed/disk pressure | Backpressure and preservation of required deltas; new entries pause before data corruption; audit fault visible. |
| D15 | Costly model review loop runs repeatedly | Explicit non-trading service budget controls calls; no unlimited external bill inferred from portfolio loss consent. |
| D16 | Historical drawdown under current-equity-as-peak bug fixture | Persisted flow-adjusted high-water mark catches the difference. |
| D17 | Report claims healthy/protected/profitable with source missing | UNKNOWN/INCOMPLETE status; valid-source positive control proves the detector works. |
| D18 | Legacy rollback requested after new fills | Rollback starts from reconciled current state; no restore of stale holdings/database. |
| D19 | Isolated new strategy release vs live process | Code hash/parameter changes explicit; no live-code mutation by model output. |

## First end-to-end demo

Use fictional paper capital, an accepted paper grant, a fake venue and versioned deterministic input. Exercise a qualifying trade, a fee-negative decline, one partial fill, a restart, and a released-capital re-entry with no new human approval. Display both venue sleeves even if only one adapter is complete. Every state change must have an evidence reference; the demo must not touch a live endpoint.

A second demo captures real public Kraken observations and replays them offline. A third uses account reads only to resolve the current Schwab/Kraken resources and capabilities. Live capability testing is a separate expressly accepted campaign; any real order, fee and residual is accounted for. Acceptance does not require pretending the strategy is profitable before an explicitly experimental run, nor does technical qualification establish economic edge.

## Performance and economics evidence

Run local event-to-decision latency and backpressure tests with the host, commit, sample count, capture hash, percentiles, observed backlog and duration. The proposed p95/p99 budgets in the implementation plan are design targets, not achieved metrics. Broker acknowledgment and fill latency are separately reported.

Evaluate full-loss and optional bounded-risk variants on identical dated out-of-sample/replay data, then a forward paper window. Include turnover, actual assumptions for fill probability/queue position, fees, maximum drawdown, terminal residual, outcome distributions and uncertainty. Report target attainment only over an explicitly bounded observation horizon with denominator and censored runs. There is no calibrated probability of doubling until there is evidence to estimate it; don't optimize target attainment by hiding ruin, costs or indefinite duration.
