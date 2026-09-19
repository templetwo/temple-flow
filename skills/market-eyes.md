# Skill: Market Eyes (Schwab-independent look)

**When to use:** Schwab auth is down, or you need prices and trend without touching the
broker. Call it when you need to look. Never run it on a loop or a schedule.

**Command:** `python3 scripts/temple_flow_eyes.py look` (add `--with-crypto` for BTC-USD and
ETH-USD, `--text` for a short brief). `budget` and `status` are free.

## Sequence
1. Run `look`. Exit 0 = complete. Exit 3 = partial: `deferred` lists what the budget held
   back and when to retry, and a symbol's `reason` says why it failed; the rest is valid.
   Exit 2 = no API key here. Exit 4 = internal error. Exit 5 = you typed the command
   wrong. All of them still print JSON.
2. Read `alerts` first, then each symbol's `quote`, `features` and `levels`.
3. Before quoting a price to anyone, read `quote.market_state`, `quote_age_s` and `stale`.
   A `closed` market means the price is the last session's: say so.
4. Treat `book_snapshot` as memory, not sight. It is always stale.
5. State the source in anything you write: "Twelve Data via eyes, evidence only".

## Output
Prices, the planner's SMA20/50, slopes, ATR14, the eyes' reading of the 1.8x ATR filter,
distance to protect stops and entry caps, and credits spent.

## Never-do
- Never size, approve, or send from eyes data. Size comes from live Schwab equity only.
- Never treat an eyes quote as the proven quote an outbox ticket needs.
- Never call it repeatedly to watch a price. Repeats inside 120 seconds are free; beyond
  that each symbol costs a credit from a budget shared with other apps.
- Never print, log or commit the API key.

Full reference: `runbooks/EYES.md`.
