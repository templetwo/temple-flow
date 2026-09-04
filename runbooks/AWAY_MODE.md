# Away / phone mode — Temple Flow Act loop

Think (this chat / Funds-beast / the phone) is **read-only** from away.
Act is the Studio launchd daemon + `scripts/temple_flow_wire.py`.
Grok Desktop is **off the send path**.

## Phone / away rules

- **No Allow-card nags.** If a mutation needs a Mac tap, it waits until home. Do not ping Anthony to tap cards from the phone.
- **No chase through cap.** Last through the Risk cap = idea dead. Leave or cancel the working pullback. Do not replace up.
- **DAY leftovers die at 16:00.** Default order is GTC + attached stop. A DAY bid that expires is not a crisis.
- **NVO naked is the only urgent home task.** 1 NVO, no hard stop. Confirm 42.50 GTC tonight. NOK 9.45 GTC is already working.
- **Cash idle > stale replace.** Sitting in cash until a real GTC+stop can be posted at the Studio beats another stale DAY and another card.
- **Think loop is read-only from the phone.** Watch, write `config/standing_rules.json` numbers, ping on breaker / fill / naked-protect gap. Do not send.

## `--live` authorization

1. Anthony is **at the Studio**, and
2. the bracket helper is **real** (`docs/BRACKET_HELPER.md` — wired 2026-08-30).

`--live` needs **both** `config/LIVE_OK` on disk **and** `TEMPLE_FLOW_LIVE=1`.

### What `--live` on the plist actually means here

The installed plist passes `--once --live` and sets `TEMPLE_FLOW_LIVE=1` in its
own environment. That leaves exactly one switch under human control:

| `config/LIVE_OK` | What the daemon does every 900s |
| --- | --- |
| **present** | **POSTs real orders to Schwab.** Live money, unattended, no card, no prompt. |
| absent | Logs `op=refuse_live` and exits 2. It does **not** plan and does **not** dry-run. |

Two things follow, and neither was stated before:

- **On a machine where `LIVE_OK` exists, the loop is live from the moment it is
  loaded.** There is no "default dry-run" left. `rm config/LIVE_OK` is the stop
  button; unloading the job is the other one.
- **"No LIVE_OK" is not a dry-run.** `main()` returns 2 before it reaches
  `run_cycle`, so nothing is planned or logged beyond the refusal. To get a real
  planning dry-run, run `--once` **without** `--live` by hand, or remove `--live`
  from the plist.

### LIVE_OK is created by a human at the glass

`config/LIVE_OK` is git-ignored and is never created by the daemon, by a ticket,
or by any remote seat. It is created by Anthony, at the Studio, in a Terminal, in
one of two ways:

```bash
cd ~/temple-flow
touch config/LIVE_OK                   # the explicit hand gesture
./scripts/install_act_loop.sh --live-ok  # or the installer, same gate
```

Before touching it: confirm the NVO stop number, confirm nothing is enabled in
`config/standing_rules.json` (new risk goes through the outbox), then decide.
Run one attended cycle and read the JSON before you walk away:

```bash
TEMPLE_FLOW_LIVE=1 ~/spiral-broker-prod/dashboard/api/venv_new/bin/python3 \
  scripts/temple_flow_wire.py --once --live
```

Do not run `--live` from Grok Desktop. Do not run `--live` from the phone. Do not
copy Mac tokens off the Studio.

## Setup: one Studio Terminal command

```bash
cd ~/temple-flow
./scripts/install_act_loop.sh
```

The installer decides and prints the LIVE_OK state **before** it copies or loads
anything, and prints the plist `ProgramArguments` it is about to load. If
`LIVE_OK` already exists and you did not pass `--live-ok`, it **refuses**, exits
non-zero, and prints the exact `rm` command — it will not quietly arm a live
daemon on your behalf.

To install deliberately live (only at the Studio, only when ready):

```bash
./scripts/install_act_loop.sh --live-ok
```

That creates `config/LIVE_OK`, refusing if standing rules still have enabled
entries.

> **Timing note.** `--live-ok` now creates `LIVE_OK` **before** `launchctl load`,
> so that the mode the installer prints is the mode it actually loads. The plist
> sets `RunAtLoad`, which means **the first live cycle fires immediately**, not
> 900s later. Under the previous ordering the flag was created after the load, so
> the first tick refused and the first live cycle was a quarter hour away. Be at
> the glass when you pass `--live-ok`.

## Ticket outbox

One-off approved tickets go in `config/outbox/*.json`. A ticket is picked up only
when `"status": "approved"` **and** `"risk_stamped": true`. Anything else is left
in place, waiting for a human.

### Schema the code actually reads

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string, non-empty | yes | ticket identity, e.g. `TF-20260902-01` |
| `status` | string | yes | must be exactly `approved` |
| `risk_stamped` | boolean | yes | must be literal `true`, not `"true"` |
| `action` | string | yes | `place_gtc_bracket` or `cancel_by_id` |
| `symbol` | string | bracket | must be in the live universe (ETHA / IBIT) |
| `qty` | **integer** > 0 | bracket | whole shares; `5.0` and `"5"` are refused |
| `limit` | number > 0 | bracket | BUY limit |
| `stop` | number > 0 | bracket | attached child stop; must be **below** `limit` |
| `side` | string | no | defaults `BUY`; only `BUY` is accepted |
| `stop_side` | string | no | defaults `SELL`; only `SELL` is accepted |
| `order_id` | string or int | cancel | must match a **working** order in the book |
| `expires_at` | ISO string | no | optional deadline. Past it the ticket dies (`ticket_expired`). Bare stamp = ET; an offset (`...+00:00`, `...Z`) is honoured. |
| `schwab_order_id` | string | written by the daemon | its presence means "already sent, never resend" |
| `first_seen_at` | ISO string | written by the daemon | stamped ET on the **first** deferral and never rewritten. The clock `outbox.max_wait_days` measures from. |
| `deferrals` | integer | written by the daemon | rides along on that one write. `1` means "has been deferred at least once". |

Optional rules field, read from `config/standing_rules.json`:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `outbox.max_wait_days` | number | **absent** | Absent means **no limit** — Anthony's call. Set it and a ticket that has waited more than N days from `first_seen_at` dies (`ticket_wait_exceeded`). A value that will not parse is treated as absent and reported in the log as `max_wait_days_problem`; `true` counts as unparseable rather than as 1 day. A huge sentinel meaning "never expire" (`1e12`, `999999999999`) is honoured as a very long wait — it used to overflow the date arithmetic and quarantine every waiting ticket instead. |

### Guards every bracket ticket passes before a single byte is POSTed

The outbox is not a side door around the standing rules. A ticket is held to the
same gates a planned entry is. **The order below is the order the code runs, and
since 2026-09-03 the order is load-bearing** — every terminal check that needs
neither the clock nor a fresh quote runs first, so a ticket that can never pass
dies at 03:00 instead of parking overnight to be killed at the open.

1. **Wait bounds** — `expires_at` on the ticket, `outbox.max_wait_days` in the
   rules. Ahead of everything, including schema. Both **terminal**.
2. **Schema** — every field type-checked before any value is used. No `float(None)`.
3. **Read coverage: orders leg** — `orders_ok` must be proven. Every book-derived
   guard below is blind without it. **Waits.** This is the one place a waiting
   guard sits ahead of a terminal one: during a Schwab outage even a ticket for
   a symbol the daemon may never trade defers, and dies on the next healthy
   read. The alternative would be evaluating gates against a book that has not
   proven itself, which is the fail-open this guard exists to close.
4. **Universe** — `symbol` in ETHA / IBIT, never a PROTECT_ONLY leftover (NVO / NOK).
5. **No chase through cap, `limit` half** — `limit` at or under `entries[sym].cap`.
   Needs no quote, so it is checked here. The 2026-08-28 law is an idea-level
   threshold ("through cap = idea dead"), so it binds a human-approved ticket
   exactly as it binds the planner's own lane.
6. **Equity known** — live equity from the book. Both caps below need it, so an
   equity the daemon could not read **waits** rather than killing the ticket.
7. **Risk clip** — `clip_qty` recomputed from live equity; a ticket asking for
   more than the 2.5% clip allows is refused, not silently shrunk. Checked
   **before** the notional cap so an oversized ticket names the size law it
   broke rather than the buying-power one.
8. **Notional cap** — `qty * limit` must be within `risk.max_ticket_notional_pct`
   of live equity (default 0.35). This is a *different* cap from `risk_pct`:
   14 ETHA passes the $14.92 risk clip while costing $261.80 of buying power.
9. **Book** — refused if an entry, any working SELL (one-sell law), or a position
   already exists on that symbol, or if a working order already matches
   symbol+side+qty+limit (duplicate).
10. **Risk box** — day breaker, peak drawdown and max-opens all re-checked.
    A tripped box is a state of the day and the day turns over, so it **waits**.
11. **Armed** — `arm_required` honoured against the live session arm file. **Waits.**
12. **RTH** — weekday 09:00–16:00 ET, same clock the planner uses. **Waits.**
13. **Re-evaluation with fresh data** — only for a ticket carrying `validity`
    (see "Planning while the market is closed" below). Quotes proven, then
    data freshness (both **wait**), then the idea itself re-checked against a
    live quote and a fresh daily history (**terminal**,
    `idea_stale_reevaluated`). A ticket without `validity` skips this entirely
    and behaves exactly as it did before 2026-09-04.
14. **No chase through cap, `last` half** — if quotes are proven, `last` must be
    at or under the cap too. Terminal, but evaluated **last** because it is the
    one terminal check that reads a live quote: killing a ticket at 03:00 on an
    overnight print is the wrong death for a gate that means "the idea is dead
    in the session about to open". For a `validity` ticket step 13 has already
    bounded `last` more tightly, so this is the plain-ticket path.
15. **In-cycle bookkeeping** — the book is fetched once per cycle, so a placed
    order is recorded into the in-memory book immediately. Two approved tickets
    for the same symbol in one cycle result in one order: the second sees the
    first and is refused. Without this, guard 9 and the `max_opens` box would
    be blind precisely when two tickets arrive together. A **cancel** is
    recorded the same way, so the planner cannot re-fire a DELETE on an order
    the outbox just canceled in the same tick.
16. **Cancel tickets** — same shape, terminal first: the `order_id` must be a
    working order in the book (terminal), on a live-universe symbol (terminal),
    and the DELETE only fires inside RTH (**waits**).

### A degraded broker read refuses; it does not proceed on an empty book

`fetch_book` makes three independent HTTP calls. A failure on the **accounts**
call aborts the read, but a failure on **orders** or **quotes** used to leave an
empty collection behind with no signal — and every guard in the wire is
book-derived, so an orders call that 500s handed the gates an empty book and
they all passed. The book now carries `orders_ok` / `quotes_ok`, and **absence
of the flag is not permission**: any book that does not state its coverage is
treated as unproven.

| Reason you will see in the log | What it means |
|---|---|
| `protect_blocked_orders_unproven` | Orders leg failed. The protect lane will not post a stop it cannot prove is not a duplicate — that duplicate is the second SELL Schwab rejected on 2026-08-30. |
| `orders_unproven` / `quotes_unproven` (inside `new_risk_blocked`) | No new entry. Blind quotes are the fail-open direction: `last_above_hold_reclaim` and `through_cap_idea_dead` only fire when `last` is known, so a blind read would let the entry through. |
| `orders_unproven` (outbox ticket) | The ticket is held before the duplicate / one-sell / max-opens checks, which a blind book would all pass. **This one WAITS** — a failed read says nothing about the ticket, so it is re-gated when Schwab answers again. |
| `cancel_lane_orders_unproven` | Informational. An unproven orders leg yields an empty list, so the cancel lane plans nothing and no DELETE is emitted. Logged so "did nothing" and "could not see" are never confused. |
| `book_not_schwab_read` / `book_missing` | The execute boundary held: only a proven Schwab read may drive a live POST or DELETE. A hint book can never reach the wire. **For an outbox ticket these WAIT**; for a planned action they refuse, because a planned action is re-derived from scratch next cycle anyway. |
| `protect_stop_at_or_above_last_would_market_sell` | The configured stop is at or above the last trade. That is not protection, it is a market SELL on the next open. |
| `ticket_limit_above_cap` / `through_cap_idea_dead` (outbox) | The no-chase-through-cap law, split across **guard 5** (the `limit` half, checked before any quote) and **guard 13** (the `last` half, checked last because it needs a proven quote). Both terminal. |
| `cancel_symbol_not_in_live_universe` (at execute) | Boundary copy of the planner's universe restriction. |
| `ticket_expired` | The ticket's own `expires_at` has passed. Terminal. |
| `ticket_wait_exceeded` | The ticket has waited longer than `outbox.max_wait_days` from `first_seen_at` (measured as elapsed days; the log carries `waited_days`). Terminal. Only ever seen when that rules field is set. |
| `quotes_unproven` (outbox ticket) | The ticket carries `validity` and the quotes leg did not prove, or there is no `last` for the symbol. There is no re-evaluating an idea without a price. **WAITS.** |
| `data_stale_refetch_next_cycle` | The ticket carries `validity` and the price behind it is older than `validity.max_data_age_minutes` — or the book never said when it was true, which is the same thing. **WAITS.** The log carries `quote_age_minutes`. |
| `history_unproven_refetch_next_cycle` | The daily-history refetch failed, or came back with too few bars to recompute the 20/50 SMAs. A read that cannot answer is the same class as a read that failed. **WAITS.** |
| `idea_stale_reevaluated` | The re-evaluation ran and the idea is broken: `last` above `validity.max_last`, `last` above the cap, or the 20-day SMA no longer above the 50-day. **Terminal**, with `planned_last` vs `last_now` (and `sma20_now` / `sma50_now`) in the gate detail. |

**Precedence, when more than one applies:** the execute boundary checks
eligibility *first*, so a cancel on a hint book reports `book_not_schwab_read`
even for a symbol the universe check would also reject. Read it as "the book
was never trustworthy", not as "the symbol was fine".

**Expect more refusals than before, and expect them to cluster during a Schwab
hiccup.** A quiet cycle that says `protect_blocked_orders_unproven` is the guard
working, not an outage. The wire also logs an `op: "book_partial"` line naming
the HTTP status of each failed leg.

> **The hint book answers no gate it cannot answer honestly.** When the broker
> read fails entirely, `resolve_book` falls back to a book built from
> `standing_rules.json`. It used to hardcode `in_rth: true` and take `armed`
> from `armed_hint`, which meant a config file was answering two gates that
> belong to the wall clock and to the session arm file. Both keys are now
> absent: the clock and `session_armed()` answer them. A hint book is also never
> eligible for a live POST or DELETE.

### What happens to a ticket

- **Posted** → the broker `order_id` is written back into the ticket file
  *before* the file is moved, then the ticket moves to `done/`. If the move ever
  fails, the ticket still carries `schwab_order_id`, so the next cycle skips it
  instead of sending a duplicate.
- **Refused TERMINALLY** → logged with its reason and moved to `failed/`.
- **Deferred (a WAIT refusal)** → logged with its reason and **left exactly where
  it is**, in `config/outbox/`, to be re-gated next cycle.
- **Raised an exception** → logged with the exception type and moved to
  `failed/`. The cycle continues to the next ticket and then to the protect lane.
- **A broker call came back bad** → `post_failed`, `cancel_failed` and
  `cancel_refused_400_after_hours` are **outcomes, not refusal reasons**, so they
  never reach the WAIT/TERMINAL split at all: the ticket moves to `failed/`.
  **This is a live edge of "wait, don't die" and it is deliberate.** A transient
  broker 500 on a POST does kill the ticket, because a POST that may have
  partially landed must never be retried by a daemon at 03:00 — quarantining it
  for a human to read is the cheaper error. Re-approve by hand if the order did
  not in fact reach Schwab.

> ### Wait, don't die — the 2026-09-03 rule
>
> **Anthony, 2026-09-03 07:49 EDT:** *"They should wait not die. Execution should
> start back up when the markets open."*
>
> Before that directive every refusal was terminal, including timing: a ticket
> approved at 22:00 was in `failed/` by the first overnight tick and there was
> nothing left for 09:30 to run. Now a refusal has two dispositions, and which
> one it gets is a property of **why** it was refused, not of when.
>
> **WAIT — the ticket stays in `config/outbox/` and is re-gated next cycle:**
> `outside_rth`, `arm_required`, `orders_unproven`, `book_missing`,
> `book_not_schwab_read`, `equity_unknown_cannot_size`, `new_risk_blocked`,
> and the three re-evaluation reads: `quotes_unproven`,
> `data_stale_refetch_next_cycle`, `history_unproven_refetch_next_cycle`.
> Nothing about the ticket is wrong. It is well-formed, inside the universe and
> inside every cap, and the only obstacle is the clock, the arm file, a degraded
> broker read, or the risk box. A later cycle can honestly find each of these
> changed.
>
> **One caveat on `new_risk_blocked`, because "resets overnight" is true of only
> one of its three clauses.** The day breaker is day-scoped; peak-drawdown is
> not; and max-opens counts *distinct symbols* holding a position or a working
> BUY entry, so the standing NVO and NOK protect-only positions occupy two slots
> permanently. A ticket parked on max-opens or peak-DD waits **indefinitely**,
> not until midnight, and only a human clearing a position or an order releases
> it. Nothing posts while it waits, so the failure is safe — but if you are away
> and want it bounded, that is what `expires_at` / `max_wait_days` are for.
>
> **TERMINAL — the ticket moves to `failed/` immediately, at 03:00 as at 10:00:**
> everything else. Schema, a symbol outside the universe, a PROTECT_ONLY symbol,
> `limit` above cap, `through_cap_idea_dead`, a qty clipped to zero or over the
> risk clip, notional over cap or uncomputable, an existing entry, the one-sell
> law, already long, a duplicate, a cancel target that is not working, a cancel
> on a symbol outside the universe, `cancel_skipped_refused_today`,
> `rules_missing`, `ticket_unreadable`, `idea_stale_reevaluated`, an unknown
> action. Waiting on any of these is waiting forever — or, for
> `idea_stale_reevaluated`, waiting on a trade nobody has re-approved.
>
> **A waiting ticket carries no permission forward.** It is re-gated from scratch
> every cycle against a fresh book. If the world changed while it waited — a
> working entry appeared, the breaker tripped, `last` ran through the cap — it is
> refused on that, not posted because it was approved last night.
>
> **Nothing special happens at the open.** There is no resume path and no retry
> queue. The 09:45 cycle runs the same gate list the 03:00 cycle ran; the ticket
> simply still exists to be gated.
>
> **Two ways to bound the waiting**, both optional and both the human's:
> `"expires_at": "2026-09-05T16:00:00"` on the ticket, and
> `"outbox": {"max_wait_days": 3}` in `config/standing_rules.json`. Absent by
> default: with neither set, a deferred ticket waits indefinitely, which is
> Anthony's stated default. `max_wait_days` counts from `first_seen_at`, which the
> daemon stamps into the ticket file on the first deferral and **never rewrites**
> — a stamp refreshed each cycle would make the bound unfireable.
>
> **To stop a waiting ticket by hand:** move it out of `config/outbox/`, or add
> an `expires_at` in the past. Deleting it works too; the daemon holds no state
> about it anywhere else.

Example ticket (live-universe symbol, inside the caps):

```json
{
  "id": "TF-20260902-01",
  "status": "approved",
  "risk_stamped": true,
  "action": "place_gtc_bracket",
  "symbol": "ETHA",
  "qty": 5,
  "limit": 18.70,
  "stop": 17.70,
  "side": "BUY",
  "stop_side": "SELL"
}
```

## Planning while the market is closed

> **Anthony, 2026-09-03 07:49 EDT:** *"on market off hours, there should be more
> strategy being defined and planning on the trends"*
>
> **Anthony, 2026-09-03 11:47 EDT:** *"if the trade doesn't go through when it
> was supposed to go through or when it was planned, it should be reevaluate
> with updated data time sensitive data"*
>
> **Anthony, 2026-09-04 19:18 EDT:** *"Go"* — built on Schwab quotes and Schwab
> daily price history, per HQ's default data source.

**THE PLANNER NEVER PLACES AN ORDER.** It reads quotes and daily history, it
computes a small feature set, it writes one JSON file to `config/plans/`, and it
prints. It has no broker POST, no cancel, and it never writes into
`config/outbox/`. The only path from a plan to the outbox is a human running
`--approve-plan`. Read that sentence twice before changing anything in this
lane.

### The loop

```
  off-hours cycle          Anthony                execution cycle
  ---------------          -------                ---------------
  plan  ─────────►  config/plans/<date>_<time>.json
                           │
                           │  --approve-plan <plan file> <ticket id>
                           ▼
                    config/outbox/<id>.json  ──►  re-evaluated at execution
                    (approved, risk_stamped)      (validity, fresh data)
                                                  │
                                                  ├─ holds  → POST
                                                  ├─ stale read → WAIT
                                                  └─ idea broken → failed/
```

Every step is gated, and none of the gates trusts the step before it. The plan
is a proposal. The approval is a human. The execution re-decides.

### When it runs

`run_cycle` runs the planning pass **only outside RTH** (`in_rth()` false:
weekends, and weekdays before 09:00 or at/after 16:00 ET), **after** the outbox
lane and the planner lane, so it can never delay an approved ticket or a protect
stop. Inside RTH the daemon's job is to execute what a human already approved,
not to think up new trades. A planner exception is caught and logged like every
other lane; it cannot poison a cycle that already posted correctly.

### The default strategy

`scripts/temple_flow_strategy.py`, function `evaluate(symbol, features, rules)`.
**That file is the seam Grok's spec replaces** — the contract is documented at
the top of it, and the load-bearing half is this: **a strategy may only propose.
All sizing and every risk cap stay in the wire**, so a replacement strategy
cannot widen risk.

A candidate is proposed only when ALL of these hold:

| Condition | Why |
| --- | --- |
| `last` at or under `entries[sym].cap` | the 2026-08-28 no-chase law, applied at the idea stage |
| a cap is configured at all | no cap, no idea. IBIT's cap is `null` in the example rules, so IBIT proposes nothing |
| 20-day SMA **above** 50-day SMA | trend stack |
| both SMA slopes **positive** | per-day change over 5 sessions, in dollars |
| `last` at or above the 20-day SMA | continuation, not a falling knife |
| `last` no more than `max_extension_pct` (4%) above it | a bounded band; further out is a chase |
| no position and no working entry on the symbol | nothing to add to |

Prices and size:

- **limit** = `last` rounded to the cent, then floored to the cap. Never above the cap.
- **stop** = `max(entries[sym].stop, last - 2 x ATR14)`, floored to the cent. The
  rules stop is a **floor** under the ATR stop, never a ceiling on it. Refused
  if it does not land strictly below the limit.
- **qty** = the wire's own risk primitives, the same ones the outbox gate
  re-applies: `clip_qty` against `risk.risk_pct`, then the
  `risk.max_ticket_notional_pct` notional cap. On the live book that is what
  makes 11 ETHA @ 18.50 the size rather than 28.

Features recorded for every symbol, candidate or not: `sma20`, `sma50`, both
slopes, `atr14` (the **simple** 14-period mean of true range, not Wilder),
`ret5d` (from closes only, so it does not move within a session), `last_vs_cap`,
`dist_to_sma20_pct`, `bars`, plus the book state (`position_qty`,
`has_working_entry`) and both coverage flags.

Tunable in `config/standing_rules.json` under `"strategy"` — every key optional,
defaults in `temple_flow_strategy.PARAMS`: `sma_fast` 20, `sma_slow` 50,
`slope_lookback` 5, `atr_period` 14, `max_extension_pct` 0.04, `atr_stop_mult`
2.0, `max_drift_pct` 0.01, `max_data_age_minutes` 60.

**There is no `"strategy"` block in `config/standing_rules.example.json`, and
that is not an omission.** Absent means "use `PARAMS`", which is the only
source of these defaults — do not grep the example file for them and conclude
the knobs do not exist. An unparseable value falls back to its default rather
than raising, and `true` is rejected rather than read as `1`.

### The plan file

`config/plans/<YYYY-MM-DD>_<HHMM>.json`, written atomically (temp + `os.replace`
in the same directory) and git-ignored. Minute resolution: a hand-run and a
daemon tick in the same minute write the same path and the later one **wins**.
That is fine — both are read-only proposals from the same rules — but know it
rather than discover it.

```jsonc
{
  "schema": "temple_flow_plan_v1",
  "planned_at": "2026-09-03T20:00:00-04:00",     // ET ISO, the cycle's own clock
  "equity": 596.86,
  "in_rth": false,
  "book_source": "schwab_read",
  "strategy_module": "temple_flow_strategy",
  "strategy_params": { "sma_fast": 20, "...": "..." },
  "coverage": {                                   // stated, never inferred
    "quotes_ok": true,
    "orders_ok": true,
    "history_ok": { "ETHA": true, "IBIT": true }
  },
  "data_as_of": {                                 // what the numbers were true of
    "quotes": "2026-09-03T20:00:00-04:00",
    "history": { "ETHA": "2026-09-03T20:00:01-04:00" }
  },
  "risk_box": { "ok": true, "reasons": [], "opens": 2 },
  "symbols": {
    "ETHA": {
      "decision": "candidate",                    // or "none"
      "reason": "strategy_candidate",             // or why there is none
      "features": { "...": "..." },
      "checks":   { "...": true },                // every named condition
      "sizing":   { "qty": 11, "risk_dollars": 5.72, "notional": 203.5 },
      "rationale": "ETHA: sma20 ... > sma50 ..., both rising ...",
      "ticket": {                                 // READY TO APPROVE, INERT
        "id": "TF-PLAN-20260903-2000-ETHA",
        "status": "proposed",                     // NOT "approved"
        "risk_stamped": false,                    // NOT true
        "action": "place_gtc_bracket",
        "symbol": "ETHA", "side": "BUY", "stop_side": "SELL",
        "qty": 11, "limit": 18.50, "stop": 17.98,
        "planned_at": "2026-09-03T20:00:00-04:00",
        "source_plan": "2026-09-03_2000.json",
        "validity": { "...": "..." }              // see below
      }
    },
    "IBIT": { "decision": "none", "reason": "strategy_declined",
              "failed_checks": ["cap_known", "last_at_or_under_cap"],
              "ticket": null }
  },
  "candidates": ["TF-PLAN-20260903-2000-ETHA"]
}
```

The ticket is written in the **exact outbox dialect the loader reads**, with the
two fields that keep it inert: `status: "proposed"` and `risk_stamped: false`.
Dropped into `config/outbox/` unchanged it is ignored, because the loader wants
`approved` + `true`.

**Reasons a symbol produces no candidate**, and they are not interchangeable:

| `reason` | Means |
| --- | --- |
| `quotes_unproven` | the quotes leg failed, or there is no `last` for the symbol. No history is even fetched. |
| `history_unproven` | the daily-history call failed. `coverage.history_ok[sym]` is `false`; the note carries the HTTP status. |
| `insufficient_history` | the call **succeeded** and returned fewer than 55 bars (50 for the slow SMA + 5 for its slope). A different fact from `history_unproven` — never merge them. |
| `strategy_declined` | the strategy said no. `failed_checks` names every condition that did not hold. |
| `qty_clipped_to_zero` / `stop_not_below_limit` / `notional_cap_uncomputable` / `equity_unknown` | the idea was fine and the wire could not size it. |

### Housekeeping, stated rather than discovered

Two costs of this lane, both small and both yours to bound if you want them
bounded:

- **Plan files accumulate.** The daemon ticks every 900s around the clock, so a
  weeknight writes roughly 60 plan files and a weekend writes several hundred.
  They are git-ignored and a few KB each. Nothing prunes them, on purpose — a
  daemon that deletes files on a money-adjacent repo is a bigger risk than a
  directory that grows. `rm config/plans/*.json` by hand whenever you like; the
  wire holds no state about them, and an approved ticket carries everything it
  needs in its own file.
- **Two extra Schwab reads per off-hours cycle**, one `pricehistory` call per
  live-universe symbol. Read-only, and skipped entirely when the quotes leg did
  not prove.

### Approving a plan — the only door

```bash
cd ~/temple-flow
scripts/temple_flow_wire.py --approve-plan config/plans/2026-09-03_2000.json TF-PLAN-20260903-2000-ETHA
```

Offline. No broker call, no book resolved, no `LIVE_OK`, no `TEMPLE_FLOW_LIVE`.
Safe to run from any Terminal at any hour. It copies that one candidate to
`config/outbox/<id>.json` with `status: "approved"`, `risk_stamped: true` and a
`human_approved_at` ET stamp, and prints one `op=approve_plan` line. Exit 0 on
success, 2 on any refusal.

**`risk_stamped: true` is a loader precondition, not a risk waiver.** The outbox
is not a side door around the standing rules and this new door is not either:
every gate in the list above still runs on a fresh book, and the `validity` block
re-decides the idea at execution.

It **refuses** (exit 2, nothing written) when:

- the plan file is unreadable, or the id is not a **candidate** in that plan;
- the ticket's `validity` does not state `max_data_age_minutes`. No window is
  invented on a money path;
- **the plan is stale**: older than `max_data_age_minutes` x 24. With the default
  60 minutes that is a **24-hour approval window** — plan overnight, approve in
  the morning. Past it the plan is **regenerated, not approved**: its prices, its
  trend and its ATR were true of a market that has moved on;
- the plan is stamped in the future (clock skew or a hand-edited file);
- `config/outbox/<id>.json` already exists. It never clobbers a ticket that may
  already be waiting or stamped.

### The `validity` contract — re-evaluation at execution

Every planned ticket carries a `validity` object. It is the idea's **falsifier**,
carried in the ticket file, and it runs inside `gate_outbox_ticket` at the moment
of execution — which for an overnight plan is hours after a human approved it.

```json
"validity": {
  "max_last": 18.68,
  "min_sma20_over_sma50": true,
  "max_data_age_minutes": 60.0,
  "planned_last": 18.50,
  "planned_atr": 0.26,
  "rationale": "ETHA: sma20 ... > sma50 ..., both rising ..."
}
```

| Field | Checked how |
| --- | --- |
| `max_data_age_minutes` | the **older** of two clocks: when the daemon read the quotes leg (`quotes_as_of`) and Schwab's own `quoteTime`/`tradeTime` for that symbol. Older than this, or unknowable, and the ticket **waits**. |
| `max_last` | fresh `last` must be at or under it. Floored to the cent from `planned_last x (1 + max_drift_pct)`, capped by the entry cap. Over it and the ticket is **terminal**. |
| `min_sma20_over_sma50` | when true, the daily history is **refetched** and the 20/50 SMAs recomputed. A failed or too-thin refetch **waits**; a flipped trend is **terminal**. |
| `planned_last` / `planned_atr` / `rationale` | carried for the log and for a human reading `failed/`. The gate detail prints planned vs now side by side. |

**Why the read failures wait and the verdict dies.** A failed read says nothing
about the idea, so it is re-gated next cycle — that is the 2026-09-03 "wait,
don't die" rule unchanged. A failed **condition** says the market moved past the
trade Anthony approved, and re-approving that is a human decision with fresh
eyes, not a daemon's at 09:31.

**Why the two freshness clocks.** The book is fetched once per cycle and handed
straight to the gate, so the read stamp is always about zero minutes old and a
gate built on it alone could never fire. Schwab's own quote time is what catches
a halted symbol, a frozen feed or a pre-market read — the case Anthony's "time
sensitive data" actually names. A gate that cannot fail is not a gate.

**A ticket with no `validity` behaves exactly as it did before 2026-09-04.** The
hand-written example ticket above still works, unchanged, and no history is
fetched for it.

## What the daemon will do while you are away

- Plan GTC ETHA pullback + attached stop when armed, under cap, inside 2.5% / 4 opens / breakers.
- Plan NVO/NOK protect stops. Never add to leftovers.
- Plan cancel/abandon if last or working limit is through the cap. Never reprice up.
  Cancels are restricted to the live universe, fire only inside RTH, and a
  Schwab 400 is remembered in `config/cancel_refusals.json` so the same order is
  not re-DELETEd every tick — one attempt per trading day.
- Process outbox tickets under the guards above. A ticket refused for a timing
  or transient-state reason **stays in `config/outbox/`** and is re-gated every
  900s until it posts, dies on a terminal gate, or hits a bound you set.
- **Outside RTH only:** run the read-only planning pass over ETHA / IBIT and
  write `config/plans/<date>_<time>.json`. It proposes; it never places, and it
  never writes to `config/outbox/`. Approving is Anthony's, by hand, with
  `--approve-plan`.
- Re-evaluate any approved ticket carrying `validity` against fresh quotes and a
  fresh daily history at the moment of execution. Stale data waits; a broken
  idea dies.
- Print JSON lines. `sent` means an order was **placed**; a cancel reports
  `execute: "canceled"` with `mutated: true` and leaves `sent` false.
