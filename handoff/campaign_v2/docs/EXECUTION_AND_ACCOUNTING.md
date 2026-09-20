# Execution and accounting contract

## 1. Nonblocking runtime

One persistent process owns a bounded event bus, per-venue input adapters, strategy evaluators, a shared ledger writer and account-specific execution workers. Prioritize fills, protection incidents, revocations and reconciliation above new entry evaluation; data backfill and model calls run in separate tasks with bounded queues. Do not coalesce raw book deltas before applying them. Coalesce redundant *strategy evaluations* after valid market state is built.

No synchronous network/history/LLM call is required while holding the reservation lock. The evaluator uses validated, versioned snapshots. When required state is stale, asynchronously refresh and reconsider a fresh intent on recovery. If only one venue is untrustworthy, the other can operate inside prepartitioned cash/risk resources; a complete portfolio metric remains marked incomplete.

## 2. Broker protocol to implement

`VenueAdapter` exposes read capabilities and order operations, not unrestricted HTTP to agents:

```text
capabilities(account_alias) -> CapabilitySnapshot
snapshot(account_alias) -> AccountSnapshot
market_events(instruments) -> async iterator[MarketEvent]
account_events(account_alias) -> async iterator[AccountEvent]
submit(ExecutableIntent, writer_permit) -> Accepted | Rejected | Unknown
cancel(OwnedOrderRef, writer_permit) -> CancelResult
amend(OwnedOrderRef, QualifiedAmend, writer_permit) -> AmendResult
reconcile(ReconcileCursor) -> ReconciliationReport
```

An adapter never assumes a timeout means not accepted. It may use streaming or documented bounded polling as appropriate, without inventing a broker stream unavailable to the installed API. Capability snapshots distinguish documented, fixture-tested, account-verified and unavailable features. Each mutable operation checks venue/account ownership and the current grant generation at the final send boundary.

## 3. Durable state and identity

Use a local transactional ledger with migrations. Monetary and quantity values are canonical decimal strings in contracts and exact Decimal arithmetic in application code. SQL TEXT is not a numeric enforcement engine: application transactions must enforce monetary invariants and tests must exercise them. Do not use floating-point SQLite SUM for accounting.

Minimum entities: campaigns/revisions; grant/revocation records; allocation snapshots; source snapshots; order intents; cash/inventory/risk reservations; orders; fills; positions/lots; protection groups; fee snapshots; external flows; NAV series; financial latches; writer generations; audit events; and read-model checkpoints. `templates/runtime_ledger.sql` is a reference DDL starting point, not a certified production database.

Intent IDs are globally collision-resistant. One intent has one durable client identity; each exchange fill has a venue/account-scoped unique key. Store exchange time, receive time, processing time, source sequence where available, and monotonic durations for local latency. Retain raw response references without secrets.

Apply one fill exactly once to the ledger even when delivery is at least once. An event ID is not enough unless uniqueness is enforced in the same transaction as money movement. Outbox persistence and cash reservation must commit together. Exchange acceptance cannot be atomically committed with a local database transaction; model that uncertainty rather than promising network-wide exactly-once.

## 4. Spendability and inventory reservations

For each venue/currency:

```text
eligible_owned_cash = owned funded cash usable under account rules
                   - pending independent commitments not already deducted
                   - required entry/exit fees and operational cash holds
```

Do not subtract exchange holds twice when the reported available balance already excludes them. Reconcile owned ledger cash, broker cash, unsettled proceeds, broker holds and local reservations separately. Unknown funding semantics block new entries on that account. Existing positions are not cash, and cash at the other venue is not local collateral.

For each base asset/security, compute total owned inventory, exact owned portions adopted by each campaign, settled/exit-eligible units, and units committed to independent sell groups. A native mutually exclusive OCO group reserves the maximum possible executable leg; independent sells reserve their sum. Partial executions atomically reduce inventory and matching reservations. An add to a long does not automatically invalidate its existing protection; the adapter must qualify how protection extends to the new lot without overselling.

Full-loss campaigns may concentrate their eligible capital in one instrument, but the sizing algorithm still selects quantity based on its declared policy. The maximum possible cash debit at the accepted entry price plus fees must fit owned resources. Post-rounding checks include minimum entry AND exit quantity/cost, fee charged in base currency, and residual dust handling. A zero stop distance or missing fee is not free risk.

## 5. Normal order state machine

```text
PROPOSED -> DECLINED
         -> AUTHORIZED -> RESERVED -> SUBMITTING
                          -> ACCEPTED -> OPEN -> PARTIAL -> FILLED
                          -> REJECTED
                          -> SUBMISSION_UNKNOWN -> RECONCILING
OPEN/PARTIAL -> CANCEL_PENDING -> CANCELED / FILLED / PARTIAL
OPEN/PARTIAL -> AMEND_PENDING  -> accepted replacement / old order retained / UNKNOWN
```

A canceled entry can leave a real position. A partial fill can have multiple protection children. `REPLACED` may introduce a new broker order identity. Persist every relationship, and do not infer inventory state from a parent status.

On send failure after possible transmission, retain reservation, query order/fill history and bind recovered identities before another send. A client order ID is a reconciliation aid, not assumed perpetual idempotency support. If absence cannot be established, remain unknown and do not resend. Account snapshots and feed sequences are reconciled at reconnect and startup before entries resume.

## 6. Protection transitions and explicit flatten

Protection is a separate state linked to exact inventory: REQUIRED, PENDING_CONFIRMATION, CONFIRMED, TRANSITIONING, INCIDENT, RESIDUAL, FLAT. An entry requesting a conditional stop is not evidence its child exists. Use exchange confirmation and fill quantity to establish coverage.

A native atomic replacement is used only where certified for that order type and child relationship. Where the venue requires cancel-then-send, specify the finite transition: freeze related entries; cancel only owned conflicting exits; wait for acknowledged terminal state; reconcile races/fills; calculate remaining sellable quantity; submit the qualified immediate close or replacement; verify result. During the gap, display TRANSITIONING, never PROTECTED. If transport fails before cancellation is known, do not send a second sale. If cancellation is known and the new exit fails, enter INCIDENT and use the campaign's preauthorized emergency procedure. Do not claim a software timeout bounds market loss or guarantees the gap can be repaired.

STOP defaults to no new risk and continuation of protection. PAUSE is resumable under the accepted grant. FLATTEN is explicit, authorized and account/position-scoped; it never borrows or oversells and may remain EXIT_PENDING when the venue/session will not permit it. An unsupported exit mode is excluded from live strategy capabilities until resolved; it is not silently replaced with an unsafe alternative.

## 7. NAV, cash flows and target semantics

Record separate gross realized P&L, fees, realized net P&L, unrealized P&L, modeled liquidation costs, infrastructure costs attributable to the campaign, and residual inventory. “Net” in campaign reporting is after trading costs and separately identified operating costs, before personal taxes; tax consequences are not inferred here.

Baseline NAV is the marked value of adopted net funded resources at arming. Deposits/withdrawals are external flows. For display, `net_trading_pnl = NAV_now - NAV_start - net_external_contributions` over a stated window, with costs and valuations consistently accounted. For return and drawdown, use unitized NAV: when a flow occurs, create/redeem units at the pre-flow price. Preserve high water of unit price. Never reset peak to current equity on each read.

Default arming excludes future contributions; they are still recognized for account reconciliation, but not spent until accepted. An unexplained delta is not automatically a deposit or a gain. Negative cash/unknown debt is an incident and cannot be “fixed” by inventing a transfer.

For a target multiple, `unit_price / initial_unit_price >= multiple` is the reporting condition. If the selected target requires realizing proceeds, first use current liquidation estimates from both venues; stale equity marks cannot trigger a claimed completed combined goal. Trigger TARGET_EXITING, stop entries, handle outstanding orders, close under the approved exit protocol, then evaluate final net value. Return COMPLETED/TARGET_REACHED only after evidence; otherwise STOPPED/TARGET_EXIT_SHORTFALL or EXIT_PENDING. Do not restart to make a failed close “win.”

## 8. Revocation and restart races

GO installs a grant with a monotonic generation and digest. Each intent binds that generation, account snapshot version and policy version. Immediately before transmission, the single writer checks grant generation and stop state again. Revocation invalidates unsent intents; possibly-sent orders are reconciled and handled by their remaining risk.

Per-account local writer fencing prevents concurrent processes on the designated host. No automatic cross-host failover in this release: a local lease expiry cannot fence a still-live process elsewhere from a public broker API. Verify the previous host cannot send before moving credentials/writer ownership. Never claim a lock file alone prevents a stale remote writer.

Startup reconstructs allocations, open/pending orders, fills and protection before entries. Open-order pagination must include all relevant ages, not only a convenient recent time window. API token renewal belongs to the adapter, automatic only within the broker's supported authorization flow. A required human sign-in is reported once; the engine does not keep retrying destructive work or fabricate a successful refresh.

## 9. Resource costs and audit retention

Keep ticks in rotated captures and only needed decision references in the transactional database. Record dropped/gapped input explicitly; never delete required deltas silently. Audit retention has a declared storage policy, with live state and unresolved incidents protected from purge. Disk-full tests must demonstrate that entries stop before unjournaled orders can be sent.

Model calls run under a separately explicit operating-cost budget. A $100 trading allocation does not authorize unlimited API spend on a credit card. Existing subscriptions and infrastructure expenses are shown distinctly, not hidden in a positive trading P&L. Losing cloud-model access must not remove native protection or make the existing deterministic policy forget its mandate.
