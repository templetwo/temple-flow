# Temple Flow — Shadow Desk Brief
**As-of:** 2026-08-22 evening ET (weekend) · **Mode:** shadow · **No orders sent**

## Book (live Schwab)
- Equity **$95.63** · Cash **$2.15** · Peak baseline **$95.63**
- Positions: **NVO 2** (MTM ~$93.48)
- Quotes: IBIT ~$44.38 · ETHA ~$18.98 · FBTC ~$68.5

## Data / technical (bars through 2026-08-21)
- Crypto universe printed a sharp up-day (BTC +7.3%, ETH +8.1%, SOL +6.9%; secondaries +5–15%)
- RSI_14 stretched **77–88** across the set (overbought)
- ATR filter **not** triggered (ratios < 1.8)
- `tf_trend_vol_v1` still says **trend_down** while price > SMA50 — **method lag**; do not treat as high-confidence regime

## Opportunities
None that clear Risk at this equity.

## Shadow tickets (vetoed — demo of constitution)
| ID | Idea | Why veto |
| --- | --- | --- |
| TF-20260822-01 | Buy 1 IBIT @ ~$44.38 | ≈46.4% equity > 18% max position; cash $2.15 |
| TF-20260822-02 | Buy 1 ETHA @ ~$18.98 | ≈19.8% equity > 18% max position |

## What the system just proved
1. Backfill DB → live technical package
2. Schwab auth → book + vehicle quotes
3. Ticket IDs + Risk veto without human pressure
4. Human gate untouched (Execution idle)

## Practical next levers
1. Fund account so 1× IBIT ≤ 18% equity (**≥ ~$247** equity for one IBIT), or
2. Explicitly amend max-position for micro-book, or
3. Stay in shadow research on spot until capital fits
