# Amendments 2026-09-15 — velocity with a free slot

**Authority:** Explicit human yes by Anthony, 2026-09-15 (~06:27 ET): “Yes, AMENDMENTS_2026-09-15 is law”.  
**Status:** LAW.  
**Does not move:** 2.5% risk/trade · 4.5% daily breaker · 18% peak drawdown · hard stops · no unsupervised size · size from live Schwab equity · one-sell law · exact `approve TF-…` · RTH cancel of PENDING_ACTIVATION.

Problem this fixes: book sat **4/4** with **~$433 cash (~70%+ of equity)** idle for days while DayPL printed ~$0–$2. Process protected stops and stranded capital. Success was redefined as “in thesis with a stop on” without a cash-deployment SLA.

---

## 1. Soft max opens = 3 (hard cap still 4)

Hard constitution max **4** stays. Operating target is **≤3** opens so **one slot + cash** stay free for ETHA/IBIT velocity.

Hitting 4 is an exception (gap fill, stop-replace mid-flight), not the steady state. If opens = 4 and cash > 15% of equity for >1 RTH session → Desk Lead must ticket a leftover recycle by next morning brief.

## 2. Leftover recycle SLA

NVO/NOK are protect leftovers, not strategy. Recycle (cancel-then-OCO under one-sell) when **any**:
- unrealized gain ≥ **8%** from avg, or
- age on book ≥ **10 calendar days**, or
- cash/equity ≥ **25%** and opens = 4

Morning brief carries exact `approve TF-…` **before 09:30**, never as an after-close ask for an RTH-only cancel.

## 3. Morning approve window (RTH tickets)

| Clock ET | Who | What |
| --- | --- | --- |
| 07:15 | Risk | restamp PASS/VETO/resize off live equity |
| 07:30–07:45 | Desk Lead | morning brief + **exact approve phrases** |
| before 09:30 | Anthony | exact `approve TF-…` |
| 09:35 | Execution | RTH mutate |

Evening approves for RTH-only cancels are accepted as **queue for next RTH**, not same-day sends (already proven 2026-09-14).

## 4. Refill failover (no multi-day cash sit)

After a recycle frees a slot: Risk sizes primary ETHA/IBIT GTC+stop.  
If at restamp **last ≥ Risk cap** → do **not** leave a zombie through-cap GTC as the only plan for >1 session. Same morning Risk must either:
- deepen the pullback limit inside the thesis, or
- VETO and size the other live name, or
- present `arm MV session` with a marketable-inside-cap MV ticket

Idle cash >25% equity with a free slot for **two consecutive morning briefs** without a live working buy = process defect.

## 5. MV is the cash engine when a slot is free

When opens ≤3 and cash >20% equity on an RTH morning (and no FOMC/CPI hard-hold flag from Desk Lead): morning brief **offers** exact `arm MV session` plus Risk-PASS ETHA/IBIT tickets. Default bias = arm and deploy under Risk, not sit.

FOMC/CPI days may still be protect-first — Desk Lead names that flag explicitly in the brief.

## 6. Success metric (add, do not replace)

Keep: in thesis with a stop on.  
Add: **cash/equity ≤ 25%** by end of any full RTH week unless Desk Lead logged a hard-hold flag (FOMC/CPI/breaker).

---

## Immediate next (does not wait on this file)

Already approved: Tue RTH `TF-20260914-01` NVO recycle → contingent `TF-20260914-02` IBIT under 43.50.  
If IBIT still through cap after NVO flat → Risk failover same day (amendment §4), not another quiet week.

---

## 7. Desk-approve standing delegation (2026-09-15)

**Authority:** Anthony exact phrase `desk may approve Risk-PASS tickets` (2026-09-15 ~06:33 ET).  
**Status:** LAW until revoke phrase `desk may not approve`.

Funds-beast (Desk Lead) may issue exact `approve TF-YYYYMMDD-XX` to Execution for tickets Risk has marked **PASS**.

Still human-only (Anthony):
- Risk **VETO**
- Through Risk-cap chase / replace-up
- New universe names outside ETHA/IBIT live + leftover protect/recycle
- Circuit breaker reset
- Expanding universe or changing Risk % numbers

Audit: Desk Lead logs every desk-approve in Helix + ticket file with `approved_by: desk_lead` and UTC. Execution treats desk-approve as human auth for PASS only.

---

## 8. Desk MV session authority (2026-09-15)

**Authority:** Anthony: “i approve you to be make execution calls on MV session issues” (2026-09-15 ~06:36 ET).  
**Status:** LAW until revoke (`desk may not run MV` or `disarm MV session` + explicit revoke).

Funds-beast may:
- Issue `arm MV session` / `disarm MV session` in Execution chat
- Drive Risk-PASS **MV-lane** tickets under an armed session until 16:00 / disarm / breaker

Still binds: soft max 3 opens, Risk PASS only, one-sell, no through-cap chase, ETHA+IBIT live universe, FOMC/CPI hard-hold when Desk Lead flags it.

Do not arm while opens=4 with no free slot. Prefer arm after a recycle frees capacity and cash/equity >20%.
