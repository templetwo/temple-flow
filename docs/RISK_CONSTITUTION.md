# RISK CONSTITUTION — Temple Flow / Funds-beast

**Effective immediately.** Applies to all capital, all modes, all Bots.  
**Cannot be overridden by any agent.**

This document is the single source of truth for the Temple Flow research-capital experiment (Temple of Two / Spiral sustainability). Any Bot that proposes a violation is automatically out of scope.

---

## Capital & account

| Field | Value |
| --- | --- |
| Research capital | **Live Schwab equity** (no fixed $1,000 placeholder) |
| Baseline snapshot | **2026-08-22 ~19:42 ET** — equity/liquidation **$95.63**; cash **$2.15**; long **NVO** 2 sh MTM **$93.48**; account …8585 MARGIN |
| Sizing basis | Risk Manager always sizes against **current live equity** from Schwab, not a stale target |
| Purpose | Temple of Two / Spiral research funding experiment |
| Broker | Charles Schwab (Studio **launchd** → `~/spiral-broker`; Grok Desktop is **off** the send path) |
| Success metric | **In the thesis with a hard stop on.** Ticket throughput is not the metric. Idle cash waiting for a card is a miss. Provenance and zero unsupervised size still bind. |

---

## Hard rules (day-one, fixed)

| Rule | Limit |
| --- | --- |
| Max risk per trade | **2.5%** of current equity |
| Max position size | **18%** of current equity (**except Micro Velocity lane** — see below) |
| Max daily loss | **4.5%** of equity → hard circuit breaker (all new risk halted until **human reset**) |
| Max drawdown from peak equity | **18%** → full system halt + mandatory human review |
| Maximum open positions | **4** |
| Volatility filter | Reduce size **50%** or skip when 14-period ATR **> 1.8×** 60-day average ATR |
| Stops | **Hard stop-loss mandatory** on every live position |
| Leverage | No leverage beyond cash-account limits under the above rules |
| Costs | Commission + estimated slippage **must** be included in every ticket R-multiple |

These replace all progressive capital tiers. Numbers may be tightened or loosened only by **explicit human edit of this document**, never by agent discretion.

---

## Micro Velocity lane amendment (human, 2026-08-22)

**Authority:** Explicit human edit by Anthony. Effective immediately.

| Field | Value |
| --- | --- |
| Lane | **Micro Velocity** agent only |
| Change | **Max position size (18%) does NOT apply** to tickets sized for this lane |
| Still bind | Max risk/trade **2.5%**; daily loss **4.5%**; peak drawdown **18%**; max opens **4**; ATR filter; hard stops; commission+slippage; **session arm** (see below) or per-ticket approve when disarmed |
| Who sizes | Risk Manager still finalizes live qty; Desk Lead does not size |
| Scope | Only ideas/tickets marked Micro Velocity. Desk / Strategist / other lanes keep the **18%** cap |
| Intent | Allow 1-share recovery vehicles (incl. IBIT/ETHA/FBTC when risk $ at stop clears 2.5%) on a micro book |

Residual legacy names (e.g. NVO overweight) are still managed toward risk hygiene; this amendment is not a blank check to ignore stops or circuit breakers.

---

## Ticket protocol (non-negotiable)

1. Every live order requires a unique ticket ID: `TF-YYYYMMDD-XX` (example: `TF-20260822-01`).
2. **Default (all non-MV lanes, and MV when disarmed):** human approval phrase must be **exact** `approve TF-YYYYMMDD-XX` within **30 minutes** of presentation.
3. Execution may only send the **exact** Risk-finalized parameters on an authorized ticket (per-ticket approve **or** active MV session arm).
4. Anything other than the exact authorize phrase is **ignored**.

### Lifecycle (default)

1. Desk Lead opens ticket with unique ID + evidence packages.
2. Risk Manager sizes or vetoes and finalizes parameters (only Risk may propose live size).
3. Human replies with exact `approve TF-YYYYMMDD-XX` **or** (MV lane only) session arm is already active.
4. Execution sends exact order; returns fill/rejection + reconciliation.
5. Desk Lead closes ticket and logs outcome.

---

## Micro Velocity session arm (human, 2026-08-24)

**Authority:** Explicit human choice by Anthony. Effective immediately.

| Field | Value |
| --- | --- |
| Purpose | Automate MV sends inside the risk box — human arms the session once, not every ticket |
| Arm phrase (exact) | `arm MV session` |
| Disarm phrase (exact) | `disarm MV session` |
| Where | Prefer **Execution** chat (same as live sends); Desk Lead will relay if said here |
| While armed | After Risk **PASS** on a ticket marked **Micro Velocity**, Execution **auto-sends** exact Risk params — **no** per-ticket `approve TF-…` |
| Still required | Risk PASS; 2.5% risk; circuit breakers; max 4 opens; hard stops; funding; exact ticket fields; full UTC logging |
| Does NOT cover | Non-MV lanes; funding/trim tickets not marked MV; any Risk VETO; size changes after Risk stamp |
| Auto-disarm | End of US RTH **16:00 America/New_York**; or daily-loss / peak-DD circuit breaker; or human `disarm MV session` |
| Re-arm | Requires a fresh exact `arm MV session` after disarm or auto-disarm |

**Intent:** automation with a kill switch — not unsupervised forever.

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
| Micro Velocity | No (ideas only) | No | No |

**Human gate on capital:** no unsupervised size. New risk needs `arm MV session` (or exact `approve TF-…` if disarmed) **and** standing rules the human wrote. Act is the Studio daemon, not Grok Desktop.

See `docs/AMENDMENTS_2026-08-28.md` (law) and `docs/OPERATING_MODEL.md`.

---

## Cut-down operating surface (human, 2026-08-28)

**Authority:** Explicit human **yes 1-5** by Anthony, 2026-08-28 ~11:52 ET. Full text: `docs/AMENDMENTS_2026-08-28.md`.

| # | Law |
| --- | --- |
| 1 | Two loops. Think = this chat / phone. Act = Studio launchd → `~/spiral-broker`. Grok Desktop is off the send path. |
| 2 | One phrase per day: `arm MV session`. Then leave. |
| 3 | Live entries: **ETHA** and **IBIT** only. NVO/NOK = protect, not strategy. No F, no AAL, no floor debate before a send. |
| 4 | One Schwab mutation: **GTC pullback + attached stop**. No DAY. No stop-after-fill second card. No replace up through the Risk cap. Through the cap = idea dead. |
| 5 | Success = in the thesis with a stop on. Not ticket theater. |

`--live` is a human act at the Studio after the bracket helper is real. Dry-run is the daemon default. Risk numbers above do not move.
