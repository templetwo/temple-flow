# Temple Flow v2 — start here, Grok Build
## Campaign-operated trading desk · implementation handoff · 2026-09-20

**Owner:** Anthony Vasquez Sr. **Desk lead:** Funds-beast. **Implementation owner:** Anthony's local Grok Build terminal and Temple Flow team.

## Assignment

Restructure the ENTIRE Temple Flow workflow around durable campaign authorization. This is not a Kraken-only add-on and not a request to make a nine-agent approval meeting run faster. Build a desk that Anthony authorizes once, then operates Schwab and Kraken continuously when their markets and account permissions permit. Trade decisions, sizing, fee evaluation and execution must not wait for Anthony or an LLM conversation on each opportunity.

Anthony explicitly states that the existing money in his two research accounts is disposable loss capital. Preserve that intent. Do not silently reinstall the old 18% position ceiling, 35% ticket ceiling, four-position ceiling, 2.5% risk ceiling, 4.5% daily breaker, or 18% drawdown breaker as universal v2 policy. The full-loss research profile makes optional numeric loss stops explicitly disabled and bounds the experiment to its funded, snapshotted capital. It permits concentration; it does not command it.

**This package authorizes design/build work by its requested scope, not a live order, account conversion, transfer, credential change, daemon restart, or public push.** Implement locally on an isolated branch/worktree. Default examples are unarmed. Once deployment is mechanically qualified, produce one resolved campaign preview for Anthony's GO. Do not ask him to approve individual trades inside that campaign.

## Read in this order

1. `01_IMPLEMENTATION_PLAN.md` — work packages, dependencies, file mapping, first vertical slice.
2. `docs/CAMPAIGN_OPERATING_MODEL.md` and `docs/PROPOSED_CONSTITUTION_V2.md` — the replacement operating contract.
3. `docs/CAP_AND_GATE_AUDIT.md` — rule-by-rule dispositions, evidence and local audit still required.
4. `docs/EXECUTION_AND_ACCOUNTING.md`, `docs/ALLOCATOR_REFERENCE.md`, `docs/BROKER_CAPABILITIES.md`, `docs/MIGRATION_AND_ROLLBACK.md` — money, order ownership, venue differences and cutover.
5. `docs/ACCEPTANCE_PLAN.md`, `contracts/`, `examples/`, `bot_cards/`.

The v1 Kraken packet is preserved byte-for-byte under `legacy/`. **Read `docs/SUPERSESSION_AND_DECISIONS.md` before borrowing from it.** Its useful venue mechanics remain reference material; its old ceilings, CV-only scope, off-hours-only entry default and session-renewal model are superseded for the v2 build.

## First work session: do this, not more planning

Resolve the actual repository with `git rev-parse --show-toplevel`; inspect branch, dirty state and HEAD. This handoff inspected main at `a5aa41b337c5f7522770225fb9a74121a1150283`. If the local checkout is newer, produce a scoped delta and merge this design with it; do not reset or overwrite another seat's work. Do not read secret files into the model transcript.

Inventory all entry points, wrappers, standalone send scripts, launchers, schema validators and configuration overlays. Record what is effective versus merely present. Read the current operating/risk docs and amendments from disk. Source snippets in this packet are not a complete local audit.

Then build a paper-only campaign-to-fill slice using the existing pure strategy seam and a fake broker. A qualifying event must pass machine policy, atomically reserve capital, submit a paper intent, account for a fill, attach protection state and render the outcome **without a human ticket approval**. Demonstrate a fee-negative decline alongside it. Ship this slice before building a large UI or refactoring every historical script.

## Required end-of-session handoff

Return the actual commit and dirty state; implemented versus proposed paths; exact commands run; test counts tied to that commit; capability facts versus unknowns; open orders and live changes only if separately authorized; and the next buildable step. Do not equate a running process with a healthy feed or a passing simulator with profitable live trading.

## Package checks that exist now

From this extracted directory:

```sh
python3 tools/verify_bundle.py
python3 -m unittest discover -s tests -v
```

The contract tests require `jsonschema` (see `requirements-dev.txt`). They validate this handoff's sample contracts and arithmetic only. They do not test the Temple Flow runtime, broker APIs, current balances, strategy profitability or live execution. The new trading CLI described in the design is **to be implemented**, not supplied by this packet.

## Deliverable, not a permission maze

One authenticated GO accepts one prepared campaign revision, snapshot and policy digest. Existing code/writer ownership has a one-time migration. Broker capability evidence is reused until it expires or changes. Retries after ordinary data recovery are automatic. Neither midnight nor loss of a chat session ends the mandate. Genuine account/auth problems are surfaced once with the next action, not converted into repeated trade approvals.
