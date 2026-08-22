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
