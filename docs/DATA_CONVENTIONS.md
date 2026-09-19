# Data conventions — crypto signal layer

**Locked 2026-08-22 by Desk Lead (Funds-beast).**

## Session / calendar
- `session_date` = **America/New_York** calendar date of the daily bar’s **period end**.
- Crypto `trading_calendar`: `is_open=1` every day except **documented exchange outages**.
- Do **not** treat equity holidays as missing crypto bars.

## Symbols
- `universe.symbol` uses UNIVERSE.md labels (`BTC-USD`, `ETH-USD`, …).
- Native venue ids (e.g. Kraken `XBTUSD`, Coinbase `BTC-USD`) live in `data_provenance.source_uri` / notes.

## Adjustments
- Spot crypto: `adjust_method=none`; `adj_close` / split / dividend null unless source is an index product.

## Approved public sources (signal layer)
Priority order:
1. Kraken OHLC
2. Coinbase Exchange candles
3. Yahoo Finance `*-USD` (fallback only)

Always checksum + provenance. No chart scraping. No invented bars.

Studio goldbrick/spiral-broker paths, when provided, **override** as preferred provenance for the same symbols.

## Lookback
- Default: **5 years** daily for primary set (BTC/ETH/SOL), then secondary.
- Intraday 1h only after daily validation.


## Approved evidence sources (ops eyes — not bars_daily gold)

**Locked 2026-09-19 by Desk Lead (Funds-beast)** after Eyes PR #5 merge (`81a0e84`).

- **Twelve Data** via `scripts/temple_flow_eyes.py` is an **evidence-only** market-eyes source when Schwab (or other live book) is dark or for desk quotes/history.
- Key: Studio-only `TWELVE_DATA_API_KEY` in git-ignored `.env` (also readable from `$SPIRAL_BROKER_ROOT/.env`). Never commit; never paste in chat.
- Credit ledger: default 8/min, 400/day; TTL cache under `data/cache/eyes/`.
- **Does not** write `bars_daily`, size tickets, or touch the Schwab wire / order path.
- **Does not** replace the approved public sources above for crypto signal-layer gold brick. Yahoo / Kraken / Coinbase remain the listed priority for that layer unless a later amendment promotes Twelve Data into bars_daily.
- Book snapshots shown by eyes are labeled STALE when sourced from carry JSON; never treat eyes marks as the live execution book.
