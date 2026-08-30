# Bracket helper — gap note (2026-08-28)

**Question:** Does spiral-broker already post a first-class OTC / OCO / bracket (GTC limit + attached stop) as one Schwab mutation?

**Answer: no.** Inspected on Mac Studio, read-only, 2026-08-28. No live POST was made. Tokens were not printed.

## What exists

| Piece | Where | What it does |
| --- | --- | --- |
| TokenManager | `~/spiral-broker/src/token_manager.py` | OAuth access/refresh. Used after `chdir` + load `~/spiral-broker/.env`. |
| Market tools | `~/spiral-broker/dashboard/api/services/schwab_tools.py` | Quotes / market data. No order POST. |
| Dashboard broker routes | `~/spiral-broker/dashboard/api/routes/broker.py` | `simulate_trade` only. Not Schwab. |
| Read-only book + orders | `~/spiral-broker/mv_watch_snapshot.py` (also `temple-flow/scripts/mv_watch_snapshot.py`) | `GET /trader/v1/accounts?fields=positions` · `GET /marketdata/v1/quotes` · `GET /trader/v1/accounts/{hash}/orders` with `fromEnteredTime` / `toEnteredTime` 10-day window. |
| Auth POSTs | `src/schwab_auth.py`, `src/token_manager.py` | Token URL only. Not trader orders. |

Live week-1 fills (NVO trim, NOK buy, NOK stop, ETHA DAY 18.75) were ad-hoc sends, **stop-after-fill**, not a stored OCO/bracket helper.

## What was not found

- No `place_order` / `place_gtc_bracket` / `place_oco` / `create_order` in first-party spiral-broker Python.
- No `orderStrategyType` of `OCO` or `TRIGGER`.
- No POST to `https://api.schwabapi.com/trader/v1/accounts/{accountHash}/orders`.
- No cancel-by-id or replace helper in-repo.

`scripts/temple_flow_wire.py` therefore stubs:

```python
def place_gtc_bracket(...):
    raise NotImplementedError(...)
```

`--live` must refuse this path even if `config/LIVE_OK` and `TEMPLE_FLOW_LIVE=1` are set.

## Remaining gap before `--live` is safe

1. A real helper on the Studio that POSTs **one** Schwab order: GTC LIMIT BUY + attached GTC STOP SELL (TRIGGER or equivalent first-class bracket), using the existing TokenManager + `SCHWAB_ACCOUNT_HASH`.
2. A matching protect-only STOP SELL GTC for leftovers (NVO / NOK) and a cancel-by-id for through-cap / DAY abandon.
3. A paper or one-share Studio proof that Schwab accepts the payload (duration `GOOD_TILL_CANCEL`, child stop attached, no DAY).
4. Anthony at the Studio. Home Terminal only — not Grok Desktop, not the phone.
5. `config/LIVE_OK` + `TEMPLE_FLOW_LIVE=1` for that one session. launchd plist stays `--once` dry-run.

Until those exist, cash idle and a dry-run daemon are the correct Act loop.
