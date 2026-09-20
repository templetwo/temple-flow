# WP0 local inventory — MacBook checkout

**Seat:** MacBook Pro, grok-4.6, session 01a0bf46. **Not HQ / not Studio.**
**Checkout:** `/Users/vaquez/temple-flow` at inspection `a5aa41b337c5f7522770225fb9a74121a1150283` (`main`), then branch `feat/campaign-v2-wp0-wp2`.
**Date:** 2026-09-20. No credentials opened. No launchd started or stopped. No live orders sent.

## What is effective vs merely present

| Surface | Present in this clone | Effective on this MacBook | Effective on Studio (this seat) |
|---|---|---|---|
| `scripts/temple_flow_wire.py` | yes | not running | **UNKNOWN** — checked-in plist targets `/Users/tony_studio/temple-flow` |
| `deploy/com.templetwo.temple-flow-wire.plist` | `--once --live` every 900s, `TEMPLE_FLOW_LIVE=1` | **not loaded here** (`launchctl` has no `temple-flow` job) | **UNKNOWN** — plist is not proof of the installed job |
| `config/LIVE_OK` | absent (gitignored) | absent | **UNKNOWN** (not inspected; Studio-only) |
| `config/standing_rules.json` | absent | example only | **UNKNOWN** |
| `config/standing_rules.example.json` | yes; `max_opens: 4`, entries disabled | example, not live | n/a |
| `scripts/send_tf_20260830.py` | one-off send helper | not invoked | do not run |
| `scripts/install_act_loop.sh` | creates LIVE_OK only with `--live-ok` | not invoked | do not run |
| `scripts/temple_flow_eyes.py` | evidence-only | not invoked against a live key | keep evidence-only |
| `~/spiral-broker` on this laptop | present | not used by v2 paper path | tokens not read |

## Mutation entry points (leave legacy writers alone)

1. `scripts/temple_flow_wire.py` `--live` (gated by LIVE_OK + `TEMPLE_FLOW_LIVE=1`)
2. launchd `com.templetwo.temple-flow-wire` (Studio paths in the checked-in plist)
3. `scripts/send_tf_20260830.py`
4. `place_gtc_bracket` / `cancel_by_id` inside the wire (R9: helper can bypass planner one-sell)

v2 paper path is `scripts/temple_flow_desk.py` + `src/temple_flow/` with an isolated `--state` directory. It does not import the wire.

## Env names (values not copied)

`SPIRAL_BROKER_ROOT`, `TEMPLE_FLOW_LIVE`, `TEMPLE_FLOW_ARMED`, `TEMPLE_FLOW_ENV_FILE`, `TEMPLE_FLOW_EYES_CACHE`.

## Cap inventory extension (local)

Supplied packet C01–C40 stands. Additional local facts at `a5aa41b`:

| ID | Location | Effective source | Class | v2 disposition |
|---|---|---|---|---|
| L01 | `scripts/temple_flow_wire.py` `_risk()` default `max_opens=4` | source default if rules omit | process | REMOVE from v2 path; do not call this pipeline |
| L02 | `config/standing_rules.example.json` `risk.max_opens` / `max_ticket_notional_pct` 0.35 | example file; live file gitignored | process | not universal v2 policy |
| L03 | `docs/RISK_CONSTITUTION.md` 2.5/4.5/18 | historical constitution | policy | superseded for `full_loss_research` |
| L04 | `docs/UNIVERSE.md` / `CAPITAL_BASELINE.md` still say max 4 | docs drift vs Sep 15 §9 | process | do not restore |
| L05 | launchd `StartInterval` 900 + `--once` | checked-in plist | technical | REPLACE (C24); not started here |
| L06 | `scripts/send_tf_20260830.py` | standalone | technical | keep out of v2 send boundary (C34) |

Causality caution from the packet remains: L01 is not proven as the cause of idle cash. Last committed Schwab snapshot (2026-09-15) is **not** a live read.

## Isolated test baseline

- `PYTHONPATH=src` + disposable `--state` dir
- `SPIRAL_BROKER_ROOT=/nonexistent` already used by existing wire/eyes tests
- v2 tests never set `TEMPLE_FLOW_LIVE` or create `LIVE_OK`
