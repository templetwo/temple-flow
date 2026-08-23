# Temple Flow — Shadow TEST RUN

**Desk:** Funds-beast / Anthony  
**Mode:** SHADOW ONLY — no orders, no Execution, no approve phrase  
**Timestamp (ET):** 2026-08-22 20:18 ET  
**Opens:** 1 of 4

---

## Live book

| Field | Value |
|-------|-------|
| Equity | 95.63 |
| Cash | 2.15 |
| NVO | 2 sh / MV 93.48 |
| Opens | 1 / 4 |
| Max position (18%) | 17.21 |
| Max risk (2.5%) | 2.39 |

---

## Ideas (entry = mid of zone; shares = 1 each)

| # | Symbol | Side | Shares | Entry (mid) | Stop | Target |
|---|--------|------|--------|-------------|------|--------|
| 1 | F | long | 1 | 14.40 | 13.50 | 15.40 |
| 2 | NOK | long | 1 | 10.18 | 9.45 | 11.00 |
| 3 | AAL | long | 1 | 13.75 | 12.95 | 14.80 |

---

## Per-idea math

| Idea | Notional | % equity | $ risk (entry−stop)×sh | % risk equity | Position-cap (≤17.21) | Risk-cap (≤2.39) | Funding (cash≥notional) | Disposition |
|------|----------|----------|------------------------|---------------|------------------------|------------------|-------------------------|-------------|
| F 1@14.40 | 14.40 | 15.06% | 0.90 | 0.94% | PASS | PASS | FAIL (2.15 < 14.40) | PASS_UNFUNDED |
| NOK 1@10.18 | 10.18 | 10.65% | 0.73 | 0.76% | PASS | PASS | FAIL (2.15 < 10.18) | PASS_UNFUNDED |
| AAL 1@13.75 | 13.75 | 14.38% | 0.80 | 0.84% | PASS | PASS | FAIL (2.15 < 13.75) | PASS_UNFUNDED |

**Notes**
- Position-cap: notional ≤ max position 17.21  
- Risk-cap: dollar risk ≤ max risk 2.39  
- Funding: cash 2.15 must cover full notional (no margin assumed in this shadow)  
- Combined: equity-math PASS on all three; funding FAIL on all three → **PASS_UNFUNDED** (not VETO_POSITION / VETO_RISK)

---

## Recommended desk outcome

- **All three** clear position-cap and risk-cap; **none** clear funding (cash 2.15).
- **Cheapest notional:** NOK @ 10.18 (still short ~8.03 vs cash).
- **Next:** AAL 13.75, F 14.40.
- Shadow ticket stubs drafted as `shadow_pass_unfunded` for all three (equity-math pass, cash veto). No live ticket, no order, no Execution.
- Desk Lead: hold until cash ≥ cheapest candidate (NOK 10.18) or raise cash / reduce other exposure; do not approve or execute.

---

## Explicit constraints

- **No Execution**
- **No approve phrase**
- Shadow / test run only

---

## Ticket stubs (shadow)

See `/workspace/temple-flow/logs/tickets/`:

- `TF-20260822-M1.json` — F — `shadow_pass_unfunded`
- `TF-20260822-M2.json` — NOK — `shadow_pass_unfunded`
- `TF-20260822-M3.json` — AAL — `shadow_pass_unfunded`
