# Temple Flow v2 — Campaign Operating Model

A build handoff for Anthony's local Grok Build terminal and Funds-beast team. One accepted campaign governs both Schwab and Kraken. Per-trade analysis, sizing, fees, reservation and execution move into the persistent runtime; people and models leave the critical path.

**Start:** `00_START_HERE_GROK.md` → `01_IMPLEMENTATION_PLAN.md`. **Rule audit:** `docs/CAP_AND_GATE_AUDIT.md`. **Core operating contract:** `docs/CAMPAIGN_OPERATING_MODEL.md`.

The package includes a proposed replacement constitution, broker capability requirements, migration/rollback instructions, ten updated role cards, closed versioned JSON schemas, unarmed examples, execution-ledger DDL, offline contract tests and the unchanged prior Kraken packet. The numerical limits in the old policy are not universal defaults in the full-loss research profile. Actual broker/funding constraints remain.

All new source paths and trading CLI interfaces described by the plan are work for the builder. This bundle is **not an installed trading engine, tested investment strategy, current account snapshot or live grant**. Its supplied executable code is offline verification only. No production file, repository, account, credential or order was changed by preparing it.

Run `python3 tools/verify_bundle.py` to check content integrity. Run `python3 -m unittest discover -s tests -v` to execute the supplied contract/arithmetic/DDL checks; the test dependency is in `requirements-dev.txt`. Read `VERIFICATION.md` for the exact scope of actual results. The long runtime acceptance plan contains requirements, not claimed passes.

`legacy/` contains original bytes. `docs/SUPERSESSION_AND_DECISIONS.md` controls how those older assumptions are superseded. Source review and unverified details are in `docs/SOURCES_AND_VERIFICATION.md`.
