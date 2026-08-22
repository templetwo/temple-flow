# Skill: Full Historical Backfill

**When to use:** First run and any time the data store is incomplete or corrupted.

**Required:** Access to price/macro/news sources used by goldbrick and spiral-broker (or approved substitutes).

## Sequence
1. Pull multi-year daily (and intraday if available) data for the chosen universe.
2. Clean, align timestamps (America/New_York), handle missing bars.
3. Recompute all technical indicators and regime labels offline.
4. Store with full provenance in the local database.
5. Validate completeness and report any gaps.

## Output
Confirmation of date range, row counts, and any anomalies.

## Never-do
Do not invent data. Do not skip validation.
