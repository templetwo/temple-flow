# Shadow / Paper Mode Runbook

**Goal:** Exercise the full desk sequence with **zero capital at risk** until Anthony explicitly opens live.

## Modes

| Mode | Data | Tickets | Execution |
| --- | --- | --- | --- |
| `shadow` | Historical + delayed/public feeds OK | Sized tickets logged, never sent | Execution is no-op; simulate fill optional |
| `paper` | Same as shadow; may use broker paper if available later | Same | Paper account only |
| `live` | Live book + Schwab | Requires exact `approve TF-YYYYMMDD-XX` | Real sends |

Default until further notice: **`shadow`**.

## Daily shadow loop (Desk Lead)

1. Confirm Risk Constitution unchanged (`docs/RISK_CONSTITUTION.md`).
2. Ask Data & Backfill for refresh status / gap report.
3. Pull Technical + Macro packages (evidence only).
4. Strategist produces ideas with hard stops (no size).
5. Risk Manager sizes or vetoes → writes ticket JSON under `logs/tickets/` with `mode: shadow`.
6. Desk Lead posts brief to Temple Flow Desk. **Do not ask for live approve in shadow unless deliberately dry-running the approve phrase.**
7. Optional: simulate fill for attribution practice; mark `execution` as simulated in notes.
8. Research Digest attributes shadow P&L separately from live capital.

## Hard rules still apply in shadow

- Same % limits against the **$1,000 research allocation** (or stated shadow equity).
- Circuit breakers still halt **new shadow risk** for process discipline.
- Never invent bars, indicators, equity, or fills.

## Exit criteria to leave shadow

- Historical backfill validated (date range + gap report OK)
- ≥ several shadow sessions with complete ticket lifecycle logs
- Schwab path wired (read first, then least-privilege trade)
- Anthony explicitly says open live under ticket approval
