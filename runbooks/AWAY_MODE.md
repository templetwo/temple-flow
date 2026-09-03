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
| `outbox.max_wait_days` | number | **absent** | Absent means **no limit** — Anthony's call. Set it and a ticket that has waited more than N days from `first_seen_at` dies (`ticket_wait_exceeded`). A value that will not parse is treated as absent and reported in the log as `max_wait_days_problem`. |

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
13. **No chase through cap, `last` half** — if quotes are proven, `last` must be
    at or under the cap too. Terminal, but evaluated **last** because it is the
    one terminal check that reads a live quote: killing a ticket at 03:00 on an
    overnight print is the wrong death for a gate that means "the idea is dead
    in the session about to open".
14. **In-cycle bookkeeping** — the book is fetched once per cycle, so a placed
    order is recorded into the in-memory book immediately. Two approved tickets
    for the same symbol in one cycle result in one order: the second sees the
    first and is refused. Without this, guard 9 and the `max_opens` box would
    be blind precisely when two tickets arrive together. A **cancel** is
    recorded the same way, so the planner cannot re-fire a DELETE on an order
    the outbox just canceled in the same tick.
15. **Cancel tickets** — same shape, terminal first: the `order_id` must be a
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
| `ticket_limit_above_cap` / `through_cap_idea_dead` (outbox) | Guard 11 above. |
| `cancel_symbol_not_in_live_universe` (at execute) | Boundary copy of the planner's universe restriction. |
| `ticket_expired` | The ticket's own `expires_at` has passed. Terminal. |
| `ticket_wait_exceeded` | `first_seen_at` + `outbox.max_wait_days` is behind us. Terminal. Only ever seen when that rules field is set. |

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
> `book_not_schwab_read`, `equity_unknown_cannot_size`, `new_risk_blocked`.
> Nothing about the ticket is wrong. It is well-formed, inside the universe and
> inside every cap, and the only obstacle is the clock, the arm file, a degraded
> broker read, or a daily box that resets. A later cycle can honestly find each
> of these changed.
>
> **TERMINAL — the ticket moves to `failed/` immediately, at 03:00 as at 10:00:**
> everything else. Schema, a symbol outside the universe, a PROTECT_ONLY symbol,
> `limit` above cap, `through_cap_idea_dead`, a qty clipped to zero or over the
> risk clip, notional over cap or uncomputable, an existing entry, the one-sell
> law, already long, a duplicate, a cancel target that is not working, a cancel
> on a symbol outside the universe, `cancel_skipped_refused_today`,
> `rules_missing`, `ticket_unreadable`, an unknown action. Waiting on any of
> these is waiting forever.
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
- Print JSON lines. `sent` means an order was **placed**; a cancel reports
  `execute: "canceled"` with `mutated: true` and leaves `sent` false.
