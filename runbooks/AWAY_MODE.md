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
2. the bracket helper is **real** (`docs/BRACKET_HELPER.md` — ✅ wired as of 2026-08-30).

`--live` also needs `config/LIVE_OK` **and** `TEMPLE_FLOW_LIVE=1`. **The launchd plist may pass `--live`**; the human gate is `config/LIVE_OK` on disk. Default without `LIVE_OK` remains dry-run.

Do not run `--live` from Grok Desktop. Do not run `--live` from the phone. Do not copy Mac tokens off the Studio.

## Setup: one Studio Terminal command

Use the installer script:

```bash
cd ~/temple-flow
./scripts/install_act_loop.sh
```

This will:
1. Copy/bootstrap the plist into `~/Library/LaunchAgents`
2. `launchctl unload/load` the daemon
3. Create outbox directories
4. Print the log path

To enable live trading (only at Studio, only when ready):

```bash
cd ~/temple-flow
./scripts/install_act_loop.sh --live-ok
```

This creates `config/LIVE_OK` (refuses if standing rules have enabled entries).

## Ticket outbox

One-off approved tickets go in `config/outbox/*.json`:
- Must have `"status": "approved"` and `"risk_stamped": true`
- Must include explicit human-approved qty/limit/stop
- After send or reject, moved to `done/` or `failed/` folder
- Never re-sends if `schwab_order_id` is already WORKING

Example ticket:
```json
{
  "id": "TF-20260831-01",
  "status": "approved",
  "risk_stamped": true,
  "action": "place_gtc_bracket",
  "symbol": "SOFI",
  "qty": 10,
  "limit": 8.50,
  "stop": 8.20,
  "side": "BUY",
  "stop_side": "SELL"
}
```

## What the daemon will do while you are away

- Plan GTC ETHA pullback + attached stop when armed, under cap, inside 2.5% / 4 opens / breakers.
- Plan NVO/NOK protect stops. Never add to leftovers.
- Plan cancel/abandon if last or working limit is through the cap. Never reprice up.
- Process outbox tickets (if LIVE_OK set).
- Print JSON lines. `sent` stays false in dry-run; true when LIVE_OK exists and order POSTs succeed.
