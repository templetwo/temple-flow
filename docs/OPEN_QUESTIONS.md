# Open questions (blocked on Anthony)

These do **not** block schema/runbook work, but they block real backfill and live trading.

1. **Universe:** which symbols for Day-1 backfill? (e.g. SPY/QQQ only vs broader goldbrick set)
2. **Data sources:** path or access to goldbrick + spiral-broker stores; or approved public substitutes
3. **Lookback:** how many years daily? intraday needed Day-1?
4. **Schwab:** app client id + exact localhost callback (after GitHub push)
5. **Live switch:** explicit human command to leave shadow

Until answered, desk stays **shadow**, Data & Backfill prepares schema only, no invented series.
