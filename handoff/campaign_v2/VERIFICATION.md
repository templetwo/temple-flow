# Verification report — packet v2

Executed 2026-09-20T17:45:37.527377+00:00 in the artifact-building Linux container using Python 3.13.5, jsonschema 4.26.0, and in-memory SQLite 3.46.1. This is **offline package validation**, not testing of the Temple Flow repository, a broker API, a trading strategy or the installed daemon.

## Executed

`python3 -m unittest discover -s tests -v`: **50 tests passed, 0 failures, 0 errors**. The suite checks JSON shape/semantics, unarmed fixtures, explicit loss-check disablement, selected boundary validation, exact illustrative fee/funding arithmetic, and reference SQL DDL constraints/transaction behavior. Complete named output: `evidence/offline_tests.txt`.

`python3 tools/contract_checks.py`: **five example contracts validated**. No grant was issued and no network call was made. Output: `evidence/example_validation.txt`. A shape-valid manifest and a string labelled grant ID are not authenticated execution authority.

The original ZIP passed its archive CRC check. Its two Markdown members matched the separately supplied original Markdown files byte-for-byte. Original ZIP SHA-256: `877cd9a48852eb46919eb6aa3d7fec05fb9abce8d45831b81d276480a72d6b02`. Its extracted members are preserved under `legacy/kraken_v1/`.

## Packaging checks

`tools/verify_bundle.py` verifies SHA-256 and byte lengths for the files enumerated in `MANIFEST.json`, and compares preserved original archive members. The manifest intentionally does not hash itself. It ignores Python bytecode caches created by test imports. Archive extraction and repeat tests are run on a fresh temporary copy during final packaging; the result is recorded below after execution.

## Not executed

The **60 runtime acceptance scenarios** in `docs/ACCEPTANCE_PLAN.md` are future implementation requirements, not 60 passes. No production campaign compiler, authenticated grant issuer, account reader, event-driven trading executor, model integration, backtest, real fill simulation, funded order or current account reconciliation was executed here. No probability of profit or target attainment is established.

The cap inventory has **40 reviewed rule/gate rows**, based on pinned documents and selected source reads; it is not a complete installed-configuration audit. Grok's WP0 must complete that local inventory. Performance budgets are design targets. The prior Kraken spec's technical statements are preserved as historical source material, with v2 precedence documented.

## Fresh-extraction and detector result

The generated ZIP passed its CRC check, was extracted into a separate directory, and the package verifier passed there. All **50 offline tests passed again** in that extracted copy. A deliberate change to README.md produced a nonzero verifier exit with a content-mismatch diagnostic; restoring the original bytes restored a pass. This positive/negative control demonstrates the supplied content-integrity detector, not financial correctness.

The final package was regenerated after this report was added and checked again. No live artifacts or repository files were modified.
