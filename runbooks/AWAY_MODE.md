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

## `--live` is not authorized until

1. Anthony is **at the Studio**, and
2. the bracket helper is **real** (`docs/BRACKET_HELPER.md` — today it is a refuse stub).

`--live` also needs `config/LIVE_OK` **and** `TEMPLE_FLOW_LIVE=1`. The launchd plist must never pass `--live`.

Do not run `--live` from Grok Desktop. Do not run `--live` from the phone. Do not copy Mac tokens off the Studio.

## Tonight, once (home, Studio Terminal)

1. Copy `config/standing_rules.example.json` → `config/standing_rules.json`.
2. Confirm the NVO stop (example is 42.50 GTC). Edit the JSON if the number is wrong.
3. Dry-run:
   ```bash
   cd ~/temple-flow
   ~/spiral-broker-prod/dashboard/api/venv_new/bin/python3 scripts/temple_flow_wire.py --status
   ~/spiral-broker-prod/dashboard/api/venv_new/bin/python3 scripts/temple_flow_wire.py --once
   ```
4. One home Terminal `--once --live` **or skip**. Skip unless the bracket helper is implemented and you are at the glass. Prefer skip over Grok Desktop.
   ```bash
   # only if helper is real AND you are at the Studio
   touch config/LIVE_OK
   TEMPLE_FLOW_LIVE=1 ~/spiral-broker-prod/dashboard/api/venv_new/bin/python3 \
     scripts/temple_flow_wire.py --once --live
   ```
5. Load launchd (dry-run `--once`, no `--live`):
   ```bash
   mkdir -p ~/Library/Logs
   cp deploy/com.templetwo.temple-flow-wire.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.templetwo.temple-flow-wire.plist
   # logs: ~/Library/Logs/temple-flow-wire.log
   ```
6. `arm MV session` if entries are wanted tomorrow. Then leave.

## What the daemon will do while you are away (dry-run today)

- Plan GTC ETHA pullback + attached stop when armed, under cap, inside 2.5% / 4 opens / breakers.
- Plan NVO/NOK protect stops. Never add to leftovers.
- Plan cancel/abandon if last or working limit is through the cap. Never reprice up.
- Print JSON lines. `sent` stays false until the helper exists and a human `--live` at the Studio actually posts.
