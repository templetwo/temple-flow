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
5. **Enforcement, and its exact scope.** `existing_sell()` is the primitive; the
   refusal is wired into **three** places, and nowhere else:
   - `plan_actions` protect lane — refuses a protect STOP when any SELL is working.
   - `plan_actions` entry lane — refuses a **bracket** when any SELL is working,
     because the bracket carries a child STOP SELL. (Added 2026-09-02. Until
     then the law was enforced only on the protect lane, so the entry lane could
     post exactly the second SELL Schwab rejected above.)
   - the outbox gate — same refusal, reason `one_sell_law_existing_sell`.

   It is **not** a property of `place_gtc_bracket()` itself. That function POSTs
   whatever it is handed. Anything calling it directly — a one-off script, a
   REPL, `scripts/send_tf_*.py` — bypasses the law entirely. The law lives in the
   planner and the gate, not in the wire.

See `docs/AMENDMENTS_2026-08-30.md`.

## Wire status

- **place_gtc_bracket**: real, proven live 2026-08-30 (HTTP 201, order 1007762031724)
- **cancel_by_id**: wired. Universe-restricted, RTH-only, and a Schwab 400 is
  persisted to `config/cancel_refusals.json` so it is retried at most once per
  trading day rather than every 900s.
- **one-sell enforcement**: planner (both lanes) + outbox gate. See the scope note above.
- **Ticket outbox**: `config/outbox/*.json`, gated on schema, universe, arm, RTH,
  risk box, `clip_qty`, a per-ticket notional cap, and book state. Every refusal
  quarantines to `failed/`. See `runbooks/AWAY_MODE.md` for the schema and guards.
- **Install script**: `scripts/install_act_loop.sh`. Decides and prints the
  LIVE_OK state before it loads anything, and refuses to arm a live daemon
  implicitly.

**Status: wired and gated, not "production-ready" in the sense of unattended and
proven.** The helper has one live fill behind it. The guard layer above it has
unit tests but no live session yet. `config/LIVE_OK` is the only thing between a
loaded plist and real money — treat every change here as a live-fire change.
