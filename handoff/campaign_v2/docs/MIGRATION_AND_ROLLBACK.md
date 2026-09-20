# Migration and rollback — one live owner at a time

## 1. Scope and safe workspace

Implement in a branch/worktree isolated from the current execution root. Do not start by editing `config/LIVE_OK`, credentials, launchd or the active outbox. Before running old tests, confirm they are isolated from the real stores and cannot import a live send path. A dirty working tree belongs to its current worker; preserve it rather than resetting for convenience.

Record the current local commit, package/interpreter, environment variable names (not values), launch targets, config precedence, command wrappers and order-sending entry points. The checked-in launcher is not proof of the currently installed job. The repository inspection in this handoff did not inspect the Studio runtime.

## 2. Strangler migration

Phase A adds v2 contracts, a paper broker and the ledger beside the existing system. Phase B extracts pure normalization, sizing and formatting functions with characterization tests. Phase C implements native adapters that preserve actual broker semantics while enforcing the v2 campaign contract. Phase D selects one live writer at a controlled cutover.

Do not run every v2 decision through the old hard caps and bypass failures; that preserves hidden policy and makes outcomes irreproducible. Do not rewrite the whole wire before producing the paper vertical slice. Maintain a legacy execution mode only for already-authorized legacy work under its original rules until adopted or retired.

## 3. Deployment preview and authorization

The builder provides one deployment packet containing code/test receipts, a capability map, exact old/new writer identities, inventory adoption plan, unresolved restrictions, current allocation snapshot and the selected campaign policy. Anthony's acceptance of deployment/campaign GO is separate from requesting this build bundle. It does not have to become a sequence of per-trade permission requests.

Before GO, all template placeholders must be resolved automatically where a read can answer them. Read-only account preparation does not place trades. A missing login or unresolved outside scope is surfaced as one necessary issue, not dozens of disabled order cards. Goal choice and genuine risk-policy choices appear together in the same preview.

## 4. Controlled cutover sequence

1. In the authorized maintenance window, stop legacy **new entries**. Preserve required protection and its observed status. Snapshot queue IDs, broker IDs, working parent/child relationships, positions, cash/holds, ledger cursor and grant state.
2. Disable all old mutation entry points, including scheduled `--once` processes and standalone send scripts, with evidence that no old writer remains active. A filename rename alone is not sufficient fencing.
3. Classify each legacy item: already submitted and owned; unresolved submission; pending approved but unsent; expired; unsupported/manual. Do not automatically replay or reauthorize old pending tickets. Preserve their records and explicitly supersede/reissue qualifying opportunities under v2.
4. Import observed inventory/order identities and historical costs where known. Unknown cost basis is UNKNOWN, not zero. Allocate account resources exactly once. No cancellation sweep is part of import.
5. Start v2 in observe/reconcile mode using the prepared writer ownership, compare with fresh broker state, verify protective coverage and resource totals, then accept GO for the resolved campaign revision.
6. Observe the first actual intent/ack/fill and receipts under the separately authorized campaign. Any discrepancy returns entries to reconciliation. Do not label a submit acknowledgement a completed trade.

A failure before old writer shutdown leaves the existing system unchanged. A failure after shutdown leaves a documented protection-only/observe state until ownership is resolved, not two engines racing to restore service.

## 5. Rollback rules

Pause v2 entries, reconcile all possibly transmitted intents, and preserve protective orders. Record a current exchange-state snapshot. Stop/fence the v2 writer before considering the legacy one. The old code may not understand adopted quantities, new symbols, crypto or v2 protection groups; rollback may therefore be **read-only/protection supervision**, not restart-the-old-trader.

Never restore an old SQLite file, cash balance or outbox as though live orders and fills after the snapshot did not happen. Keep append-only execution facts and use forward corrective migrations. Reverse a schema only when no newer facts would be lost and the procedure is tested. Rollback of code is not rollback of the market.

If v2 created no live orders, normal code/config rollback is simpler but must still establish writer ownership. If it did, only a ledger/order-aware compatibility path may assume control. Kraken has no legacy equivalent in this project; its safe fallback is truthful stopped entries plus existing native protection and documented human/qualified close handling.

## 6. Recovery and operational handoff

Simulate power loss, disk-full, expired API access, missed fills, duplicate execution messages, quote corruption, exchange maintenance, daylight-saving transitions and a model outage. After restart, reconstruct state before allowing entries. Every alert carries campaign/venue, known state, uncertain state and next action.

Final deliverable: `DEPLOYMENT_RECEIPT.json`, actual commit, capability evidence, adopted inventory/working-order references, active grant digest, operator controls and any unresolved exposure. Keep sensitive account/credential material outside the public repo and outside the Stack record; only non-sensitive summaries are appropriate for general handoffs.
