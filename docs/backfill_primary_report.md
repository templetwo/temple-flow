# Temple Flow — Primary Historical Backfill Report

- **Run started (UTC):** 2026-08-22T23:25:46Z
- **Run finished (UTC):** 2026-08-22T23:25:55Z
- **Started (ET):** 2026-08-22 19:25:46 EDT
- **Finished (ET):** 2026-08-22 19:25:55 EDT
- **Status:** `ok`
- **DB:** `/workspace/temple-flow/data/temple_flow.sqlite`
- **Universe:** BTC-USD, ETH-USD, SOL-USD
- **Lookback target:** ~5 years daily OHLCV
- **Global date span:** 2021-08-22 → 2026-08-21
- **Total bar rows:** 5478
- **Total indicator rows:** 31602

## Per-symbol summary

| Symbol | Source | Native | Date min | Date max | Bars | Gaps | Indicators |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| BTC-USD | coinbase_exchange | `BTC-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 10534 |
| ETH-USD | coinbase_exchange | `ETH-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 10534 |
| SOL-USD | coinbase_exchange | `SOL-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 10534 |

## Sources & provenance

### BTC-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400`
- **native venue symbol:** `BTC-USD`
- **provenance_id (bars):** 1
- **checksum (bars):** `22342e763884efc0d1fec1b0e46ae5bbdaefc716f8c113fd1496cdcf62334a7d`
- **indicator provenance_id:** 2
- **adjust_method:** `none` (spot); adj_close/split/dividend null

Indicator coverage (row counts):

- `ATR_14`: 1812
- `ATR_60D_AVG`: 1753
- `ATR_RATIO_14_60`: 1753
- `RSI_14`: 1812
- `SMA_50`: 1777
- `SMA_200`: 1627

### ETH-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=86400`
- **native venue symbol:** `ETH-USD`
- **provenance_id (bars):** 3
- **checksum (bars):** `bd9ca75911e88df2012ea63ad080153ffacaec5710a6487a75dceaabfb3eb771`
- **indicator provenance_id:** 4
- **adjust_method:** `none` (spot); adj_close/split/dividend null

Indicator coverage (row counts):

- `ATR_14`: 1812
- `ATR_60D_AVG`: 1753
- `ATR_RATIO_14_60`: 1753
- `RSI_14`: 1812
- `SMA_50`: 1777
- `SMA_200`: 1627

### SOL-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/SOL-USD/candles?granularity=86400`
- **native venue symbol:** `SOL-USD`
- **provenance_id (bars):** 5
- **checksum (bars):** `d7e7d857ea62825e80541ed6e3cca91500ed7d13df9959d9c0f3bb8e278fdaf6`
- **indicator provenance_id:** 6
- **adjust_method:** `none` (spot); adj_close/split/dividend null

Indicator coverage (row counts):

- `ATR_14`: 1812
- `ATR_60D_AVG`: 1753
- `ATR_RATIO_14_60`: 1753
- `RSI_14`: 1812
- `SMA_50`: 1777
- `SMA_200`: 1627

## Source selection notes

Preferred order (Kraken → Coinbase Exchange → Yahoo) was honored for every symbol.

- **Kraken** public `OHLC` (`XXBTZUSD` / `XETHZUSD` / `SOLUSD`, interval=1440) returns at most ~720 committed daily candles (~719 calendar-day span). That is below the ~5y lookback target, so Kraken was **not** selected as the stored series.
- **Coinbase Exchange** daily candles (`granularity=86400`) covered the full lookback with **0** missing session dates for all three symbols and was written to `bars_daily`.
- **Yahoo** was not needed.

No documented Coinbase outages in this span; `trading_calendar.is_open=1` for every day from 2021-08-22 through 2026-08-21.

## Gap / outage notes

Crypto calendar treats every America/New_York calendar day as `is_open=1` except documented exchange outages. No equity holidays applied as gaps.

### BTC-USD
- Missing session_date count vs contiguous calendar: **0**
- No gaps in contiguous daily series.

### ETH-USD
- Missing session_date count vs contiguous calendar: **0**
- No gaps in contiguous daily series.

### SOL-USD
- Missing session_date count vs contiguous calendar: **0**
- No gaps in contiguous daily series.

## Failures

- None.

## Validation notes

- `session_date` = America/New_York date of daily bar period end (UTC midnight–aligned bars).
- Preferred source order honored: Kraken → Coinbase Exchange → Yahoo.
- Indicators computed offline from stored bars only; names match `indicator_catalog`.
- No invented bars.
