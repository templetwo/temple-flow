# Reconcile OUNTNO-XBVAK-EPG6QI — 2026-09-20 MacBook Kraken

**Do not cancel.** Parent filled. Native stop is working.

| Field | Live `QueryOrders` / `OpenOrders` |
|-------|-----------------------------------|
| Parent `OUNTNO-XBVAK-EPG6QI` | **closed** · vol 0.0012 · vol_exec 0.0012 · cost 97.49352 · descr.close `close position @ stop loss 78454.6` |
| Child / working | `O55VHG-TY4DM-O3KIJT` SELL stop-loss XBTUSD qty 0.0012 @ **78454.6** remaining 0.0012 |
| Position | XXBT 0.0012000000 |
| ZUSD leftover | 2.1165 (Balance; resting stop is a sell, not a buy reservation) |

The passdown `stop_price: None` was a **display** hole: OTO close does not copy onto the parent as `stopPrice`. Snapshot now parses `descr.close` and stop-loss working sells.

No Schwab Act touch. No second XBT buy while long. ETH not sent (cash < min after fill).
