# Eyes: a look at the market that does not need Schwab

`scripts/temple_flow_eyes.py` is an on-demand, read-only market data tool backed by
Twelve Data. It exists because every price the Act loop sees comes from Schwab: when the
Schwab login lapses, the desk has no quotes, no history and no plan. The eyes keep working.

**It is a tool you call, not a process that runs.** There is no daemon, no schedule and no
polling. No credit is spent unless an agent or a person asks for a look.

## The line that does not move

The eyes are **evidence only**. They are never an execution data source.

- `book_is_live_eligible` in the wire only lets a proven Schwab read drive a POST or DELETE.
  The eyes do not change that and cannot satisfy it: `book["source"] == "schwab_read"` is
  set only inside the wire, after a live Schwab read.
- The script does not import the wire, names no host except `api.twelvedata.com`, only
  issues GET requests, and writes nowhere except its own cache directory. The cache may
  not be placed under `config/`, `logs/` or any other directory the wire or a person reads.
- `scripts/test_temple_flow_eyes.py` checks that by reading the source. Some checks are
  whitelists, where anything not named fails: imports (including aliases and
  `from ... import`), `os` attributes, `urllib` attributes, and the exact `Class.method`
  names allowed to write a file. The rest are pattern checks: banned builtins, reflection
  on `os`/`sys`/`urllib`, the exact shape of `Request(...)` and `urlopen(...)`, changing a
  request after building it, and URL-like strings other than Twelve Data's. A second test
  appends 28 hostile edits (shelling out, aliased `os`, a lazy import of the wire, a POST
  body, an impostor `_write`, a write into the outbox) and proves each one trips it.
  A pattern check passes whatever nobody thought of, so this is a guard against the file
  drifting toward having hands. It is not a proof against someone determined to hide
  them; review still matters.
- Every answer is stamped `"evidence_only": true` and `"not_for_execution": true`.
- Sizing comes from live Schwab equity, never from the eyes. The eyes cannot see the
  account: positions, orders, fills, cash and equity are Schwab-only facts.
- The eyes write nothing to the SQLite store. `docs/DATA_CONVENTIONS.md` still lists
  Kraken, Coinbase and Yahoo as the approved sources for `bars_daily`; adding Twelve Data
  there is a human amendment, not something this tool assumes.

## When to reach for it

- Schwab auth is down and the desk needs to know where ETHA, IBIT, NVO and NOK are.
- A morning brief or watch needs prices and trend without touching the broker.
- You want to know how far a protect-only leftover is from its stop.
- You want a second opinion on a Schwab quote that looks wrong.

If Schwab is up and you are inside the Act loop, the Schwab read remains the authority.

## Commands

Output is one JSON document on stdout, always, unless `--text` is given. Even an internal
error comes back as JSON, never a traceback.

```
python3 scripts/temple_flow_eyes.py look                 # ETHA IBIT NVO NOK
python3 scripts/temple_flow_eyes.py look --with-crypto   # plus BTC-USD and ETH-USD
python3 scripts/temple_flow_eyes.py look --text          # short human brief
python3 scripts/temple_flow_eyes.py quote IBIT BTC-USD   # prices only
python3 scripts/temple_flow_eyes.py history ETHA --days 260
python3 scripts/temple_flow_eyes.py budget               # free: credits used and left
python3 scripts/temple_flow_eyes.py status               # free: config, key present or not
```

Flags on `look`, `quote` and `history`:

| Flag | Meaning |
| --- | --- |
| `--max-age S` | accept cached quotes up to `S` seconds old (default 120). A quote served from a cache entry older than 15 minutes is marked `stale` whatever `S` says |
| `--no-cache` | always fetch; costs credits |
| `--wait` | if the minute budget defers part of the answer, sleep and finish it (at most three rounds; never waits on the day budget) |

`look` also takes `--symbols`, `--rules PATH` (default `config/standing_rules.json`) and
`--snapshots DIR` (default `logs/snapshots`). `history --days` is capped at 4999.

Crypto uses the desk's labels (`BTC-USD`); the tool maps them to Twelve Data's (`BTC/USD`).

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | complete answer |
| 2 | no API key available and the cache could not answer |
| 3 | partial answer. Either the budget deferred something (read `deferred`, it says when to retry) or a symbol failed (read its `reason`). Whatever did come back is valid |
| 4 | internal error; the JSON carries `"reason": "internal_error"` and the exception type |
| 5 | bad command line; the JSON carries `"reason": "usage_error"`. Deliberately not argparse's usual 2, which here means "no key" |

## What `look` returns

Per symbol:

- `quote`: `last`, `previous_close`, `change_pct`, `market_state` (`open`, `closed` or
  `unknown`), `quote_time` (epoch seconds of the last print), `quote_age_s`, `stale`,
  `venue`, `from_cache`, `cache_age_s`, `fetched_at`.
- `features`: the planner's own names and arithmetic, `sma20`, `sma50`,
  `sma20_above_sma50`, `sma20_slope`, `sma50_slope`, `atr14`, `ret5d`,
  `dist_to_sma20_pct`, plus `atr_60d_avg`, `atr_ratio` and `atr_filter` (true above 1.8x).
  A value that cannot be computed is `null`, never a guess.
- `levels`: `protect_stop`, `dist_to_protect_stop_pct`, `at_or_below_protect_stop`,
  `entry_limit`, `entry_stop`, `entry_cap`, `above_entry_cap`, read from the human-written
  `config/standing_rules.json` when this machine has it. The example file is never read.
- `history`: a summary (`bars`, `last_bar_at`, `history_ok`, `fetched_at`). Use the
  `history` command for the candles themselves; they come back oldest first in the same
  shape as the wire's `fetch_daily_history`.

Top level:

- `as_of` is when the question was asked. When the data is from is on each symbol:
  `fetched_at`, `quote_age_s`, `last_bar_at`.
- `alerts`: `quote_unavailable`, `quote_stale`, `market_closed_last_session_price`,
  `history_unavailable`, `atr_filter`, `at_or_below_protect_stop`, `above_entry_cap`.
- `book_snapshot`: the newest readable file in `logs/snapshots/`, marked to the eyes'
  prices. It is **always** `"stale": true`. It is what the desk last remembered, not what
  the account holds now. Orders may have filled since.
- `deferred`: what the budget would not allow this minute, with `retry_after_s`.
- `credits`: `spent_this_call`, minute and day usage, and Twelve Data's own count when it
  sends one.

### Reading freshness honestly

- **Open or unknown market:** a last print older than 15 minutes is `stale`. A quote with
  no timestamp is `stale`: unmeasured is not fresh. An unknown market state is held to the
  open-market standard.
- **Closed market:** the price is the last session's. It is labelled
  `market_state: "closed"` and raises `market_closed_last_session_price`, so nobody
  repeats Friday's close on Monday morning as if it were live. It only becomes `stale`
  after five days, which is longer than any holiday weekend.
- **Before you quote a price to a person, say its age and its market state.**

### Finished bars only

Features use finished daily bars. A bar still forming (an equity bar dated today before
16:20 ET; a crypto bar for the current UTC day) is set aside under `history.partial_bar`,
so the numbers can be re-derived later from the same candles. The cutoff is 16:20 and not
the bell because the provider's daily bar is provisional for the first minutes after
16:00. Cached history is dropped at the next session boundary (16:20 ET on a weekday;
00:00 UTC for crypto), so the bar that was unfinished at 15:00 is fetched again, finished,
after the close rather than missing for the rest of the evening. A market holiday costs
one extra fetch per symbol, not a refetch on every call.

### Two things the eyes do differently from the planner

- **Number parsing is stricter.** The wire's `_f` lets `True`, `"NaN"` and `"inf"` through
  as `1.0`, `nan` and `inf`. The eyes turn them into `null` and drop the bar, because text
  from a data vendor is less trusted than a broker field and one bad close should not turn
  a moving average into NaN. On every finite number the two agree, and the suite proves
  `sma`, `sma_slope`, `atr`, `window_return` and `closes_of` match the wire's on the same
  candles.
- **`atr_filter` is the eyes' reading of the constitution**, "14-period ATR > 1.8x 60-day
  average ATR", computed as the mean of the last 60 daily ATR14 values. Nothing else in
  this repo computes it, so treat it as a prompt to look, not as the Risk Manager's
  verdict. It needs 74 finished bars and is `null` below that.

## Budget: why this cannot burn the plan

Twelve Data's Basic plan allows 8 credits a minute and 800 a day. One symbol costs one
credit per `quote` or `history`.

- **Atomic ledger.** Spend is recorded in `data/cache/eyes/ledger.json`. Reading the
  balance, deciding what fits and charging it happen inside one file lock, before the
  request leaves, so two agents calling at the same instant cannot both be granted the
  same credit. The suite forks four processes at once, eight times over, and checks that
  exactly 8 credits are granted between them each time. It also runs the same race
  against a deliberately non-atomic ledger and requires that one to overrun, so the test
  is known to catch the bug it guards against.
- **No meter, no spend.** If the ledger cannot be written, nothing is fetched; the symbols
  come back with `"reason": "ledger_unavailable"`.
- **Day budget is 400 by default**, half the plan, because the Tape apps share the key.
  Set `TWELVE_DATA_DAY_BUDGET` to change it. `0` means spend nothing. Values above 800 are
  clamped to 800; nonsense falls back to 400.
- **Shared key.** When Twelve Data reports a higher per-minute count than the ledger holds
  (another app spent credits), the ledger tightens to match. It never loosens.
- **Cache.** Quotes are reused for 120 seconds and daily history for up to 6 hours within
  a session. A cold `look` at the four desk names costs 8 credits and fits one minute
  when nobody else has spent in that minute; a warm one costs 4; a repeat inside two
  minutes costs 0.
- **Prices first.** When the minute is short, `look` buys quotes before history.
- **Rate limited anyway?** A 429 closes the minute locally so the next caller waits too.
- **Corrupt ledger?** It is quarantined beside itself (`ledger.json.corrupt-<time>`). The
  new ledger treats the current minute as spent and keeps whatever spend could still be
  read out of the damaged file. If nothing could be read, it assumes half the day's
  budget is gone: a lost counter must not read as an untouched budget.

This ledger meters one machine. Two machines with the same key meter separately; the
provider's own count, read back on every response, is what ties them together.

## Setup

1. Put the key in the environment, or in a git-ignored `.env` at the repo root:

   ```
   TWELVE_DATA_API_KEY=...
   ```

   The tool also looks in the file named by `TEMPLE_FLOW_ENV_FILE` and in
   `$SPIRAL_BROKER_ROOT/.env`, reading only its own variable from them. A key containing
   whitespace or control characters is rejected as missing.
2. `python3 scripts/temple_flow_eyes.py status` should say `"key_present": true`.
3. `python3 scripts/temple_flow_eyes.py look --text`

The key is sent as an `Authorization` header. It is never placed in a URL, printed,
logged or cached, and error text that echoes it (plain, URL-encoded or escaped) is
redacted. This repo is public: never commit a `.env`.

Standard library only; Python 3.10+. It needs the system time zone database for
`America/New_York` (present on macOS and ordinary Linux; on a minimal container,
`pip install tzdata`). No Schwab login, no broker repo and no `requests` are needed, so it
runs on the Studio, the Grok Bot box or a laptop alike.

`TEMPLE_FLOW_EYES_CACHE` moves the cache. It is refused if it points inside `config/`,
`logs/`, `scripts/`, `docs/` or the other directories the wire or people read.

## Reasons you will see

| `reason` | Meaning |
| --- | --- |
| `no_api_key` | no usable key on this machine and nothing fresh in the cache |
| `minute_budget` / `day_budget` | deferred by the ledger; see `retry_after_s` |
| `ledger_unavailable` | the ledger could not be written, so nothing was spent |
| `rate_limited` | Twelve Data returned 429; the minute is closed locally |
| `provider_error` | Twelve Data refused (bad symbol, bad key, plan does not cover it) |
| `bad_payload` | the response had no usable price or no usable bars; it is not cached |
| `network_error` | the request did not complete; the credit is still counted |
| `internal_error` | a bug; exit code 4, with the exception type |

Indices and commodities (VIX, DXY, US10Y) are not part of the Basic plan; expect
`provider_error` for them until the plan changes.

## Tests

```
python3 scripts/test_temple_flow_eyes.py
```

No network: every test that drives the tool injects its transport and clock, and those
test classes arm a tripwire that fails the test if it reaches the real internet. Two tests
fork real processes to race the ledger.
