# Venue-specific implementation requirements

## 1. Schwab — policy evidence is not account entitlement

Schwab's published article states that it planned to stop counting pattern day trades from June 8, 2026 under the changed framework. FINRA's June 4 guidance describes intraday margin requirements and funded cash-account rules. Therefore do not code a universal pre-2026 $25,000/four-trades lockout. Verify the actual account's enabled regime, restrictions and nonborrowed resources from current broker evidence. This package does not verify that account or authorize borrowing. [S1–S2]

Most equity trades settle T+1. Repeated cash-account use must distinguish settled funds from sale proceeds whose reuse/early sale can violate cash-account rules. The equities adapter needs instrument/lot-aware exit eligibility and settlement state, not a single `cash` number. A broker-displayed buying-power figure may include credit or conditional reuse, which the funded-only campaign cannot assume. [S2–S3]

Discover current account type, permitted sessions, intraday restrictions, free/settled resources, holds, all working orders and native order capabilities. Keep a source timestamp and actual account-bound evidence. Unknown remains UNKNOWN; do not automatically change account type or enable margin. Shared reporting may summarize both venues, but their tradable resources remain independent.

### Existing integration to reuse cautiously

Repository R9 identifies `TokenManager`, `schwab_tools`, GET book/orders/quotes routes and the `place_gtc_bracket`/`cancel_by_id` seams. Those paths and historical receipts are pointers for local inspection, not newly run tests. The raw bracket helper is documented as lacking some planner guards. Put the v2 intent validation at every credential-bearing mutation boundary; retire one-off scripts from the live permission path. [R9]

Before implementing extra order types, inspect the installed official schema/documentation and validate on the actual approved API/account. This review did not access authenticated Schwab Trader API specifications. Do not invent support for fractional ETF API orders, true bracket OCO conversion, private fill streams, arbitrary session stops or safe automatic token refresh indefinitely. Express each as a capability status and implement only the confirmed route. Use whole units where that is the verified granularity; do not let old whole-share rounding leak into Kraken.

### Concrete qualification cases

Test native entry-plus-protection acceptance, child activation/fill mapping, partial entry, cancel races, pending-activation behavior by session, scale-in with existing protective exits, cancel-replace ownership, terminal fill reconciliation and reconstruction of old still-working GTC orders. A native OCO relationship must be known before reserving its legs as exclusive. Closed-market restrictions are not a reason to refuse to plan or to halt Kraken; they are action-specific eligibility facts.

## 2. Kraken — native spot APIs, not a chat trading shortcut

Kraken publishes account/pair fee information via TradeVolume. The September 8 release notes deprecate fee arrays in AssetPairs; empty arrays are not zero fees. The current fee page displays entry-tier spot maker/taker rates of 0.40%/0.80%, but the account/pair result is authoritative for the bot. Never assume the displayed public tier is Anthony's fee. [K1–K3]

The first v1 fee arithmetic remains a hypothetical, not a quote: $100 equal-notional entry and exit costs 2 times $100 times the chosen fee fraction when the same rate applies. Exact quote-fee price breakeven for a fixed base quantity is `(1+f_entry)/(1-f_exit)-1`, before other costs. Maker entry does not imply maker emergency exit. Avoid double-counting spread already included in executable-price estimates.

### Adapter components

Use official WS v2 public and authenticated streams and REST for bootstrap/reconciliation. Decode instrument increments/minimums, status, ordered book updates and executions. Serialize Decimal values into Kraken's required numeric format without a lossy binary-float round trip. Keep raw number formatting when checksum construction requires it. Apply the specified top-book checksum; do not invent a sequence field for L2. Source documentation and protocol contract tests are required for each stream. [K8–K11]

New order requests support `conditional` close templates that produce a secondary order per primary fill. This is OTO behavior, not evidence of a simultaneous stop-and-target OCO bracket. Preserve identity and exact quantity for every actual child. Client IDs aid reconciliation; they are not proof of perpetual idempotency. [K4]

Atomic amend has order-type constraints, including exclusions for orders with attached conditional-close terms. Do not blindly amend a live OTO parent. Verify whether an already-created child stop supports the intended amendment. Unsupported profit exit/flatten transitions need the explicit stateful procedure in `EXECUTION_AND_ACCOUNTING.md`; claiming a native atomic operation where none exists is a mechanical failure. [K5]

Global CancelAllOrdersAfter is a timeout-triggered cancel operation, not liquidation and not presumed protection-safe. Default to expiring entry risk and selective owned cancellation while preserving native stops. Do not install a global timer that erases those stops on disconnect; another API key alone does not prove cancellation isolation. [K6]

Budget the venue's trading counters across transports and action types; rapid amendments/cancellations have different costs. Reserve capacity for protection and reconciliation, and do not evade limits with more keys. Market event throughput and order throughput are separate. [K7]

The documented beta WebSocket endpoint uses the production trading engine. Use the local fake adapter and captures for ordinary tests. `validate` is not a fill simulator. Private minimal-live probes require a separately accepted capability-test campaign and account resources; successful documentation parsing is not actual live qualification. [K8]

## 3. Capability cache, not recurring approval prompts

A capability record includes venue, account alias, feature, supported parameter set, source, test receipt, as-of time, code/protocol version and invalidation conditions. Reuse it until the relevant code, account permission, API contract or observable behavior changes. Do not ask Anthony to reapprove a known capability before every trade.

Example statuses: `DOCUMENTED_ONLY`, `FIXTURE_TESTED`, `ACCOUNT_VERIFIED`, `UNSUPPORTED`, `UNKNOWN`. Production feature selection uses the needed evidence class; unsupported features disable only affected strategies where possible. They do not necessarily prohibit all trading at the venue. Native protection should continue when research/feed inputs used for new entries are temporarily unavailable.

## 4. Statistical economics and mechanical qualification are separate

Mechanical qualifications prevent incorrect orders and accounting. They do not prove returns. Economic validation uses a fixed model/version, separated train/test windows, realistic fees/fills/latency and relevant no-trade/passive comparisons. An explicitly experimental full-loss campaign may accept unproven economics, but still requires a fully specified hypothesis, truthful labeling and correct mechanical execution.

All simulated performance must identify passive-fill assumptions and uncertainty. No artificial execution at candle highs/lows, no automatic full fills when a limit is touched, and no validation against the same holdout repeatedly optimized by the team. The local builder should keep statistical experiments reproducible without claiming this packet supplied a profitable strategy.
