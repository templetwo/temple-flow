# Temple Flow — Shadow Path: TRIM 1 NVO → BUY 1 NOK

**Desk:** Funds-beast / Anthony  
**Mode:** SHADOW ONLY — no orders, no Execution, no approve phrase  
**Timestamp (ET):** 2026-08-22 20:20 ET  
**Context:** Anthony said "whatever you want" on NVO funding; Desk Lead chose **TRIM 1 NVO** then **BUY 1 NOK** as primary.  
**Frictions (assumed):** $0 commission; **$0.02 slip** on sell and on buy.

---

## Live book (pre)

| Field | Value |
|-------|-------|
| Equity | 95.63 |
| Cash | 2.15 |
| NVO | 2 sh / MV 93.48 (~46.74/sh) |
| Opens | 1 / 4 |
| Max position (18%) | 17.21 |
| Max risk (2.5%) | 2.39 |

---

## Sequence

### 1) Sell 1 NVO @ 46.74 → `TF-20260822-N1` · disposition **shadow_pass**

| Field | Pre | Post-trim |
|-------|-----|-----------|
| Cash | 2.15 | **48.89** (2.15 + 46.74) |
| NVO | 2 / MV 93.48 | **1 / MV 46.74** |
| Equity | 95.63 | ~95.63 (−0.02 sell slip → **~95.61**) |
| Opens | 1 / 4 | **1 / 4** |
| Remaining NVO % equity | ~97.75% | **~48.88%** (46.74 / 95.63) |

### 2) Buy 1 NOK @ 10.18 stop 9.45 target 11.00 → `TF-20260822-N2` · disposition **shadow_pass_funded**

| Field | Value |
|-------|-------|
| Notional | 10.18 |
| Dollar risk (entry − stop) | 0.73 |
| Cash after buy | **38.71** (48.89 − 10.18); w/ both slips → **~38.67** |
| Equity after both slips | **~95.59** (95.63 − 0.04) |
| NOK position | 1 sh / MV 10.18 |
| NVO remaining | 1 sh / MV 46.74 |
| Opens | **2 / 4** |

---

## Post-trim book

| Field | Value |
|-------|-------|
| Cash | 48.89 |
| Positions | NVO 1 @ ~46.74 (MV 46.74) |
| Equity | ~95.61 (after $0.02 sell slip) |
| Remaining NVO % equity | 48.88% |
| Open count | 1 / 4 |
| Disposition (sell) | **shadow_pass** |

---

## Post-buy book

| Field | Value |
|-------|-------|
| Cash | 38.71 (~38.67 w/ slips) |
| Positions | NVO 1 MV 46.74; NOK 1 MV 10.18 |
| Equity | ~95.59 (after $0.04 total slip) |
| NOK % equity | **10.65%** (10.18 / 95.63) |
| Remaining NVO % equity | **48.88%** (46.74 / 95.63) |
| Risk $ / % equity | **0.73 / 0.76%** |
| Open count | **2 / 4** |
| Disposition (buy) | **shadow_pass_funded** |

---

## Cap checks (NOK primary)

| Check | Limit | Actual | Result |
|-------|-------|--------|--------|
| Position (notional) | ≤ 17.21 (18%) | 10.18 (10.65%) | **PASS** |
| Risk | ≤ 2.39 (2.5%) | 0.73 (0.76%) | **PASS** |
| Opens | ≤ 4 | 2 | **PASS** |
| Funding (post-trim cash) | cash ≥ notional | 48.89 ≥ 10.18 | **PASS** |

**Note:** Remaining NVO (~48.88% equity) is still above the 18% max-position *new-entry* cap; it is a **legacy overweight** reduced by the trim, not a new open sized to cap. New risk only attaches to NOK.

---

## Alternates (also fund after trim)

Cash post-trim **48.89** clears all three ideas from the earlier shadow TEST RUN:

| Idea | Notional | Funds after trim? | Desk Lead |
|------|----------|-------------------|-----------|
| **NOK 1@10.18** | 10.18 | YES | **PRIMARY** |
| F 1@14.40 | 14.40 | YES | Alternate |
| AAL 1@13.75 | 13.75 | YES | Alternate |

---

## Recommended next human step

**Shadow complete — no orders sent.**

If going live later:

1. Approve **TF sell** (`TF-20260822-N1` — sell 1 NVO) **separately**, confirm fill / cash.
2. Then approve **TF buy** (`TF-20260822-N2` — buy 1 NOK @ 10.18 / stop 9.45 / target 11.00) **separately**.

Do **not** batch-approve sell+buy as one phrase. Do **not** execute from this shadow log.

---

## Explicit constraints

- **No Execution**
- **No approve phrase**
- Shadow path only

---

## Ticket stubs (shadow)

See `/workspace/temple-flow/logs/tickets/`:

- `TF-20260822-N1.json` — sell 1 NVO — `shadow_pass`
- `TF-20260822-N2.json` — buy 1 NOK — `shadow_pass_funded`
