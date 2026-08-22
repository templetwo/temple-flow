# RISK CONSTITUTION — Temple Flow / Funds-beast

**Effective immediately.** Applies to all capital, all modes, all Bots.  
**Cannot be overridden by any agent.**

This document is the single source of truth for the Temple Flow research-capital experiment (Temple of Two / Spiral sustainability). Any Bot that proposes a violation is automatically out of scope.

---

## Capital & account

| Field | Value |
| --- | --- |
| Research allocation | **$1,000** |
| Purpose | Temple of Two / Spiral research funding experiment |
| Broker | Charles Schwab (live credentials held by human / secure store) |
| Success metric | Reliable process, zero unsupervised risk, full provenance — **not** “make money” |

---

## Hard rules (day-one, fixed)

| Rule | Limit |
| --- | --- |
| Max risk per trade | **2.5%** of current equity |
| Max position size | **18%** of current equity |
| Max daily loss | **4.5%** of equity → hard circuit breaker (all new risk halted until **human reset**) |
| Max drawdown from peak equity | **18%** → full system halt + mandatory human review |
| Maximum open positions | **4** |
| Volatility filter | Reduce size **50%** or skip when 14-period ATR **> 1.8×** 60-day average ATR |
| Stops | **Hard stop-loss mandatory** on every live position |
| Leverage | No leverage beyond cash-account limits under the above rules |
| Costs | Commission + estimated slippage **must** be included in every ticket R-multiple |

These replace all progressive capital tiers. Numbers may be tightened or loosened only by **explicit human edit of this document**, never by agent discretion.

---

## Ticket protocol (non-negotiable)

1. Every live order requires a unique ticket ID: `TF-YYYYMMDD-XX` (example: `TF-20260822-01`).
2. Human approval phrase must be **exact**: `approve TF-YYYYMMDD-XX`
3. Approval window: **30 minutes** from ticket presentation.
4. Execution Bot may only send the **exact** parameters on an approved ticket.
5. Anything other than the exact approve phrase is **ignored**.

### Lifecycle

1. Desk Lead opens ticket with unique ID + evidence packages.
2. Risk Manager sizes or vetoes and finalizes parameters (only Risk may propose live size).
3. Human replies with exact `approve TF-YYYYMMDD-XX`.
4. Execution sends exact order; returns fill/rejection + reconciliation.
5. Desk Lead closes ticket and logs outcome.

---

## Circuit breaker

If **daily loss ≥ 4.5%** or **overall drawdown from peak ≥ 18%**:

1. Immediately halt all new risk (no new tickets).
2. Notify Desk Lead and human.
3. Require explicit **human reset** before any new tickets can be opened.
4. Log the breach with full context (UTC, equity path, open book).

---

## Logging & research attribution

- Every signal, debate, sizing decision, approval, fill, and risk event is logged with **UTC timestamp** and **provenance**.
- Daily attribution must map P&L and risk events to the Temple of Two / Spiral research-funding goal.
- The experiment’s primary output is attributable process data, whether P&L is positive or negative.

---

## Role boundaries (summary)

| Role | May propose size | May send orders | May override this constitution |
| --- | --- | --- | --- |
| Desk Lead (Funds-beast) | No | No | No |
| Data & Backfill | No | No | No |
| Market Technical | No | No | No |
| Macro Sentiment | No | No | No |
| Strategist | No | No | No |
| Risk Manager | **Yes** (only) | No | No |
| Execution | No | **Only** on approved ticket ID | No |
| Research Digest | No | No | No |

**Human gate on capital:** every live order requires explicit ticket approval by ID. No unsupervised sends.
