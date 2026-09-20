# Temple Flow — Secondary Historical Backfill Report

> **Desk Lead correction (Data & Backfill, 2026-08-22T23:31Z):** Prefer regime method **`tf_trend_vol_v1`** for Technical packages (Desk Lead + Data agreed). A late parallel remediate (`backfill_runs.id=5`) also wrote additive `tf_regime_v1` rows and briefly overstated that method as canonical in this file — **ignore that**. Bars/indicators unchanged and intact. Both methods currently coexist (12977 rows each); consumers should filter `method='tf_trend_vol_v1'`.

- **Run started (UTC):** 2026-08-22T23:30:05Z
- **Run finished (UTC):** 2026-08-22T23:30:10Z
- **Started (ET):** 2026-08-22 19:30:05 EDT
- **Finished (ET):** 2026-08-22 19:30:10 EDT
- **backfill_runs.id:** 5 (remediate/canonicalize; bar load was run 3, status=ok)
- **Prior secondary load run:** 3
- **Status:** `ok`
- **DB:** `/workspace/temple-flow/data/temple_flow.sqlite`
- **Secondary universe:** BNB-USD, XRP-USD, AVAX-USD, LINK-USD, DOGE-USD
- **Lookback target:** 2021-08-22 → 2026-08-21
- **Rows written this remediate run:** 226536
- **DB totals — bars:** 14569
- **DB totals — indicators:** 213559
- **DB totals — regimes (tf_trend_vol_v1 preferred):** 12977
- **DB totals — regimes (tf_regime_v1 additive):** 12977
- **DB totals — regimes (all methods):** 25954

## Per-symbol summary (secondary)

| Symbol | Source | Native | Date min | Date max | Bars | Gaps | Indicators | Regimes | Prov (bars) |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| BNB-USD | yahoo | `BNB-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 26768 | 1627 | 16 |
| XRP-USD | yahoo | `XRP-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 26768 | 1627 | 17 |
| AVAX-USD | coinbase_exchange | `AVAX-USD` | 2021-09-30 | 2026-08-21 | 1787 | 0 | 26183 | 1588 | 18 |
| LINK-USD | coinbase_exchange | `LINK-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 26768 | 1627 | 19 |
| DOGE-USD | coinbase_exchange | `DOGE-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 26768 | 1627 | 20 |

## Sources & provenance (secondary)

### BNB-USD
- **source_name:** `yahoo`
- **source_uri:** `https://query1.finance.yahoo.com/v8/finance/chart/BNB-USD?interval=1d`
- **native venue symbol:** `BNB-USD`
- **provenance_id (bars):** 16
- **checksum (bars):** `4cd12fb3e1b0126527e1d471e7bedec2f602479eb720973d7e73a9f14973a113`
- **indicator provenance_id:** 36
- **regime provenance_id:** 37
- **adjust_method:** `none` (spot); adj_close/split/dividend null
- **upgrade note:** coinbase_short n=304

Indicator coverage (row counts):

- `ATR_14`: 1813
- `ATR_60D_AVG`: 1754
- `ATR_RATIO_14_60`: 1754
- `RSI_14`: 1812
- `MACD`: 1801
- `MACD_SIGNAL`: 1793
- `MACD_HIST`: 1793
- `BB_UPPER`: 1807
- `BB_MID`: 1807
- `BB_LOWER`: 1807
- `SMA_20`: 1807
- `SMA_50`: 1777
- `SMA_200`: 1627
- `EMA_12`: 1815
- `EMA_26`: 1801

### XRP-USD
- **source_name:** `yahoo`
- **source_uri:** `https://query1.finance.yahoo.com/v8/finance/chart/XRP-USD?interval=1d`
- **native venue symbol:** `XRP-USD`
- **provenance_id (bars):** 17
- **checksum (bars):** `138ced483abe20c3722c1c4bf1c6c36e54ee3c049e25819941f54318ed35b002`
- **indicator provenance_id:** 48
- **regime provenance_id:** 49
- **adjust_method:** `none` (spot); adj_close/split/dividend null
- **upgrade note:** coinbase_short n=1136

Indicator coverage (row counts):

- `ATR_14`: 1813
- `ATR_60D_AVG`: 1754
- `ATR_RATIO_14_60`: 1754
- `RSI_14`: 1812
- `MACD`: 1801
- `MACD_SIGNAL`: 1793
- `MACD_HIST`: 1793
- `BB_UPPER`: 1807
- `BB_MID`: 1807
- `BB_LOWER`: 1807
- `SMA_20`: 1807
- `SMA_50`: 1777
- `SMA_200`: 1627
- `EMA_12`: 1815
- `EMA_26`: 1801

### AVAX-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/AVAX-USD/candles?granularity=86400`
- **native venue symbol:** `AVAX-USD`
- **provenance_id (bars):** 18
- **checksum (bars):** `c79e6d231c97d3a0c52d2641146ea1379463d170cc8967de3aa07c398816488c`
- **indicator provenance_id:** 34
- **regime provenance_id:** 35
- **adjust_method:** `none` (spot); adj_close/split/dividend null
- **anomaly:** shorter history than target start 2021-08-22 (first bar 2021-09-30); no pre-listing bars invented

Indicator coverage (row counts):

- `ATR_14`: 1774
- `ATR_60D_AVG`: 1715
- `ATR_RATIO_14_60`: 1715
- `RSI_14`: 1773
- `MACD`: 1762
- `MACD_SIGNAL`: 1754
- `MACD_HIST`: 1754
- `BB_UPPER`: 1768
- `BB_MID`: 1768
- `BB_LOWER`: 1768
- `SMA_20`: 1768
- `SMA_50`: 1738
- `SMA_200`: 1588
- `EMA_12`: 1776
- `EMA_26`: 1762

### LINK-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/LINK-USD/candles?granularity=86400`
- **native venue symbol:** `LINK-USD`
- **provenance_id (bars):** 19
- **checksum (bars):** `aa0f964a711bff42834cc4e84a233aeb72921a903cb5b9bc1da3e7d49aff9155`
- **indicator provenance_id:** 44
- **regime provenance_id:** 45
- **adjust_method:** `none` (spot); adj_close/split/dividend null

Indicator coverage (row counts):

- `ATR_14`: 1813
- `ATR_60D_AVG`: 1754
- `ATR_RATIO_14_60`: 1754
- `RSI_14`: 1812
- `MACD`: 1801
- `MACD_SIGNAL`: 1793
- `MACD_HIST`: 1793
- `BB_UPPER`: 1807
- `BB_MID`: 1807
- `BB_LOWER`: 1807
- `SMA_20`: 1807
- `SMA_50`: 1777
- `SMA_200`: 1627
- `EMA_12`: 1815
- `EMA_26`: 1801

### DOGE-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/DOGE-USD/candles?granularity=86400`
- **native venue symbol:** `DOGE-USD`
- **provenance_id (bars):** 20
- **checksum (bars):** `d7eece944e4ada0303fbd17ac0d19b7c5c5de6e34d4e9c1756c3245dee2463c6`
- **indicator provenance_id:** 40
- **regime provenance_id:** 41
- **adjust_method:** `none` (spot); adj_close/split/dividend null

Indicator coverage (row counts):

- `ATR_14`: 1813
- `ATR_60D_AVG`: 1754
- `ATR_RATIO_14_60`: 1754
- `RSI_14`: 1812
- `MACD`: 1801
- `MACD_SIGNAL`: 1793
- `MACD_HIST`: 1793
- `BB_UPPER`: 1807
- `BB_MID`: 1807
- `BB_LOWER`: 1807
- `SMA_20`: 1807
- `SMA_50`: 1777
- `SMA_200`: 1627
- `EMA_12`: 1815
- `EMA_26`: 1801

## Whole-DB indicator / regime extension

| Symbol | Bars | Indicator rows | Regime rows (tf_regime_v1) | Ind prov | Regime prov |
| --- | ---: | ---: | ---: | ---: | ---: |
| AVAX-USD | 1787 | 26183 | 1588 | 34 | 35 |
| BNB-USD | 1826 | 26768 | 1627 | 36 | 37 |
| BTC-USD | 1826 | 26768 | 1627 | 38 | 39 |
| DOGE-USD | 1826 | 26768 | 1627 | 40 | 41 |
| ETH-USD | 1826 | 26768 | 1627 | 42 | 43 |
| LINK-USD | 1826 | 26768 | 1627 | 44 | 45 |
| SOL-USD | 1826 | 26768 | 1627 | 46 | 47 |
| XRP-USD | 1826 | 26768 | 1627 | 48 | 49 |

### Indicator catalog row counts (whole DB)

- `ATR_14`: 14465
- `ATR_60D_AVG`: 13993
- `ATR_RATIO_14_60`: 13993
- `RSI_14`: 14457
- `MACD`: 14369
- `MACD_SIGNAL`: 14305
- `MACD_HIST`: 14305
- `BB_UPPER`: 14417
- `BB_MID`: 14417
- `BB_LOWER`: 14417
- `SMA_20`: 14417
- `SMA_50`: 14177
- `SMA_200`: 12977
- `EMA_12`: 14481
- `EMA_26`: 14369

### Regime label counts (method `tf_regime_v1`)

- `high_vol`: 402
- `trend_down`: 7540
- `trend_up`: 5035

Regime rules (`details_json.rules`):

- `trend_up`: SMA_50 > SMA_200 and ATR_RATIO_14_60 <= 1.8
- `trend_down`: SMA_50 < SMA_200 and ATR_RATIO_14_60 <= 1.8
- `high_vol`: ATR_RATIO_14_60 > 1.8
- `range`: else
- provenance `source_name`: `offline_regimes_v1`

Note: both `tf_trend_vol_v1` (Desk Lead preferred for Technical) and `tf_regime_v1` (additive from run 5) exist; **use `tf_trend_vol_v1`**.

## Source selection notes

Preferred order (Kraken → Coinbase Exchange → Yahoo) honored.
Kraken public daily OHLC ~720 candles is insufficient for ~5y.
BNB-USD / XRP-USD: Kraken insufficient (~720d). Coinbase Exchange daily candles only from ~2025-10-22 (BNB-USD, ~304 bars) and ~2023-07-13 (XRP-USD, ~1136 bars; post US trading gap). Yahoo `*-USD` fallback used to reach the ~5y target. Exchange preferred when coverage is adequate (AVAX/LINK/DOGE on Coinbase).
AVAX-USD Coinbase history begins 2021-09-30 (honest shorter span; no invented pre-listing bars).

## Gap / outage notes

Crypto calendar: every NY calendar day `is_open=1` except documented outages (none applied). Gap checks from each symbol's first bar.

### BNB-USD
- Missing vs open calendar from first bar: **0**
- No gaps in contiguous daily series from first bar.

### XRP-USD
- Missing vs open calendar from first bar: **0**
- No gaps in contiguous daily series from first bar.

### AVAX-USD
- Missing vs open calendar from first bar: **0**
- No gaps in contiguous daily series from first bar.
- Pre-listing before 2021-09-30 excluded from gap expectation.

### LINK-USD
- Missing vs open calendar from first bar: **0**
- No gaps in contiguous daily series from first bar.

### DOGE-USD
- Missing vs open calendar from first bar: **0**
- No gaps in contiguous daily series from first bar.

### BTC-USD
- Missing vs open calendar from first bar: **0**
- No gaps in contiguous daily series from first bar.

### ETH-USD
- Missing vs open calendar from first bar: **0**
- No gaps in contiguous daily series from first bar.

### SOL-USD
- Missing vs open calendar from first bar: **0**
- No gaps in contiguous daily series from first bar.

## Anomalies

- BNB-USD: Coinbase listed daily only from ~2025-10-22 (~304 bars) → Yahoo fallback for full 2021-08-22→2026-08-21 (1826 bars, 0 gaps).
- XRP-USD: Coinbase daily only from ~2023-07-13 (~1136 bars) → Yahoo fallback for full span (1826 bars, 0 gaps).
- AVAX-USD: Coinbase series starts 2021-09-30 (shorter than target 2021-08-22); no pre-listing bars invented.
- AVAX-USD: first bar 2021-09-30 after target 2021-08-22

## Failures

- None.

## Validation notes

- `session_date` = America/New_York date of daily bar period end.
- Preferred source order: Kraken → Coinbase Exchange → Yahoo.
- Indicators from stored bars; catalog names only; idempotent upserts.
- Regimes: prefer `tf_trend_vol_v1` (Desk Lead); `tf_regime_v1` / `offline_regimes_v1` also present from run 5.
- Primary bars preserved (APPEND only). No invented bars. No trade ideas. No wipe.

