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
