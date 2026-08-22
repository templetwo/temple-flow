# Temple Flow — Secondary + Extend Backfill Report

- **Completing run (UTC):** 2026-08-22T23:28:38Z → 2026-08-22T23:28:57Z (`backfill_runs.id=3`)
- **Started (ET):** 2026-08-22 19:28:38 EDT
- **Finished (ET):** 2026-08-22 19:28:57 EDT
- **Status:** `ok`
- **DB (canonical only):** `/workspace/temple-flow/data/temple_flow.sqlite`
- **Idempotent verify run:** `backfill_runs.id=4` (0 rows written; confirmed state)
- **Secondary universe:** BNB-USD, XRP-USD, AVAX-USD, LINK-USD, DOGE-USD
- **All active symbols:** AVAX-USD, BNB-USD, BTC-USD, DOGE-USD, ETH-USD, LINK-USD, SOL-USD, XRP-USD
- **Lookback target:** ~5 years daily OHLCV
- **DB date span:** 2021-08-22 → 2026-08-21
- **Total bars_daily:** 14569
- **Total indicators_daily:** 213559
- **Total regimes (tf_trend_vol_v1):** 12977
- **trading_calendar days:** 1826 (is_open sum=1826)
- **Provenance IDs (run 3):** [16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33]
- **Run notes:** secondary_bars=9091 indicators_new=133255 regimes=12977 method=tf_trend_vol_v1; calendar_added=0

## Secondary OHLCV summary

| Symbol | Source | Native | Date min | Date max | Bars | Gaps | Prov ID | Checksum |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| BNB-USD | yahoo | `BNB-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 16 | `4cd12fb3e1b01265…` |
| XRP-USD | yahoo | `XRP-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 17 | `138ced483abe20c3…` |
| AVAX-USD | coinbase_exchange | `AVAX-USD` | 2021-09-30 | 2026-08-21 | 1787 | 0 | 18 | `c79e6d231c97d3a0…` |
| LINK-USD | coinbase_exchange | `LINK-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 19 | `aa0f964a711bff42…` |
| DOGE-USD | coinbase_exchange | `DOGE-USD` | 2021-08-22 | 2026-08-21 | 1826 | 0 | 20 | `d7eece944e4ada03…` |

## Primary symbols (already in DB; extended this pass)

| Symbol | Source | Date min | Date max | Bars | Gaps |
| --- | --- | --- | --- | ---: | ---: |
| BTC-USD | coinbase_exchange_candles | 2021-08-22 | 2026-08-21 | 1826 | 0 |
| ETH-USD | coinbase_exchange_candles | 2021-08-22 | 2026-08-21 | 1826 | 0 |
| SOL-USD | coinbase_exchange_candles | 2021-08-22 | 2026-08-21 | 1826 | 0 |

## Sources & provenance (secondary)

### BNB-USD
- **source_name:** `yahoo`
- **source_uri:** `https://query1.finance.yahoo.com/v8/finance/chart/BNB-USD?interval=1d`
- **provenance_id:** 16
- **checksum:** `4cd12fb3e1b0126527e1d471e7bedec2f602479eb720973d7e73a9f14973a113`
- **notes:** native_venue_symbol=BNB-USD; interval=1d; adjust_method=none; preferred_order=kraken>coinbase_exchange>yahoo; Kraken insufficient (bars=487, span_days=486); Coinbase short (bars=304); selected=yahoo
- **adjust_method:** `none`
- **session_date:** America/New_York date of daily bar period end
- **range:** 2021-08-22 → 2026-08-21 (1826 bars, 0 gaps)

### XRP-USD
- **source_name:** `yahoo`
- **source_uri:** `https://query1.finance.yahoo.com/v8/finance/chart/XRP-USD?interval=1d`
- **provenance_id:** 17
- **checksum:** `138ced483abe20c3722c1c4bf1c6c36e54ee3c049e25819941f54318ed35b002`
- **notes:** native_venue_symbol=XRP-USD; interval=1d; adjust_method=none; preferred_order=kraken>coinbase_exchange>yahoo; Kraken insufficient (bars=720, span_days=719); Coinbase short (bars=1136); selected=yahoo
- **adjust_method:** `none`
- **session_date:** America/New_York date of daily bar period end
- **range:** 2021-08-22 → 2026-08-21 (1826 bars, 0 gaps)

### AVAX-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/AVAX-USD/candles?granularity=86400`
- **provenance_id:** 18
- **checksum:** `c79e6d231c97d3a0c52d2641146ea1379463d170cc8967de3aa07c398816488c`
- **notes:** native_venue_symbol=AVAX-USD; interval=1d; adjust_method=none; preferred_order=kraken>coinbase_exchange>yahoo; Kraken insufficient (bars=720, span_days=719); selected=coinbase_exchange
- **adjust_method:** `none`
- **session_date:** America/New_York date of daily bar period end
- **range:** 2021-09-30 → 2026-08-21 (1787 bars, 0 gaps)

### LINK-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/LINK-USD/candles?granularity=86400`
- **provenance_id:** 19
- **checksum:** `aa0f964a711bff42834cc4e84a233aeb72921a903cb5b9bc1da3e7d49aff9155`
- **notes:** native_venue_symbol=LINK-USD; interval=1d; adjust_method=none; preferred_order=kraken>coinbase_exchange>yahoo; Kraken insufficient (bars=720, span_days=719); selected=coinbase_exchange
- **adjust_method:** `none`
- **session_date:** America/New_York date of daily bar period end
- **range:** 2021-08-22 → 2026-08-21 (1826 bars, 0 gaps)

### DOGE-USD
- **source_name:** `coinbase_exchange`
- **source_uri:** `https://api.exchange.coinbase.com/products/DOGE-USD/candles?granularity=86400`
- **provenance_id:** 20
- **checksum:** `d7eece944e4ada0303fbd17ac0d19b7c5c5de6e34d4e9c1756c3245dee2463c6`
- **notes:** native_venue_symbol=DOGE-USD; interval=1d; adjust_method=none; preferred_order=kraken>coinbase_exchange>yahoo; Kraken insufficient (bars=720, span_days=719); selected=coinbase_exchange
- **adjust_method:** `none`
- **session_date:** America/New_York date of daily bar period end
- **range:** 2021-08-22 → 2026-08-21 (1826 bars, 0 gaps)

## Indicator coverage (all symbols)

Catalog names ensured. Computed offline from bars; warm-up skipped (no invention).
Kept ATR_14, ATR_60D_AVG, ATR_RATIO_14_60, RSI_14, SMA_50, SMA_200; extended MACD*, BB_*, SMA_20, EMA_12, EMA_26.

### AVAX-USD
| Indicator | Rows |
| --- | ---: |
| `RSI_14` | 1773 |
| `MACD` | 1762 |
| `MACD_SIGNAL` | 1754 |
| `MACD_HIST` | 1754 |
| `BB_UPPER` | 1768 |
| `BB_MID` | 1768 |
| `BB_LOWER` | 1768 |
| `SMA_20` | 1768 |
| `SMA_50` | 1738 |
| `SMA_200` | 1588 |
| `EMA_12` | 1776 |
| `EMA_26` | 1762 |
| `ATR_14` | 1774 |
| `ATR_60D_AVG` | 1715 |
| `ATR_RATIO_14_60` | 1715 |

### BNB-USD
| Indicator | Rows |
| --- | ---: |
| `RSI_14` | 1812 |
| `MACD` | 1801 |
| `MACD_SIGNAL` | 1793 |
| `MACD_HIST` | 1793 |
| `BB_UPPER` | 1807 |
| `BB_MID` | 1807 |
| `BB_LOWER` | 1807 |
| `SMA_20` | 1807 |
| `SMA_50` | 1777 |
| `SMA_200` | 1627 |
| `EMA_12` | 1815 |
| `EMA_26` | 1801 |
| `ATR_14` | 1813 |
| `ATR_60D_AVG` | 1754 |
| `ATR_RATIO_14_60` | 1754 |

### BTC-USD
| Indicator | Rows |
| --- | ---: |
| `RSI_14` | 1812 |
| `MACD` | 1801 |
| `MACD_SIGNAL` | 1793 |
| `MACD_HIST` | 1793 |
| `BB_UPPER` | 1807 |
| `BB_MID` | 1807 |
| `BB_LOWER` | 1807 |
| `SMA_20` | 1807 |
| `SMA_50` | 1777 |
| `SMA_200` | 1627 |
| `EMA_12` | 1815 |
| `EMA_26` | 1801 |
| `ATR_14` | 1813 |
| `ATR_60D_AVG` | 1754 |
| `ATR_RATIO_14_60` | 1754 |

### DOGE-USD
| Indicator | Rows |
| --- | ---: |
| `RSI_14` | 1812 |
| `MACD` | 1801 |
| `MACD_SIGNAL` | 1793 |
| `MACD_HIST` | 1793 |
| `BB_UPPER` | 1807 |
| `BB_MID` | 1807 |
| `BB_LOWER` | 1807 |
| `SMA_20` | 1807 |
| `SMA_50` | 1777 |
| `SMA_200` | 1627 |
| `EMA_12` | 1815 |
| `EMA_26` | 1801 |
| `ATR_14` | 1813 |
| `ATR_60D_AVG` | 1754 |
| `ATR_RATIO_14_60` | 1754 |

### ETH-USD
| Indicator | Rows |
| --- | ---: |
| `RSI_14` | 1812 |
| `MACD` | 1801 |
| `MACD_SIGNAL` | 1793 |
| `MACD_HIST` | 1793 |
| `BB_UPPER` | 1807 |
| `BB_MID` | 1807 |
| `BB_LOWER` | 1807 |
| `SMA_20` | 1807 |
| `SMA_50` | 1777 |
| `SMA_200` | 1627 |
| `EMA_12` | 1815 |
| `EMA_26` | 1801 |
| `ATR_14` | 1813 |
| `ATR_60D_AVG` | 1754 |
| `ATR_RATIO_14_60` | 1754 |

### LINK-USD
| Indicator | Rows |
| --- | ---: |
| `RSI_14` | 1812 |
| `MACD` | 1801 |
| `MACD_SIGNAL` | 1793 |
| `MACD_HIST` | 1793 |
| `BB_UPPER` | 1807 |
| `BB_MID` | 1807 |
| `BB_LOWER` | 1807 |
| `SMA_20` | 1807 |
| `SMA_50` | 1777 |
| `SMA_200` | 1627 |
| `EMA_12` | 1815 |
| `EMA_26` | 1801 |
| `ATR_14` | 1813 |
| `ATR_60D_AVG` | 1754 |
| `ATR_RATIO_14_60` | 1754 |

### SOL-USD
| Indicator | Rows |
| --- | ---: |
| `RSI_14` | 1812 |
| `MACD` | 1801 |
| `MACD_SIGNAL` | 1793 |
| `MACD_HIST` | 1793 |
| `BB_UPPER` | 1807 |
| `BB_MID` | 1807 |
| `BB_LOWER` | 1807 |
| `SMA_20` | 1807 |
| `SMA_50` | 1777 |
| `SMA_200` | 1627 |
| `EMA_12` | 1815 |
| `EMA_26` | 1801 |
| `ATR_14` | 1813 |
| `ATR_60D_AVG` | 1754 |
| `ATR_RATIO_14_60` | 1754 |

### XRP-USD
| Indicator | Rows |
| --- | ---: |
| `RSI_14` | 1812 |
| `MACD` | 1801 |
| `MACD_SIGNAL` | 1793 |
| `MACD_HIST` | 1793 |
| `BB_UPPER` | 1807 |
| `BB_MID` | 1807 |
| `BB_LOWER` | 1807 |
| `SMA_20` | 1807 |
| `SMA_50` | 1777 |
| `SMA_200` | 1627 |
| `EMA_12` | 1815 |
| `EMA_26` | 1801 |
| `ATR_14` | 1813 |
| `ATR_60D_AVG` | 1754 |
| `ATR_RATIO_14_60` | 1754 |

## Regimes (`tf_trend_vol_v1`)

Deterministic offline method `tf_trend_vol_v1`: SMA_50 vs SMA_200 relation (band=0.005) + SMA_50 slope (lookback=5) + ATR_RATIO_14_60 high_vol flag (threshold=1.8). Params in each row `details_json`. Primary also retains prior `tf_regime_v1` rows (different method key).

| Symbol | Total | trend_up | trend_down | range | high_vol |
| --- | ---: | ---: | ---: | ---: | ---: |
| AVAX-USD | 1588 | 422 | 1094 | 7 | 65 |
| BNB-USD | 1627 | 713 | 832 | 36 | 46 |
| BTC-USD | 1627 | 824 | 775 | 22 | 6 |
| DOGE-USD | 1627 | 517 | 1009 | 7 | 94 |
| ETH-USD | 1627 | 688 | 916 | 17 | 6 |
| LINK-USD | 1627 | 490 | 1062 | 14 | 61 |
| SOL-USD | 1627 | 629 | 941 | 18 | 39 |
| XRP-USD | 1627 | 672 | 842 | 28 | 85 |

## Gaps

Crypto calendar: every America/New_York day `is_open=1` except documented outages. No equity holidays as gaps. No invented bars.

### BNB-USD
- Contiguous span 2021-08-22 → 2026-08-21: **0** missing session_dates
- No gaps inside contiguous daily series.

### XRP-USD
- Contiguous span 2021-08-22 → 2026-08-21: **0** missing session_dates
- No gaps inside contiguous daily series.

### AVAX-USD
- Contiguous span 2021-09-30 → 2026-08-21: **0** missing session_dates
- AVAX history begins 2021-09-30 on selected Coinbase feed (shorter than ~5y BTC/ETH window; not a mid-span gap).
- No gaps inside contiguous daily series.

### LINK-USD
- Contiguous span 2021-08-22 → 2026-08-21: **0** missing session_dates
- No gaps inside contiguous daily series.

### DOGE-USD
- Contiguous span 2021-08-22 → 2026-08-21: **0** missing session_dates
- No gaps inside contiguous daily series.

## Failures / blockers

- None blocking. Kraken public OHLC ~720d insufficient for 5y on all secondary symbols → fell through per conventions.
- BNB-USD / XRP-USD: Coinbase history shorter than lookback target → Yahoo fallback (documented in provenance notes).
- AVAX-USD: Coinbase listing/availability from 2021-09-30 (1787 bars); no mid-series gaps.

## Validation notes

- Appended to canonical DB only; no second database.
- Source order honored: Kraken → Coinbase Exchange → Yahoo.
- Indicators from stored bars only; warm-up skipped.
- Regimes method `tf_trend_vol_v1` reproducible from details_json params.
