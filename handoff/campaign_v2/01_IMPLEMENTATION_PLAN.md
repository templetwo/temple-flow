# Temple Flow v2 — implementation plan
## From ticket-led workflow to campaign-operated desk

**Version:** 2.0 design handoff, September 20, 2026. **Status:** BUILD SPECIFICATION; no production changes or orders performed. **Repository reviewed:** main `a5aa41b337c5f7522770225fb9a74121a1150283`. Source keys resolve in `docs/SOURCES_AND_VERIFICATION.md`.

## 1. Product outcome

Anthony should be able to prepare a campaign, inspect one concise preview, and say GO. Funds-beast then operates both the equity and crypto lanes: it deploys eligible available capital into qualified opportunities, manages positions, recycles released capital, selects registered strategies and reports actual outcomes. Anthony is not a per-trade approver. Grok agents are not a serial synchronous voting mechanism in the order path.

The campaign survives a phone going offline, model outages, equity-market close and process restarts. Its executor is event-driven, not a new process every fifteen minutes. It stops new entries on revoked authority, exhausted/tradably insufficient capital, an optional selected loss boundary, terminal objective handling, or an execution fault whose truth cannot yet be established. Temporary data faults recover automatically after reconciliation under the same mandate.

**More trades are not evidence of better performance.** The engineering outcome is removal of avoidable delay and stranded *eligible* capital. The financial outcome remains an experiment; positive net returns and doubling are not established by this design.

## 2. What Anthony has decided, and what is still a runtime fact

The latest direction applies the campaign model to Funds-beast and the whole project, including Schwab and Kraken. Existing funds in both accounts are described by Anthony as capital he can accept losing. The reported $432 Schwab cash is a user statement, not a verified current balance. The earlier $100-to-$200 example is an illustrative goal, not the actual Kraken balance or a finalized combined objective.

A Finances account read in this work returned no linked accounts. Consequently no current equity, settled cash, account type, Kraken fee tier, open order or holding was verified here. The local adapters must resolve those facts during preparation. Do not hard-code $432, $100, $597, a historical account identifier, or a combined account total.

The build includes a full-loss research profile for this stated posture. It does not permit borrowing, account overdrafts, unrelated assets, automatic deposits, transfers, options, futures or short positions. Those are different capabilities and are not implied by willingness to lose the current funded capital.

## 3. Verified reasons to change the implementation

The repository already separates Think and Act and delegates Risk-PASS approvals to Funds-beast; retain those advances. September 15 removes the name-count ceiling, while the example, schema and source still contain count-cap behavior. The checked-in launchd file starts `--once` every 900 seconds. The wire's first 250 lines also document synchronous re-evaluation reads, manual promotion of plan files, a fixed live universe, rejection of adds to existing longs, and day/session-oriented approval lifetimes. [R1–R8, R10]

These facts support the redesign but do **not** prove why all of the reported cash remained idle. The wire's own discussion notes that its default four-name check often cannot be reached as a blocker with the two-name entry universe and earlier no-add checks. Runtime evidence is required before assigning historical missed profit to a particular cap. Price movement after the fact is not a fill the system necessarily could have obtained.

The bracket runbook documents that helper calls outside the planner/gate can bypass the one-sell enforcement. V2 must put order ownership and authority checks at the real send boundary, not merely improve chat instructions. [R9]

## 4. Implementation shape: small persistent core, two venue adapters

Start with a single persistent asynchronous Python service on the designated execution host, a local transactional ledger and one credential-owning writer per venue account. Use the project's existing dependency workflow; add a reproducible package/lock setup if none exists. Do not introduce Kafka, Kubernetes, active-active execution or a rewrite in a new language before profiling.

Proposed repository layout:

```text
src/temple_flow/
  campaign/       contracts.py, lifecycle.py, authority.py, policy.py
  allocation/     allocator.py, sizing.py, cash.py, exposure.py
  execution/      intents.py, writer.py, reconcile.py, protection.py
  ledger/         store.py, migrations/, nav.py, events.py
  market/         feed.py, instruments.py, calendar.py, features.py
  strategies/     registry.py, equity_pullback.py, crypto_momentum.py
  adapters/       protocol.py, paper.py, schwab.py, kraken.py
  control/        api.py, principals.py, receipts.py
  reporting/      desk.py, cash_diagnostics.py, attribution.py
scripts/temple_flow_desk.py
schemas/campaign.v2.schema.json
schemas/order_intent.v2.schema.json
schemas/decision.v2.schema.json
config/campaigns/                     # private, ignored live state
config/profiles/                     # versioned non-secret policy templates
runbooks/CAMPAIGN_OPERATIONS.md
```

These are proposed paths. Keep the existing `scripts/temple_flow_strategy.py` compatibility entry point until its callers are migrated. Extract shared pure mechanics from `temple_flow_wire.py` under characterization tests; do not call its old approval/risk pipeline and then simply bypass whatever refuses the new intent. Treat old execution and new execution as distinct owners during migration.

## 5. Work packages and completion criteria

### WP0 — local truth, cap inventory, baseline characterization

**Owner:** Grok Build integration lead. **Depends on:** none.

Inventory tracked files plus the actual launch target and non-secret effective configuration on the designated host. Resolve overlapping scripts and daemon ownership without starting or stopping anything. Produce a cap inventory with policy ID, code location, current effective source, financial/process/technical classification, proposed disposition, regression test and migration owner. Extend the supplied cap audit instead of treating it as exhaustive.

Capture a clean checkout baseline for pure unit tests in a disposable state directory with broker network access disabled. Inventory environment variables, account aliases, startup flags and legacy queues without copying credentials or personal account dumps into the public repo. Identify old order-retrieval lookback limits; all still-working orders must be discoverable, even if created before the historical ten-day window mentioned in the runbook. [R9]

**Done:** baseline SHA + characterization receipts + complete local policy-input inventory. A failure to inspect a production host is an explicit deployment unknown, not a reason to postpone the paper build.

### WP1 — campaign contracts, compiler and command surface

**Owner:** core builder. **Depends on:** WP0's source interfaces.

Implement draft/prepare/GO/pause/resume/stop/flatten/status contracts. A prepared campaign resolves accounts, allocation ownership, adopted positions, strategy versions, numeric parameter ranges, schedules and goal. Its immutable digest binds the GO. Changes outside the accepted envelope need a new campaign revision; ordinary parameter choice inside it does not.

Implement `full_loss_research` and `bounded_loss` profiles. In the former, loss-per-day, percentage drawdown and arbitrary position/ticket/count caps are explicitly disabled rather than omitted. In the latter they are explicit parameters. Both enforce funded ownership, order correctness, eligible markets, current data and actual venue rules. No fallback from a missing field to a more permissive or legacy policy is allowed.

**Done:** invalid manifests, forged approval fields, stale previews, contradictory profiles and hidden legacy overlays fail with named reasons. One valid paper GO creates exactly one grant. Repeating GO is idempotent, not another allocation.

### WP2 — paper vertical slice, event bus and ledger

**Owner:** execution/core builder. **Depends on:** WP1.

Build the first full path using a deterministic fake venue. Inputs include market state, strategy snapshot, policy hash, fee model and account snapshot. One machine evaluation produces a decision; one transaction reserves money and persists an order intent; a single writer processes it; fills update lots, orders, cash and protection; reporting reads the same events.

Provide a scripted demonstration with a $100 fixture and a $200 objective, a qualifying signal, a fee-rejected signal, a partial fill, a repeated fill event, an unknown submission and recovery. Values are synthetic and visibly labeled. No actual Kraken or Schwab credentials are present.

**Done:** the trade completes without a chat call or per-ticket approval; duplicate delivery changes no money; restart reconstructs the identical ledger. Existing pure equity strategy tests remain readable.

### WP3 — source-agnostic allocation and asynchronous team operation

**Owner:** Funds-beast policy builder + Risk implementation owner. **Depends on:** WP2.

Implement one allocator per funded venue sleeve with a common portfolio view. Candidate evaluation does not block on another venue. Reserve cash against worst permitted fill plus costs; aggregate per-symbol positions and outstanding orders; choose eligible candidates by versioned after-cost policy. New money released by a fill/cancel/settlement event triggers reallocation without waiting for the next morning brief.

Turn the desk agents into asynchronous contributors. Data, Technical and Macro publish versioned evidence packages; Strategist/MV/CV publish strategy configurations and opportunity policies; Funds-beast selects; Risk owns deterministic sizing; Execution owns sends; Digest reports. The last valid strategy continues while chat is offline until its own validity rule expires. Position protection does not expire with research packages.

**Done:** concurrent candidates cannot spend the same dollar; a stalled Macro call cannot stall a valid order or protective action; every uninvested eligible dollar has an attributable reason category, not an invented profit claim.

### WP4A — Schwab adapter and equity workflow replacement

**Owner:** Schwab integration builder. **Depends on:** WP2 and local capability survey.

Wrap the existing credential/token path without moving secrets or treating its documentation as fresh live proof. Normalize book, working orders, settled/unsettled resources, permissions, order statuses and snapshots. Preserve exchange-held protection during every transition. Replace symbol-wide no-add rules with quantity-aware owned-lot accounting. Support scale-in, trim and rebalance only for native order combinations whose mechanics are qualified.

The equity executor is always running, but only submits in eligible sessions and supported order modes. Learn the actual account's intraday and settlement constraints; do not hard-code the pre-2026 PDT restriction. Do not turn on borrowing or convert the account to make a test pass. A marketable limit is permitted only when its exact strategy and price envelope support it, not as an automatic response to a resting order's failure.

**Done:** realistic replay goes GO → equity decision → paper bracket → fill/recycle without manual approvals or arbitrary name-count refusal; account-specific restrictions are explicit. Any private API capability remains NOT VERIFIED until tested with permission.

### WP4B — Kraken adapter and Crypto Velocity

**Owner:** crypto integration builder. **Depends on:** WP2.

Implement native market/account streams, fee and instrument metadata, book validation, cost-aware requests, conditional child mapping, partial-fill accounting and identity reconciliation. Use the technical parts of the archived Kraken v1 spec with the v2 supersession map. Crypto entries are eligible 24/7 subject to venue/account state, not merely outside equity hours.

Keep public ingestion, account recovery and private order writes separate. Reserve order-rate capacity for exits. Honor request/price validity and self-trade prevention. Do not interpret Kraken beta as a paper environment. Do not rely on global cancel-all behavior to flatten or preserve stops.

**Done:** the native adapter's paper/capture path spans a weekend/close boundary; private mechanics have explicit capability statuses; every child/quantity race in the acceptance plan is tested before its live feature is armed.

### WP5 — position lifecycle, portfolio goals and cash observability

**Owner:** execution + reporting builder. **Depends on:** WP3 and applicable adapter.

Implement campaign cash-flow-adjusted NAV, realized/unrealized P&L, fee/impact diagnostics, prospective liquidation costs and goal handling. A goal crossing first moves to `TARGET_EXITING`; it is not booked profit. Stop new entries, reconcile existing orders and perform the authorized close policy. Report achieved only after inventory and orders resolve and realized net value meets the goal; otherwise report `TARGET_EXIT_SHORTFALL` without automatically re-entering.

Implement `cash-diagnostics`: deployed, reserved, unsettled, held, minimum-size residue, eligible/no-edge, and operationally stranded cash. Record what prevented an eligible order and its timestamps. Support counters with zero denominators shown as N/A. Show observed missed signals separately from modeled missed P&L.

**Done:** no source-free green status, no deposits counted as gain, no unsettled proceeds counted as repeatedly reusable capital, no closed equity quote presented as live portfolio profit.

### WP6 — fault tests, replay and evidence-qualified deployment

**Owner:** second reviewer + build lead. **Depends on:** WP1–WP5.

Run the acceptance cases and positive controls in a clean checkout with external sends denied. Profile end-to-end local decision and durable reservation latency. Proposed initial target for a fixed two-venue replay: p95 <=100 ms, p99 <=250 ms from complete validated event to durable decision; record host, workload and sample size. Network/broker acknowledgement latency is a separate measurement. These are targets, not existing measurements.

Use source capture and stochastic fill assumptions, not midprice-only paper fills. A mechanical release can be qualified while statistical profitability is unproven; label the latter as an explicitly selected research campaign. Do not make vague demands for months of paper profit an unbounded deployment queue. Conversely, passing tests does not establish an economic edge.

**Done:** test receipts tied to the exact commit; strategy evidence explicitly labeled; no live mode unlocked by merely editing `mode` or a boolean approval field.

### WP7 — one-time controlled cutover and first GO

**Owner:** Grok Build on the authorized host, with Anthony's deployment decision. **Depends on:** WP6 and qualified capabilities.

Follow the migration runbook. Freeze legacy entries, inventory pending tickets and protective orders, establish that old senders cannot run, transfer ownership to v2, reconcile again, and prepare a manifest. Do not cancel all orders, rewrite balances, replay old outboxes, or leave two daemons live.

Produce one concise preview: two resolved account aliases, total and venue-local allocation, holdings adopted, liabilities/holds excluded, chosen goal, loss posture, markets, strategies, fees as of, and residual capability limits. GO is the authorization for this revision and normal in-envelope sends; subsequent trades do not need another approval.

**Done:** actual ownership and grant receipts exist; eligible orders can operate without the phone; STOP prevents new sends; observed state and remaining exposure are truthful. The build terminal must not treat this handoff itself as that GO.

## 6. Parallel work without duplicate architecture

Freeze the normalized broker protocol, campaign contract and ledger identity rules first. Then WP4A and WP4B can proceed in parallel while another worker builds WP3/reporting. One integration owner resolves schema changes; every worker uses isolated state and fake credentials. An execution reviewer should challenge a builder's assumptions about order states and protection rather than merely rerun that builder's happy-path tests.

The trading team remains Funds-beast's team. The general HQ/Sovereign Stack infrastructure is not recruited to operate the brokerage by this plan. The requested Grok Build seat is the implementation entry point; no extra agent or plugin is needed to make the handoff actionable.

## 7. Definition of delivery

Delivery is a working paper campaign, a qualified adapter capability map, a migratable ledger, measured latency and fault behavior, updated bot roles, explicit policy replacement, and a single actionable deployment/GO preview. A folder full of revised prose alone is not the implementation. A single live fill alone is not proof of sustained operation. A daily profit number alone is not proof of attribution or execution quality.

## Reference sizing policy

`docs/ALLOCATOR_REFERENCE.md` specifies `funded_weighted_v1`: an exact, deterministic resource allocator to implement before campaign preparation. It permits full funded allocation without inheriting 18%/35% caps, and separates sizing mechanics from evidence of strategy profitability. Include its actual registry version in the one-time preview.
