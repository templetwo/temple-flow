# Bracket helper — wired (2026-08-30 live proof)

**Question:** Does spiral-broker post a first-class OTC / OCO / bracket (GTC limit + attached stop) as one Schwab mutation?

**Answer: YES.** Live proof 2026-08-30: IBIT BUY 2 @43.90 TRIGGER got HTTP 201 as order 1007762031724.

## What exists

| Piece | Where | What it does |
| --- | --- | --- |
| TokenManager | `~/spiral-broker/src/token_manager.py` | OAuth access/refresh. Used after `chdir` + load `~/spiral-broker/.env`. |
| Market tools | `~/spiral-broker/dashboard/api/services/schwab_tools.py` | Quotes / market data. |
| Read-only book + orders | Temple Flow and MV watch scripts | `GET /trader/v1/accounts?fields=positions` · `GET /marketdata/v1/quotes` · `GET /trader/v1/accounts/{hash}/orders` with `fromEnteredTime` / `toEnteredTime` 10-day window. |
| **place_gtc_bracket** | `scripts/temple_flow_wire.py` | **REAL.** POST one Schwab order: GTC LIMIT BUY + attached GTC STOP SELL (TRIGGER orderStrategyType). Reuses TokenManager + SCHWAB_ACCOUNT_HASH. |
| **cancel_by_id** | `scripts/temple_flow_wire.py` | **WIRED.** DELETE `/trader/v1/accounts/{hash}/orders/{id}`. HTTP 400 after hours on PENDING_ACTIVATION = leave it. |

## One-sell law (2026-08-30 live proof)

Sunday after hours, ETHA already had STOP 17.70 `PENDING_ACTIVATION`. A second SELL LIMIT 19.80 was **REJECTED**. An OCO posted *without* canceling that stop was **REJECTED**. Cancel of the pending-activation stop returned HTTP **400**.

Implication for the helper:

1. Entry path: one POST, GTC LIMIT BUY + attached GTC STOP. That is the only sell on the share.
2. Flatten path: RTH only. Cancel (or REPLACE) the existing stop, then one OCO (LIMIT take-profit XOR STOP). Never POST a second standalone SELL.
3. After hours: no flatten retry. Leave the stop. Next RTH replace.
4. Two singles is not an OCO. Schwab treats the stop as owning the share.
5. **Enforcement:** `plan_actions` now refuses to place a SELL if any working SELL order exists on that symbol (one-sell law).

See `docs/AMENDMENTS_2026-08-30.md`.

## Wire status

- ✅ **place_gtc_bracket**: real, tested live
- ✅ **cancel_by_id**: wired, handles 400 after hours
- ✅ **one-sell enforcement**: planner refuses duplicate SELLs
- ✅ **Ticket outbox**: `config/outbox/*.json` for one-off approved tickets
- ✅ **Install script**: `scripts/install_act_loop.sh` for launchd setup

The bracket helper is **production-ready** for Studio launchd use with `config/LIVE_OK` gate.
