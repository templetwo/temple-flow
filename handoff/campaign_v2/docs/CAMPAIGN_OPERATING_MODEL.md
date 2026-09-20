# Campaign operating model

## 1. The authorization unit is a campaign

A campaign is a durable permission to operate a named set of already-funded account resources under one immutable policy revision. It contains objectives, scope, inventory ownership, exit behavior, a sizing-policy envelope and revocation state. A trade intent is an execution artifact within that grant, not a request to Anthony.

The desired control surface is:

```text
prepare campaign -> show exact preview -> GO
                                      |
                          permanent campaign record
                                      |
               streams -> policy -> reserve -> execute -> reconcile
                                      |
                                report / adapt
```

Proposed commands to implement: `desk prepare`, `desk go`, `desk status`, `desk explain-cash`, `desk pause`, `desk resume`, `desk stop`, `desk flatten`, `desk report`. A UI can use the same authenticated control API. Do not implement authorization by scraping untrusted text for the word GO. A button or exact command must resolve one prepared ID and digest; ambiguity fails once, not for each trade.

## 2. Profile for Anthony's stated loss tolerance

`full_loss_research` permits loss of the entire explicitly adopted, funded allocation. It removes inherited percentage loss breakers, position-count ceilings, and arbitrary fractional notional caps as universal rules. Exposure may use all eligible capital after funding and execution reserves; permission for 100% exposure is not a requirement to hold it.

Existing gains can compound within the same campaign. New deposits and unrelated positions do not automatically enlarge it. Initial holdings and cash are enumerated in the arming snapshot. A supported pre-existing long can be adopted with its cost/protection facts; an unsupported asset is visible and quarantined from autonomous changes until its handling is in the prepared plan. Cash from sales remains owned by the same campaign, but only becomes reusable when the venue/account rules permit it.

A separate `bounded_loss` profile supports selected per-position risk, daily loss, drawdown or capital floors. These are campaign choices, not hidden constants. Disabled loss checks are explicit objects with `enabled:false`, `limit_fraction:null` and a reason. A missing check definition is invalid configuration. No agent may convert a bounded-loss grant into full-loss by returning a high confidence score.

**Zero is a consent boundary, not a precise exchange stop.** Spot inventory can remain above zero while below minimum tradable size. Enter `CAPITAL_EXHAUSTED` or `RESIDUAL_ONLY` when no feasible funded order remains, retaining truthful residual valuation and protection where possible. Never spend the final cash on needless fees just to make the balance equal zero. A positive floor is likewise not guaranteed against gaps, halts or exchange failure.

## 3. Runtime states and permitted actions

Use three orthogonal state dimensions rather than one overloaded boolean:

| Dimension | Values | Meaning |
|---|---|---|
| Campaign lifecycle | DRAFT, PREPARED, RUNNING, TARGET_EXITING, STOPPED, COMPLETED, CAPITAL_EXHAUSTED | Business intent and termination |
| Entry permission | DISARMED, ENABLED, PAUSED, REVOKED | Whether new risk can be authorized |
| Health per venue | READY, DEGRADED, RECONCILING, AUTH_REQUIRED, MANUAL_REVIEW | Whether actual state is trustworthy |

Protection and accounting continue when entries are paused, revoked or stopped. COMPLETED requires resolved orders and inventory, not merely a successful cancel call. `RESIDUAL_ONLY` and `TARGET_EXIT_SHORTFALL` are outcome reason codes, not extra implicit lifecycle states. A target attempt may finish with shortfall; that is an outcome, not authority to chase the original target.

A transient feed failure places the affected venue in RECONCILING. It returns to READY after the deterministic recovery conditions hold, without another human approval. A revoked grant, unknown external order, breached selected financial latch or unresolvable ownership conflict needs its defined resolution. Fresh GO cannot erase an earlier loss history or reset unitized NAV invisibly.

## 4. Team decisions versus order decisions

Funds-beast owns the campaign's choices inside the accepted envelope: strategy selection, allocation preferences, in-envelope parameter changes, routine pauses and resumption after automatically resolved faults. It may concentrate in a suitable opportunity or leave capital unallocated when there is no defensible trade. It must surface structural blockers and propose a bounded correction rather than narrate them indefinitely.

Data/Technical/Macro work asynchronously. Each package carries as-of time, feature definition, source and expiration semantics. Macro is not a mandatory live-chat signature on every ticket. An approved rule can make a known event window reduce exposure; it cannot convert an unanswered chat into an indefinite mystery veto.

Risk is a deterministic service owned by the Risk role. It evaluates the complete proposed order against the accepted policy and fresh state, chooses executable quantity, and emits a decision receipt. Execution independently verifies the receipt/state binding at the credential boundary. Receipt verification is a fast local operation, not another agent deliberation. If state changed materially, recompute; do not seek another human approval.

No model has to run in the critical path. Models may emit fresh strategies or opportunistic proposals, but approved deterministic strategies continue to operate without them. Out-of-envelope proposals wait for a campaign revision while the existing campaign remains active where valid.

## 5. Sizing without arbitrary inherited caps

Remove universal 18%, 35% and four-name values. Keep a versioned sizing algorithm. A useful contract returns desired notional based on strategy state, volatility, estimated cost/impact, current inventory and the campaign's selected risk preference. Risk converts this to an executable quantity.

```text
q_strategy = desired_notional / worst_permitted_entry_price
q_cash = eligible_owned_cash / (entry_price * (1 + entry_fee_fraction))
q_liquidity = size supportable inside the accepted impact envelope
q_exit = size whose chosen exit/protection mechanics are qualified
q_optional_risk = selected remaining position/campaign risk budget / unit risk
q_final = floor_to_increment(min(applicable q values))
```

In full-loss mode there is no mandatory inherited `q_optional_risk` percentage. Physical funding, liquidity and valid ownership still bind. In bounded-loss mode it must include entry/exit fees, stressed slippage and existing position plus entry reservations. Do not multiply the allowance by generating new ticket IDs. Recompute after rounding and fee-currency treatment.

Quantity should not grow simply because the target is farther away or the last trade lost. The goal is a reporting/termination condition, not an instruction to escalate risk. Validate parameter selection on out-of-sample or explicitly experimental evidence. A language-model probability is not calibrated evidence of edge.

## 6. Universe and strategy delegation

Replace hard-coded live symbols with an approved eligibility policy and versioned registry. Proposed v2 product scope is fully paid long/flat exchange-listed cash equities and unleveraged ETFs at Schwab, and accessible USD spot crypto at Kraken. No derivatives, leverage, shorts, borrowed assets or automatic funding operations.

Funds-beast can promote another instrument inside that scope when its venue permissions, tick/minimum data, liquidity/impact conditions, exit mechanism and strategy inputs qualify. Anthony need not approve every symbol separately once he accepts that eligibility policy. A broader asset class or jurisdiction is a scope change. Reference examples retain ETHA/IBIT and BTC/USD/ETH/USD for compatibility tests, not as permanent universe limits or buy recommendations.

Strategy code is versioned and mechanically validated before being loaded. Configurations can change inside ranges accepted by GO. Full-loss willingness does not give a model permission to patch the live Python process or expand network/credential privileges. Local Grok Build can produce reviewed versions and the campaign can select qualified versions through its normal release mechanism.

## 7. What counts as an opportunity

Use exact expected cash flows after known fees and modeled costs. Show expected return, downside and uncertainty separately. Gross price target minus fees alone is not enough if the probability of loss is ignored. A positive expected edge is conditional on its model; it is not measured profit.

Two economic evidence states are supported:

* `VALIDATED_RESEARCH`: defined out-of-sample evidence supports the strategy assumptions, with limitations.
* `EXPERIMENTAL_UNPROVEN`: Anthony has accepted a research campaign whose economic premise is unproven; known costs and mechanical correctness still apply, and all reports say experimental.

Do not require an endlessly deferred declaration of certain profitability before a disposable-capital experiment may begin. Do not allow the objective itself to replace a strategy or fee model. An experimental strategy must be a specified, replayable hypothesis with defined entry/exit behavior, not “buy anything until $200.”

## 8. Idle cash is a state to explain, not a mandatory violation

Define mutually reconcilable capital categories per venue: invested holdings; exchange/local reservations counted once; unsettled or non-reusable proceeds; broker/deposit holds; fee/exit reserves; dust/minimum-size remainder; and currently eligible free cash. Only that last category is available for the allocator.

For eligible free cash, report no qualifying signal, strategy declined, an intentional selected reserve, or an operational blocker. An operational blocker identifies owner, evidence, first_seen and next recovery action. The executor reevaluates on state changes; it never waits until the next day's briefing simply because the previous ticket expired.

Proposed service target: after a complete eligible signal arrives with funded resources and healthy state, the local decision/reservation path should meet its measured latency budget. After a material release of resources, the next allocation evaluation should be triggered immediately. Do not impose a minimum trade count, a mandatory end-of-week invested percentage, or a made-up missed-profit estimate to enforce “activity.”

## 9. Portfolio objective and venue independence

One parent campaign can hold two funded venue sleeves. Combined reporting does not imply transferable buying power. No automated cash bridge exists. Each sleeve has its own owned resources and its own market availability. Rebalancing between venues is a separate proposed funding action, not a send instruction.

The default optional target is a net-return multiple on cash-flow-adjusted campaign NAV. The $100-to-$200 fixture uses 2.0, but the real target remains selected in the prepared preview. Cash transfers and deposits cannot count toward target attainment. A closing equity venue supplies stale/closed marks, not a live liquidation value; prevent false global-target execution based on such marks. While one venue is unavailable, the other can continue inside its reserved resources unless a genuine parent stop applies.

A target exit is best effort under qualified venue mechanics. If the goal is reached only on paper and realizable exit proceeds are lower, say so. Default after a goal-triggered exit attempt is no new risk until outcome is resolved; no automatic “one more trade” to cover the shortfall.
