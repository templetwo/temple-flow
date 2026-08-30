# Amendment 2026-08-30 — one-sell / OCO replace

**Authority:** Live Schwab reject, 2026-08-30 ~18:57 ET. Human: "make a note of this and learn from it."  
**Status:** LAW.  
**Does not move:** 2.5% / 4.5% day / 18% peak DD / hard stops / ETHA+IBIT only / GTC+attached stop as the first mutation.

## What happened
ETHA was already long 1 with STOP 17.70 GTC `1007757064203` `PENDING_ACTIVATION`.  
Desk sent a second SELL: LIMIT 19.80 GTC flatten `1007762031740` → **REJECTED**.  
Then OCO 19.80 XOR 17.70 `1007762031741` without the old stop gone → **REJECTED**.  
`DELETE` of the pending-activation stop after hours → HTTP **400**. Stop stayed on.

IBIT BUY 2 @ 43.90 `1007762031724` and NVO STOP 42.50 `1007762031723` were unaffected (still pending Monday).

## Law
A share with an existing SELL STOP (`WORKING` or `PENDING_ACTIVATION`) **cannot** take a second SELL.

- Standalone LIMIT flatten on that share: reject.
- OCO (limit XOR stop) while the old stop still owns the share: reject.
- After hours, cancel of `PENDING_ACTIVATION` stops: HTTP 400. Do not retry. Leave the stop on.

Flatten is **not** a second ticket. It is an **RTH replace** of the stop: cancel the stop, then one OCO (take-profit LIMIT XOR the same STOP). Same session only.

`REJECTED` is not `WORKING`. Do not invent a flatten. Do not duplicate after a reject.

New entries stay one mutation: GTC BUY + attached STOP. The take-profit is either attached at entry or swapped in at RTH via that replace. Never stacked.

## Monday follow-through (this book)
ETHA: cancel `1007757064203`, then OCO 19.80 XOR 17.70. Do not send 19.80 while 17.70 is live.  
IBIT flatten 45: only after parent `1007762031724` fills, and only as OCO vs the attached 41.20 — never a naked second sell, never a short.
