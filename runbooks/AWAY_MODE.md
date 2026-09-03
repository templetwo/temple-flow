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
| `schwab_order_id` | string | written by the daemon | its presence means "already sent, never resend" |

### Guards every bracket ticket passes before a single byte is POSTed

The outbox is not a side door around the standing rules. A ticket is held to the
same gates a planned entry is:

1. **Schema** — every field type-checked before any value is used. No `float(None)`.
2. **Universe** — `symbol` in ETHA / IBIT, never a PROTECT_ONLY leftover (NVO / NOK).
3. **Armed** — `arm_required` honoured against the live session arm file.
4. **RTH** — weekday 09:00–16:00 ET, same clock the planner uses.
5. **Risk box** — day breaker, peak drawdown and max-opens all re-checked.
6. **Risk clip** — `clip_qty` recomputed from live equity; a ticket asking for
   more than the 2.5% clip allows is refused, not silently shrunk.
7. **Notional cap** — `qty * limit` must be within `risk.max_ticket_notional_pct`
   of live equity (default 0.35). This is a *different* cap from `risk_pct`:
   14 ETHA passes the $14.92 risk clip while costing $261.80 of buying power.
8. **Book** — refused if an entry, any working SELL (one-sell law), or a position
   already exists on that symbol, or if a working order already matches
   symbol+side+qty+limit (duplicate).
9. **Cancel tickets** — the `order_id` must be a working order in the book, on a
   live-universe symbol, and the DELETE only fires inside RTH.
10. **In-cycle bookkeeping** — the book is fetched once per cycle, so a placed
    order is recorded into the in-memory book immediately. Two approved tickets
    for the same symbol in one cycle result in one order: the second sees the
    first and is refused. Without this, guards 8 and the `max_opens` box would
    be blind precisely when two tickets arrive together. A **cancel** is
    recorded the same way, so the planner cannot re-fire a DELETE on an order
    the outbox just canceled in the same tick.
11. **No chase through cap** — `limit` must be at or under `entries[sym].cap`,
    and if quotes are proven, `last` must be too. The 2026-08-28 law is an
    idea-level threshold ("through cap = idea dead"), so it binds a
    human-approved ticket exactly as it binds the planner's own lane.
12. **Read coverage** — see below. Every guard from 5 to 11 is book-derived, so
    a ticket is refused outright when the leg it depends on is unproven.

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
| `orders_unproven` (outbox ticket) | The ticket is refused before the duplicate / one-sell / max-opens checks, which a blind book would all pass. |
| `cancel_lane_orders_unproven` | Informational. An unproven orders leg yields an empty list, so the cancel lane plans nothing and no DELETE is emitted. Logged so "did nothing" and "could not see" are never confused. |
| `book_not_schwab_read` / `book_missing` | The execute boundary refused: only a proven Schwab read may drive a live POST or DELETE. A hint book can never reach the wire. |
| `protect_stop_at_or_above_last_would_market_sell` | The configured stop is at or above the last trade. That is not protection, it is a market SELL on the next open. |
| `ticket_limit_above_cap` / `through_cap_idea_dead` (outbox) | Guard 11 above. |
| `cancel_symbol_not_in_live_universe` (at execute) | Boundary copy of the planner's universe restriction. |

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
- **Refused, for any reason** → logged with its reason and moved to `failed/`.
- **Raised an exception** → logged with the exception type and moved to
  `failed/`. The cycle continues to the next ticket and then to the protect lane.

> **Refusal is terminal, including for timing.** A ticket refused because it was
> outside RTH, or because the session was not armed, is quarantined to `failed/`
> the same as a malformed one. It is **not** parked and retried when the market
> opens. This is deliberate — a ticket that sits in the outbox retrying itself is
> a standing order nobody re-approved — but it means **a ticket dropped in
> overnight will be dead by morning.** Move it back out of `failed/` and re-approve
> it when you are at the glass.
>
> **OPEN QUESTION, for Anthony, not for a seat to decide.** The read-coverage
> refusals below make this cost bigger: a Schwab hiccup now quarantines tickets
> that were never wrong, only unproven. A third outcome — `deferred/`, left in
> the outbox for refusals that are purely about timing or coverage — would fix
> it. It is deliberately **not built here**: it is a new state machine on a live
> wire, and "retry it later automatically" is exactly the property the terminal
> rule was chosen to avoid. Decide the policy first.

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
- Process outbox tickets under the guards above.
- Print JSON lines. `sent` means an order was **placed**; a cancel reports
  `execute: "canceled"` with `mutated: true` and leaves `sent` false.
