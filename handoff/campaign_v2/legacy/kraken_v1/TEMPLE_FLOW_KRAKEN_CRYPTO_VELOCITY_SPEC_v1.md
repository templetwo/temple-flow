# Temple Flow — Kraken / Crypto Velocity
## Grok-team build specification · v1.0 · September 20, 2026

**Status: PROPOSED FEATURE, NOT LIVE AUTHORIZATION.**

**Repository baseline:** `templetwo/temple-flow` at commit `a5aa41b337c5f7522770225fb9a74121a1150283` (September 19, 2026).

**Product owner:** Anthony Vasquez Sr. **Desk owner:** Funds-beast / Temple Flow Grok team. **New specialist:** Crypto Velocity (`CV`).

This document specifies an implementation. It does not report a deployed integration, a tested strategy, current account balances, a verified Kraken account fee tier, or permission to place orders. Source review covered the repository documents, schemas and selected code described below, plus Kraken's current official documentation. No repository tests, private Kraken API calls, live daemon inspection, deposits or trades were performed for this specification. Ownership remains with the Temple Flow team; the general Sovereign Stack/HQ infrastructure is not made the trading operator by this proposal.

## 1. Product decision

Add a **persistent, event-driven Kraken spot trading lane** that the existing Grok-led desk can operate autonomously inside an explicitly approved mandate. Crypto Velocity continuously looks for short-horizon opportunities, selects approved strategy configurations, and explains its decisions. A deterministic execution service processes market events, applies Risk's sizing rules, manages orders and protects inventory without waiting for a model response on each tick.

The objective is **additional net returns from qualified opportunities outside the equity session**, not maximum ticket count. The architecture should support rapid repeated trades when an after-cost edge exists; it must also distinguish legitimate waiting from operational failure. There is no minimum trades-per-day requirement, forced deployment deadline for crypto, guaranteed daily profit, or automatic increase in capital following a good run.

Initial scope is **Kraken spot, USD-funded, long/flat**, with `BTC/USD` and `ETH/USD` as a proposed first whitelist. These are implementation candidates, not instructions to buy. Additional pairs can be researched in shadow and added through the same explicit universe-change authority. Margin, shorts, perpetuals, futures, staking, lending, automatic funding and withdrawals are outside v1.

Separate three quantities: market-event throughput, order-message throughput, and executed trading turnover. A high-throughput data engine need not be a high-fee account-churning engine.

## 2. Existing system: preserve the useful architecture, repair the drift

The current operating model separates **Think** (Funds-beast / chat) from **Act** (the Studio daemon). Grok Desktop is not the order wire. The September 15 amendment already delegates approval of Risk-PASS tickets and MV session operation to Funds-beast, and removes the open-position-count ceiling. Do not require Anthony to reapprove those settled delegations. Their current universe and session scope do not automatically include Kraken. [R1–R3]

Verified integration seams and migration issues:

| Existing surface | Verified property | Required treatment |
| --- | --- | --- |
| `scripts/temple_flow_strategy.py` | Pure `evaluate(symbol, features, rules)` strategy seam; proposals rather than sizing or sending; equity-cent rounding and daily features | Preserve the contract pattern, not the equity tick or daily-only assumptions. Add a separate crypto strategy implementation. |
| `scripts/temple_flow_wire.py` | The reviewed source still checks `opens >= cfg["max_opens"]` | Reconcile the source with September 15 §9 in a separately reviewed change. The live installed copy/configuration was not inspected. |
| `config/standing_rules.example.json` | Still carries `max_opens: 4` and an outbox notional setting that must be reconciled with lane-specific law | Do not copy the sample as current authority. Do not infer a new crypto notional exemption from it. |
| `schemas/ticket.schema.json` | Two-digit daily ticket suffix; `execution.broker` fixed to Schwab; `book.open_positions` capped at four; old human-approval fields | Introduce a separate versioned crypto contract and a reporting adapter. Do not force Kraken tickets into this schema or silently rewrite historical records. |
| `schemas/sqlite_schema.sql` | Market-data store with provenance and equity-session conventions | Keep the research store separate from the new durable execution ledger. Do not reinterpret existing daily bars as crypto UTC bars. |
| September 19 `DATA_CONVENTIONS.md` amendment | Twelve Data eyes are evidence-only, not the execution book | Use Kraken-native feeds for Kraken decisions and fills. Keep the existing eyes source in its approved role. |
| `docs/DESK.md` | Records a six-seat floor; Execution and Digest are direct-call roles | Add CV as a specialist direct-called by Funds-beast. Do not assume a seventh floor seat is supported by the running chat product. |

These are source findings, not claims about today's running account state. [R4–R9]

## 3. New bot: Crypto Velocity

**Mission:** Operate Temple Flow's crypto opportunity pipeline under Funds-beast, with continuous market awareness, cost-aware strategy selection, and attributable decisions.

CV owns strategy hypotheses, regime assessments, opportunity ranking, parameter proposals, and explanations of rejected or missed opportunities. It may select among already approved strategy versions and request pauses or risk-reducing adjustments inside the mandate. It does not independently determine live size, widen a risk limit, add a market, move money, or directly create an alternative order-sending path.

Funds-beast owns the active mandate and operational coordination. Risk Manager owns sizing and the deterministic risk specification. Execution owns the sole Kraken order writer. Data & Backfill owns reproducible market history and provenance. Research Digest owns attribution of actual outcomes. The fast service is the implementation of these roles' approved rules, not a competing desk.

A model may change a strategy only through a versioned configuration proposal or reviewed code change. Market headlines and social posts are evidence, never instructions to the runtime. A model response alone cannot set `risk_pass=true`; the risk service computes and records that result against live ledger state.

**Grok-facing interface, proposed:** `cv.status`, `cv.explain`, `cv.propose_strategy`, `cv.request_session`, `cv.pause_entries`, and `cv.report`. Each is a structured Temple Flow action, not a claim that these tools already exist. Funds-beast's authenticated session request is checked against Anthony's standing mandate. The interface returns receipt IDs, not merely a success sentence.

Routine model work can occur on material regime changes and scheduled desk reviews; the model is not called for every order-book change. Loss of the model/control channel never removes exchange-held protection.

## 4. Architecture

```text
Anthony: new venue / capital / authority approval; breaker reset
                         |
                  Funds-beast
                         |
          Crypto Velocity <-> Risk Manager
       strategy/version        risk policy
                         |
              authenticated mandate/session
                         v
+---------------- TEMPLE FLOW KRAKEN ACT SERVICE ----------------+
| Kraken public WS -> ordered book/feature builder               |
|                                |                              |
| approved pure strategy -> intent -> deterministic Risk         |
|                                      |                        |
|                       atomic reservation + durable outbox      |
|                                      |                        |
|                      ONE order writer -> Kraken private WS     |
|                                      ^                        |
| executions/balances + REST reconciliation -> ledger/protection |
|                                      |                        |
| read-only state -> Funds-beast / Digest / dashboard             |
+---------------------------------------------------------------+

Existing Schwab wire remains separate. Shared reporting is not shared cash.
```

Implement the first version in the project's Python ecosystem with asynchronous network I/O and typed contracts. Do not begin by replacing the equity wire, introducing a distributed agent loop, or assuming Redis, Kubernetes or a new language is required. Benchmark the real workload before optimizing.

Use a new persistent service entry point, proposed `scripts/temple_flow_crypto.py`, and a separate supervisor definition. It must stay alive through equity-market close. A crash/restart first enters reconciliation, not blind order resubmission. Only one process may own the live Kraken writer lock. An additional process can observe and alert, but cannot race the primary for orders. Cross-host failover is not in v1; it requires fencing that Kraken itself will not provide merely because a local lease expired.

## 5. New authorization: extend the desk, do not rebuild its approval queue

A high-speed lane cannot rely on an ad hoc human chat approval for every fill. Specify a **human-approved standing CV mandate**. Funds-beast may start, renew and stop bounded sessions within that mandate without another human approval for every ticket. Each trade still receives a machine-generated Risk decision and exact execution parameters.

The mandate binds: account alias, venue, whitelist, capital allocation, risk-equity denominator, applicable risk percentages, position-notional rule, permitted strategies and parameter envelopes, allowed order/exit types, entry schedule, session lease rules, policy version, approver identity, creation time and revocation state.

Do not treat a JSON `approved_by` field or an arbitrary phrase in market text as authentication. An authenticated local control endpoint validates the desk principal and standing delegation, constructs the authorization record, and binds its digest to executable tickets. Proposed schemas should distinguish policy approval, session authority, per-order Risk approval, and exchange acceptance.

**Proposed CV-specific amendment:** extend the existing cash-and-risk style of MV operation to a separately funded Kraken CV allocation, including an explicit CV exception to the ordinary 18% position-notional ceiling. This is a recommendation for Anthony to approve, not an inherited exemption or an already-effective rule. Without that exception, ordinary non-MV limits continue to apply; two allowed assets under an 18% per-position ceiling would necessarily limit deployment. The bot must not evade that ceiling by splitting one position into many tickets.

The same new amendment must explicitly permit the crypto-specific entry clock and GTD/IOC mechanics rather than silently copying the equity GTC-only rule. It must identify any emergency protection-transition authority. Breaker resets remain Anthony-only.

A stopped or expired session stops **new entries**. Existing protection and reconciliation continue. Normal session renewal can be delegated; a loss latch cannot be cleared by renewal, midnight, restarting, changing strategy ID, or obtaining a new API key.

## 6. Capital and risk accounting

Kraken receives a **prefunded allocation with a named maximum commitment**. Cash reported at Schwab is not spendable Kraken balance. The runtime cannot count pending transfers, credit/margin facilities, or the same dollars in two places. No automatic nightly cash shuttle is part of this build. Preserve any desired Monday equity reserve at its own venue rather than depending on an overnight crypto liquidation and transfer.

The existing constitution states 2.5% maximum risk per trade, 4.5% daily loss, 18% peak drawdown, mandatory hard stops and an ATR volatility filter. These remain ceilings, not recommended targets for each fast trade. Their extension to a new venue requires an explicit denominator: the recommended CV basis is the marked value of the authorized Kraken allocation, not total assets elsewhere on Kraken and not a historical Schwab balance. [R1]

For a proposed long entry, let `p` be worst permitted entry price; `s < p` the initial stop; `q` base quantity; `f_in` and `f_stop` fee fractions; and `slip_unit` a stressed exit-slippage allowance in USD/base-unit. Compute:

```text
risk_unit = (p - s) + p*f_in + s*f_stop + slip_unit
q_risk    = remaining_trade_risk_usd / risk_unit
q_cash    = spendable_allocated_usd / (p*(1+f_in))
q_final   = floor_to_qty_increment(min(q_risk, q_cash,
                                     position_headroom_qty,
                                     aggregate_risk_headroom_qty,
                                     liquidity_headroom_qty))
```

`remaining_trade_risk_usd` is net of risk already reserved for that economic position/strategy, including working orders. A stream of small tickets cannot reset the per-trade risk budget. Recompute every constraint after rounding, including exit feasibility and minimum order size. A strategy `qty_hint` can reduce size, not increase it.

The ledger reserves quote currency, fee buffers, inventory and risk **in the same transaction** as the executable intent. Reconcile local reservations with exchange-held funds without subtracting the same hold twice. Buys, working buys and inventory all consume allocation capacity. Sellable quantity excludes inventory already committed to other close orders.

**Recommended aggregate constraint, part of the new mandate:** remaining risk-to-stop across the CV inventory and working entries must fit the remaining CV loss budget. Track downside correlation with the equity desk's BTC/ETH-linked holdings. Do not call two venue positions diversification merely because the symbols differ.

Measure daily P&L from a defined America/New_York day boundary, net of fees and external cash flows, with unrealized P&L included. Maintain a rolling-24-hour loss view; applying the same loss ceiling to that window is an additional proposed mandate provision, not existing law. Use a cash-flow-adjusted/unitized NAV series for drawdown so deposits cannot hide losses or create performance. Persist all loss latches.

Preserve the constitutional ATR definition rather than substituting a one-minute volatility indicator for a daily requirement. The proposed crypto amendment should define completed UTC daily bars, a simple ATR14, and the preceding 60 completed daily ATR14 observations for the comparison. Preserve the 1.8 ratio and 50% reduction/skip behavior unless Anthony changes it. Warmup gaps are unavailable evidence, not zero volatility.

Desk reporting must show both venue-local and combined exposure. Closed-market ETF marks remain labeled closed-market marks; a live BTC price is a risk proxy, not a live executable ETF quote. Unexplained changes in holdings or unknown working orders block new CV risk. Simultaneous 24/7 new-risk operation by both venues requires atomic shared risk reservations or an approved prepartitioned risk budget; merely reading two dashboards does not enforce a common ceiling.

Stops constrain the intended exit mechanism; they do not guarantee a fill at the stop price, exchange availability, or a maximum realized loss. Gap and outage risk remain.

## 7. Cost-aware strategy requirement

Kraken's fee page and July 9 cross-platform fee-tier announcement show a published entry tier of **0.40% maker / 0.80% taker**, as checked September 20. The actual account/pair rate is not known here. [K1–K2]

Illustrative fees on a $100 buy and a $100 sell at that tier are approximately $0.80 maker/maker, $1.20 maker/taker, or $1.60 taker/taker, excluding spread and slippage. This is equal-notional arithmetic, not a promised breakeven price or this account's rate. For quote-currency fees and equal base quantity, exact price breakeven before other costs is `(1+f_entry)/(1-f_exit)-1`.

**No signal becomes an order solely because its gross target is positive.**

```text
conservative_net_edge_bps = expected_gross_move_bps
                           - entry_fee_bps - exit_fee_bps
                           - spread_and_impact_bps
                           - adverse_selection_allowance_bps
                           - uncertainty_buffer_bps
```

Use this approximate decomposition for diagnostics; the risk and expectancy calculation should use exact cash flows. Do not double-count spread if the entry and exit execution-price estimates already include it. Estimate expected movement from a fixed, out-of-sample-calibrated strategy model, not from an uncalibrated language-model confidence score. Require both a positive conservative edge and approved loss/distribution constraints.

For stop-based exits, budget taker fees. A passive entry is not a guarantee of a cheap exit. A post-only rejection does not authorize a market-order retry. Unknown fees prohibit new entries but never suppress an already required protective action.

Kraken deprecated `AssetPairs.fees` and `fees_maker` on September 8, 2026; the arrays are now empty. Obtain pair-specific rates from `TradeVolume`, refresh them with a recorded as-of time, and use actual fill fees for realized accounting. Empty arrays are **not zero fees**. [K3–K4]

### Strategy releases

**First candidate: `cv_momentum_pullback_v1`.** A deterministic short-horizon long/flat model using Kraken trade flow, spread, book imbalance and completed intraday trend features. It proposes a capped entry and an initial stop, takes no short position in declining regimes, and buys only when its out-of-sample expected move can cover the actual cost stack. Thresholds, feature windows and any statistical model must be versioned research artifacts; this specification does not invent a profitable set of numbers.

After entry, the initial live exit design is the native hard stop plus risk-reducing stop tightening when supported. Profit-locking rules must be simulated as stop-based exits, not as fictional fills at a target price. An intended holding horizon is not a guaranteed time exit.

**Additional candidates:** range reversion, then inventory-aware passive quoting. Keep each in shadow until its own after-cost evidence passes. Do not introduce martingale sizing, loss-chasing, self-trading, orders intended to mislead the market, or trading volume solely to earn a fee tier. Two-sided market making requires explicit inventory and exit mechanics; it is not achieved by repeatedly issuing buy and sell instructions from chat.

A longer required holding horizon is a legitimate consequence of fees. The engine can react quickly without pretending every small price oscillation is tradeable profit.

## 8. Kraken integration contract

**Transport:** public WS v2 `wss://ws.kraken.com/v2`; authenticated WS v2 `wss://ws-auth.kraken.com/v2`; REST base `https://api.kraken.com`. REST supplies authentication tokens, account bootstrap and reconciliation, not per-tick polling. Use current official signing instructions, a serialized per-key nonce source and credential-safe error handling. [K5–K6]

**Market and account state:** ingest `instrument`, `book`, `trade`, system status, `executions` and the current documented balances channel. Pair metadata supplies price/quantity increments and minimum quantity/cost. Store monetary values as Decimal internally and exact decimal strings in Temple Flow contracts; serialize the exchange's expected numeric format without a binary-float round trip. [K5, K7]

Maintain ordered L2 updates and verify the Kraken top-ten CRC32 checksum, even when subscribing to greater depth. A mismatch invalidates the book and requires a new snapshot. Do not invent an L2 sequence number. Track the execution channel's documented subscription sequence independently and reconcile on gaps. [K8–K9]

Use `cl_ord_id` as a persisted client identifier; UUID form avoids squeezing a high-volume ticket into an exchange text limit. Keep it distinct from Temple Flow `ticket_id` and websocket `req_id`. The latter correlates responses and is not an idempotency guarantee. [K5, K10]

Order capabilities to certify are limit/post-only entries, bounded GTD/IOC use, attached conditional closes, in-place child-stop amendments, single-order cancellation and account reconciliation. Route only spot-funded orders and use self-trade prevention. Do not rely on a margin `reduce_only` flag as a spot inventory constraint. Local reservations enforce spot sell limits. [K10]

**Rate governor:** budget exchange trading-counter cost, not just messages/second. Kraken shares trading limits across REST, WS and FIX; rapid cancellations/amendments have age-dependent costs. Use execution-counter feedback and reserve capacity for urgent protection and reconciliation. Opening additional keys or transports is not a workaround. Coalesce intent changes before submitting them; never drop raw book deltas before applying/checking them. [K11]

**Exchange availability:** consume status, pair status and maintenance/incident advisories. System state and account permissions determine allowed actions; an advisory is not a reason to assume orders are guaranteed executable. Stop new entries ahead of a relevant maintenance boundary, cancel owned entry remainders where possible, preserve valid protection and report residual exposure. [K3, K7]

## 9. Protection and order state: release-critical details

### 9.1 Attached protection is OTO, not an assumed OCO bracket

Kraken's documented `conditional` close template creates an opposite-side secondary order for each fill. That is not evidence of a simultaneous stop-plus-take-profit OCO bracket. The adapter must track actual child order IDs and coverage per fill, including partial entry fills and partial exits. [K10]

v1 entries must include the approved native stop template. After a fill, protection remains `PENDING_CONFIRMATION` until exchange evidence identifies the appropriate child. A missing child triggers a protection incident, cancels further entry risk where possible, reconciles account state and invokes only the emergency remediation authority already present in the mandate. Do not create a second sell while the first child's existence is unresolved.

Minimum-size partial fills and untradeable dust are explicit capability tests. Normal accounting tolerances may address exchange precision, not silently forgive meaningful unprotected inventory. The live capability is blocked if the chosen entry/close combination cannot protect its fills and there is no approved residual-handling procedure.

### 9.2 Atomic amendments have a material limitation

Kraken's atomic-amend guide excludes orders with conditional close terms attached and warns that unacknowledged websocket amend/cancel sequences are not guaranteed to execute in submission order. Therefore, do not assume an OTO entry can be continuously atomically repriced. Wait for a terminal/cancel result and reconcile any intervening fills before replacing its remainder. [K12]

The proposed profit-locking path tightens an already-created native stop child in place, **after that capability is separately verified**. Never widen its effective loss exposure. If child-stop amendments are unsupported, retain the original protection and disable that strategy's live profit-locking feature; do not substitute cancel-then-create invisibly. In-place order parameter changes are documented, but compatibility with the specific child must be evidenced. [K13]

A discretionary immediate profit exit, emergency flatten or stop-to-other-order conversion must have its own tested ownership/reconciliation procedure and explicitly approved protection-gap policy. There is no claim of atomicity where the venue does not supply it. Flat-by-a-clock strategies cannot go live using only a hoped-for trailing-stop fill.

### 9.3 A dead-man switch can conflict with protection

Kraken's `CancelAllOrdersAfter` cancels all client orders on timeout; it is not a liquidation operation. A global cancel mechanism must not be assumed to spare protective stops or another client's/manual order. [K14]

**Default for this stop-protected lane: no global dead-man cancellation.** Use expiring owned entries, selective entry cancellation, persistent exchange stops, heartbeat supervision and immediate protection alerts. Any alternative requires verified cancellation scope and a protection-preserving design; a second API key is not proof of isolation. Disable/resolve an inherited cancel timer before arming, with coordination where other Kraken trading shares the account.

### 9.4 Durable lifecycle

```text
CANDIDATE -> RISK_REJECTED
          -> AUTHORIZED -> RESERVED -> SUBMITTING
                -> SUBMISSION_UNKNOWN -> RECONCILING
                -> ACKNOWLEDGED -> OPEN / PARTIALLY_FILLED / FILLED
                -> REJECTED / CANCELED / EXPIRED

Inventory protection is a separate linked state:
NONE -> PENDING_CONFIRMATION -> PROTECTED -> CLOSING -> FLAT
                                  -> PROTECTION_INCIDENT
```

An acknowledgment is not a fill. A timeout is not a rejection. A cancel request is not proof the order did not fill. Entry termination is not proof the acquired inventory is flat.

Persist the exact intent and client ID before sending. If the network breaks after transmission, enter `SUBMISSION_UNKNOWN`, hold its reservation, query open/closed orders and executions, and resolve the existing identity before considering another send. If identity remains unresolved, do not retry blindly. Use unique execution IDs for deduplication and transactions for each ledger application. Promise recoverable at-least-once processing with deduplication, not impossible network-wide exactly-once delivery.

## 10. Storage and message contracts

Create a dedicated local execution database with migrations and transactional tables for mandates, session leases, order intents, reservations, orders, fills, inventory lots, protection links, fee snapshots, NAV observations, risk latches and append-only events. Monetary fields use exact decimal representations. Use WAL/durable commits under a single writer; serialize mutations rather than allowing every agent to edit SQLite.

Store high-volume raw market traffic in rotated, compressed capture files with checksums, timestamps and data-gap records. Keep replay manifests and all decision-relevant captures referenced by live tickets. Raw tick retention and storage budgets are operational settings, not implicit permission to delete audit evidence. Trading records, errors and reconciliation events are retained under an explicit policy. Do not log credentials or complete signed requests.

The crypto ticket contract is new and versioned. A minimum executable ticket carries:

```text
schema_version, ticket_id, venue, account_alias, pair, side
strategy_id, strategy_version, parameter_hash
mandate_id, mandate_revision, session_id, authorization_receipt
created_at_utc, intent_expires_at_utc, data_as_of_utc
book_snapshot_ref, book_valid, fee_snapshot_id, inventory_version
entry(type, price_cap, time_in_force, deadline, post_only)
protection(type, trigger, required_coverage)
size(base_qty_decimal, quote_reservation_decimal)
risk(calculation_ref, all_checks, decision_id, policy_hash)
cl_ord_id, request_id, execution_state, reason_codes
```

Use a collision-resistant identifier such as `TF-CV-<UTC date>-<UUID>`; keep legacy equity IDs valid in their existing lane. The shared report accepts both schema versions. The new ticket cannot reach the Schwab outbox and an equity ticket cannot reach Kraken accidentally.

Persist exchange timestamps, local receive time, monotonic duration measurements, instrument version and strategy inputs. Reports reference the same ledger events rather than reconstructing fills from conversational summaries.

## 11. Runtime schedule, human controls and observability

Data collection and inventory protection run continuously. Default **new-entry eligibility** is outside the existing equity regular session, using a real session calendar with holidays, early closes and daylight-saving behavior. Extending eligibility to all hours is a mandate setting. The 16:00 MV disarm rule stays in the equity lane; it must not stop CV's protection process. An entry near the next equity open must be acceptable under the mandate's carry policy or be declined.

Session mode (`observe`, `shadow`, `paper`, `live`) is distinct from entry permission (`paused`, `armed`, `latched`) and health (`healthy`, `degraded`, `reconciling`). At startup, reconstruct current positions and protection before allowing entries. A service process that exists but has no valid feed cannot display “operational” without qualification.

Provide **Pause entries**, **Disarm CV**, and **Request flatten** as distinct controls. Pause/disarm cancel only owned risk-increasing remainders when possible and preserve protection. A request to flatten follows the separate exit authority; it is not implemented as “cancel all.” Human breaker reset verifies the cause, account state and risk calculation before clearing the latch.

The first UI deliverable can be a read-only local status page plus JSON/CLI output, rather than a rewrite of the desk interface. Show actual mode, authority, data age, exchange state, account reconciliation, available/reserved capital, inventory, stop coverage, working orders, gross/net P&L, fees, realized slippage, open risk and the latest decision/receipt.

Every idle interval has a reason such as `NO_NET_EDGE`, `UNFUNDED`, `AUTHORIZATION_REQUIRED`, `SESSION_CLOSED`, `RISK_LIMIT`, `RATE_BUDGET`, `MINIMUM_ORDER`, `FEES_UNKNOWN`, `STALE_OR_INVALID_BOOK`, `UNRESOLVED_ORDER`, or `EXCHANGE_RESTRICTED`. Do not label all non-trading as healthy: distinguish an intentional rejection from a missed eligible signal and a broken process.

Use the existing desk's delivery route for morning/evening summaries; urgent notifications are protection incidents, latches, unresolved submissions and security/auth failures. Avoid a phone notification for every tick or quote change. A proposed morning crypto handoff should arrive before the existing 07:30 desk brief; this specification does not create that scheduled task.

## 12. Measurement and qualification

**Proposed engineering acceptance targets, not measured capabilities:** on the intended deployment host, replay a documented two-pair workload with 25-level books plus trades at 1,000 received messages/second for 30 minutes and a 10,000/second burst for 60 seconds. Measure receipt-to-durable-decision latency, aiming for p95 ≤100 ms and p99 ≤250 ms. Record hardware, process configuration, commit, capture hash, sample counts, backlog, memory growth and failures. Exchange/network latency is separately measured and is not included in those local targets. A failure of these targets leads to profiling or scope reduction, not a fabricated performance claim.

Measure order-rate capacity against the actual Kraken tier and action-cost model. Do not translate the data-ingestion target into permission to send thousands of orders per second. Book reconstruction processes every required update; overload closes new-entry eligibility rather than silently corrupting market state.

Strategy qualification is separate from plumbing qualification. Use temporally separated training/calibration and out-of-sample evaluation, weekend and weekday-off-hours segments, varying volatility, realistic passive fill/queue assumptions, exchange fees, slippage and order latencies. Model adverse selection and missed fills. Test stressed costs and compare against cash and a relevant passive benchmark. Keep the strategy version fixed during its validation window. Report uncertainty, sample dates, rejected signals and exposure as well as return; do not optimize repeatedly on the same holdout and call it independent proof.

Paper trading does not demonstrate execution quality. Kraken's official CLI includes no-auth paper trading and an MCP surface, which can help development and the desk's read-only tooling. It is not proof that an order would fill, nor a substitute for Temple Flow's Risk and execution ledger. Do not connect an unrestricted alternate live command path. [K15]

Kraken's documented beta WebSocket endpoint connects to the **production trading engine**. It is not a paper sandbox. The initial test harness is local and has no live credentials. `validate=true` checks an order without trading, but does not simulate fills or protection. Any later minimal-live capability test requires separate explicit authorization and accounted real capital. [K5, K10]

## 13. Acceptance suite

Each negative assertion requires a positive control: prove the detector can observe a valid event before trusting “nothing happened.” No live side effects are allowed in the ordinary test suite.

| Test ID | Scenario | Required evidence |
| --- | --- | --- |
| CV-01 | Start in default mode with funded-looking fixtures | No live network order path; explicit paper/shadow label. |
| CV-02 | Valid strategy with sufficient after-cost edge vs identical fee-eroded candidate | First reaches paper submission; second declines with exact cost breakdown. |
| CV-03 | Empty `AssetPairs` fee arrays / unavailable `TradeVolume` | No zero-fee fallback; no new live risk. |
| CV-04 | Corrupt a book update / reconnect without a snapshot | New entries stop; checksum-positive control restores eligibility after reconciliation. |
| CV-05 | Partial entry fills and multiple conditional children | Every fill linked; total protection/inventory reconciled without duplicate sells. |
| CV-06 | Fill races cancel; sell fee/dust/minimum-size boundary | Exact inventory and reservations; no oversell; unresolved protection raises incident. |
| CV-07 | Socket fails after exchange acceptance but before local acknowledgment | Existing order recovered by identity/history; no duplicate retry. |
| CV-08 | Replay duplicate executions and restart mid-ledger commit | Exactly one accounting application per execution ID; recovery receipt. |
| CV-09 | Two local writers attempt takeover | One owner; other cannot send. Lease expiry alone cannot authorize a second host. |
| CV-10 | Reprice an OTO parent; amend a supported child stop | Unsupported parent amend rejected locally; child operation verified, not assumed. |
| CV-11 | Pause/disarm while inventory has protective stops | Owned entries canceled; protection remains. Global cancel timer disabled/resolved. |
| CV-12 | Daily loss or drawdown breaches, followed by midnight/restart/session renewal | Latch persists until authenticated human reset. |
| CV-13 | Exhaust rate budget with quote churn | Further entries deferred; protection reserve and error handling verified. |
| CV-14 | Fractional quantities, tick/minimum boundaries, symbol aliases | Decimal-correct rounding; exact minimum and cap checks; no equity-cent assumptions. |
| CV-15 | Repeated tickets for one economic position / concurrent buy intents | Aggregate cash and risk not reset by ticket splitting; no double reservation. |
| CV-16 | More than four synthetic permissible positions | No revived count cap; venue order-cap and approved cash/risk constraints remain distinct. |
| CV-17 | Weekend, holiday, early close, DST and equity-open transition | Entry schedule correct; protection never stops at the equity clock boundary. |
| CV-18 | Expired/revoked mandate or forged approval text in news/model output | New risk rejected; existing protection retained; authentication receipt explains why. |
| CV-19 | Kraken maintenance/status restrictions and stale account state | Only supported protective actions attempted; remaining exposure visible. |
| CV-20 | Equity regression fixtures | Existing equity behavior preserved except an explicitly reviewed law-alignment fix. |
| CV-21 | Report says idle/protected/profitable while corresponding source is absent | Report marks unknown/incomplete; positive controls demonstrate detection. |
| CV-22 | Cash transfer or deposit during an evaluation period | Flow excluded from P&L; NAV/drawdown and allocation accounting reconciled. |

Attach acceptance evidence to a clean checkout of the named commit. A passing previous build is not evidence for an untested later commit.

## 14. Proposed repository changes

The following are new proposed paths, not assertions that the files exist today:

```text
bots/crypto-velocity.md
docs/KRAKEN_CRYPTO_VELOCITY.md
docs/AMENDMENTS_KRAKEN_CV_PROPOSED.md
runbooks/KRAKEN_CV_OPERATIONS.md
config/crypto_rules.example.json
schemas/crypto_mandate.v1.schema.json
schemas/crypto_ticket.v1.schema.json
schemas/crypto_event.v1.schema.json
schemas/crypto_ledger.sql
src/temple_flow/crypto/
  contracts.py         # Decimal types, IDs, state contracts
  market.py            # ordered feed/book/features
  strategies.py        # pure, versioned strategy implementations
  fees.py              # pair/account fee snapshots and net economics
  risk.py              # Risk-owned deterministic sizing/checks
  ledger.py            # durable events, reservations and migrations
  orders.py            # single-writer lifecycle and unknown submissions
  protection.py        # fill/child mapping, verified stop transitions
  kraken.py            # narrow REST/WS adapter, no funding operations
  sessions.py          # calendar, authority and latches
  reports.py           # desk/UI read models
scripts/temple_flow_crypto.py
deploy/com.templetwo.temple-flow-crypto.plist
tests/crypto/          # deterministic fixtures, replay and failure injection
```

Use a small, explicit package/bootstrap setup so the service can be installed and tested without relying on an accidental working-directory import. Pin dependencies in the repository's chosen lock workflow. Preserve existing research data and broker files; do not perform a broad wire refactor as a prerequisite.

Update roster, operating-model, universe and data-convention documents with references to the new lane. Keep the proposed amendment clearly separate from enacted law until Anthony approves it. Resolve old schema/sample/risk-code contradictions explicitly, with migrations and regression tests; do not silently change historical ticket meaning.

## 15. Build sequence and team handoff

**M1 — contracts and law alignment.** The integration lead produces versioned contracts, an authority matrix and the separately reviewed `max_opens` drift repair proposal. Deliver a schema-valid paper example, migration tests and a clear list of genuinely new approvals. No live activation.

**M2 — real market observations.** Data/adapter owners deliver Kraken feed capture, book verification, metadata normalization, account read interfaces and status output. Deliver a replay manifest with raw-feed provenance and an intentional-corruption test.

**M3 — cost-aware paper trading.** Strategy/Risk owners deliver one pure candidate strategy, conservative fee/impact modeling, position/risk reservations and a local fill simulator. The vertical slice is market event → candidate → Risk → paper order/fill → protection accounting → desk report. Both profitable-looking and fee-rejected fixtures must work.

**M4 — recoverable execution.** Execution owner implements native order capability mapping, conditional child accounting, unknown-submit reconciliation, rate budgeting, single-writer protection and fault injection. All live functions remain disabled outside explicit capability-test authorization.

**M5 — continuous operation and reporting.** Integrate the specialist bot and dashboard, calendar behavior, alerts, restart runbook, loss latches and clean-checkout evidence. Run a continuous soak spanning an equity-close transition and an off-hours period; record both service health and intentional idle decisions.

**M6 — explicit activation decision.** Anthony approves the new venue/whitelist, funded allocation, CV notional treatment, denominator, session mandate and exit/remediation scope. Risk and Execution present the mechanical qualification and strategy evidence separately. A minimally funded, specifically authorized live capability test establishes actual fills, fees and protection behavior. Expansion requires review of those receipts; it is never unlocked automatically by a profit number.

Parallelize M2 and strategy research after M1 freezes the contracts. The reviewer should not be the sole author of the execution changes. Funds-beast remains the desk owner through all milestones.

## 16. Disabled configuration example

This is a planning template. Null approvals and capital fields are intentionally non-armable. The percentages reproduce the present ceilings; adopting the proposed crypto denominator and exception still requires the new amendment.

```json
{
  "schema_version": "crypto_rules.v1",
  "enabled": false,
  "mode": "shadow",
  "venue": "kraken_spot",
  "account_alias": null,
  "allowed_pairs": ["BTC/USD", "ETH/USD"],
  "entry_schedule": "outside_equity_regular_session",
  "clock_timezone": "America/New_York",
  "capital_budget_usd": null,
  "risk_equity_basis": "PROPOSED_authorized_kraken_allocation_nav",
  "position_notional_policy": "PENDING_EXPLICIT_CV_AMENDMENT",
  "max_open_position_count": null,
  "max_risk_per_trade_fraction": "0.025",
  "daily_loss_limit_fraction": "0.045",
  "peak_drawdown_limit_fraction": "0.18",
  "native_protection_required": true,
  "global_dead_man_cancel": false,
  "margin_enabled": false,
  "funding_operations_enabled": false,
  "approved_strategy_versions": [],
  "mandate_id": null,
  "approval_receipt": null,
  "live_capability_receipt": null
}
```

A missing field must not mean permission. Paper defaults cannot become live values by changing only `mode`. Do not use this example to override the live equity configuration.

## 17. First meaningful demonstration

With real Kraken market data and a paper-only ledger, show CV active after the equity session ends. Produce an attributable opportunity, apply the cost and risk calculations, execute only when the paper rules allow it, track its protected inventory and show net P&L. Interrupt the connection, restart the service, reconstruct state, and prove that a duplicate order was not created. Then inject a fee increase and show the same gross signal correctly rejected.

**Completion means the next competent Temple Flow builder can recover the policy, market evidence, order state, stop coverage and accounting from the artifacts without reconstructing them from a chat participant's memory.**

## Sources and verification map

Repository links are pinned to the inspected commit. External API behavior was checked September 20, 2026 and must be revalidated at implementation/capability qualification. Summaries above are deliberately narrower than a claim of exhaustive repository or exchange audit.

[R1] Risk constitution: https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/RISK_CONSTITUTION.md
[R2] September 15 amendments: https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/AMENDMENTS_2026-09-15.md
[R3] Operating model: https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/OPERATING_MODEL.md
[R4] Strategy seam (reviewed lines 1–210): https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/scripts/temple_flow_strategy.py
[R5] Wire (targeted `max_opens` source search, not whole-file audit): https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/scripts/temple_flow_wire.py
[R6] Standing rules example: https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/config/standing_rules.example.json
[R7] Ticket schema and SQL market store: https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/schemas/ticket.schema.json ; https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/schemas/sqlite_schema.sql
[R8] September 19 evidence-only amendment / commit: https://github.com/templetwo/temple-flow/commit/a5aa41b337c5f7522770225fb9a74121a1150283
[R9] Desk roster: https://github.com/templetwo/temple-flow/blob/a5aa41b337c5f7522770225fb9a74121a1150283/docs/DESK.md
[K1] Kraken fee schedule: https://www.kraken.com/features/fee-schedule
[K2] Cross-platform fee-tier changes (July 9, 2026): https://support.kraken.com/articles/cross-platform-fee-tier-changes
[K3] Kraken release notes (September 8 fee-field deprecation; September 1 maintenance advisories): https://docs.kraken.com/exchange/changelog
[K4] Account/pair fee lookup: https://docs.kraken.com/api-reference/account-data/get-trade-volume
[K5] WS versions, endpoints, production/beta and numeric precision: https://docs.kraken.com/exchange/guides/websockets/introduction
[K6] WebSocket authentication: https://docs.kraken.com/exchange/guides/websockets/authentication
[K7] Instrument metadata: https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/instrument
[K8] L2 book: https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/book
[K9] Executions: https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/executions
[K10] Add order: https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/add_order
[K11] Trading rate limits: https://docs.kraken.com/exchange/guides/general/ratelimits
[K12] Atomic amendment constraints: https://docs.kraken.com/exchange/guides/general/amends
[K13] Amend order parameters: https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/amend_order
[K14] Global timeout cancellation: https://docs.kraken.com/api-reference/trading/cancel-all-orders-after-x
[K15] Official CLI / paper trading: https://docs.kraken.com/home/cli
