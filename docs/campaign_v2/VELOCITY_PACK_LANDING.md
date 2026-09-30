# Velocity pack — Studio landing sheet

**Written:** 2026-09-29, Mac Studio seat, before the PR link arrived.
**Status:** LOCAL SEAT, 2026-09-29. Anthony: "you are the point on this, make the fixes real." The fixes that were libraries in PR #7 now run inside `run_cycle`. They are in the working tree the launchd job executes. They are not committed. `config/standing_grants.json` is absent, so the desk grant is closed and the next cycle approves nothing and arms nothing. Disarm at 16:00 still writes. Copy `config/standing_grants.example.json` and set the two flags true only when Anthony wants the grant open.
**Cloud agent (still running when this was written):** https://cursor.com/agents/bc-28c45204-7595-5eb7-98a1-065fa83b356b
**Author of the pack:** Funds-beast (Grok bot). This sheet is the Studio's acceptance check, not a second design.

The pack is supposed to land as one PR onto the branch the Studio actually runs, and to include deploy and rollback commands. Do not merge it, do not restart the wire, and do not treat a green cloud-agent log as a Studio receipt.

---

## What the Studio is running right now

Measured 2026-09-29, this checkout:

| Fact | Value |
| --- | --- |
| Branch | `feat/campaign-v2-wp0-wp2` @ `fa62b3d` (checked out, not moved) |
| Tracking | `origin/feat/campaign-v2-wp0-wp2` @ `793aebf` — **5 commits ahead of this checkout** |
| Those 5 | `769ffac` desk log push, `e10ef84` friend-profit baseline, `546b45b` and `c2b1e07` Kraken writer/URL/OTO, `793aebf` merge of origin/main. **None touch `scripts/temple_flow_wire.py`.** |
| vs `origin/main` | Local HEAD is an ancestor of origin/feat. `main` locally is `769ffac`. |
| Live job | `com.templetwo.temple-flow-wire`, StartInterval 900s, `--once --live` |
| Program | `~/temple-flow/scripts/temple_flow_wire.py` via `spiral-broker-prod` venv |
| WorkingDirectory | `~/temple-flow` — the job runs the **working tree**, not a pinned commit |
| Last exit | 0. Runs counted at measurement: 89. Job was not running (interval job, exited). |
| Staged, uncommitted | `scripts/temple_flow_wire.py` (+14) and `scripts/test_temple_flow_wire.py` (+169) |

The staged hunk is the PR #6 cancel fix, already sitting in the index and not committed. A checkout, reset, or clean that drops the index will un-apply a fix the live process is already using. Preserve it (commit on a side ref, or stash including the index) before any fetch that moves this tree.

PR #6 itself is still OPEN against `main`, not against this branch:

- https://github.com/templetwo/temple-flow/pull/6
- head `cursor/fix-cancel-resting-pullback-buy-limits-c601` @ `2578ece`
- title: Cancel lane must not delete resting pullback buy limits
- mergeable against `main` at measurement time

A pack that "includes the PR #6 cancel fix" and is based on `main` will not contain the eight commits this Studio runs (`ef9e750` through `fa62b3d`: campaign v2, live adapters, Kraken cycle, Grok bot profiles). A pack based on `feat/campaign-v2-wp0-wp2` will not fast-forward `main`. Confirm the base before anyone says "straight to the Studio."

Untracked and not part of the wire: `logs/`, `docs/campaign_v2/baselines/`, `scripts/exchange_oauth_once.py`, `scripts/start_oauth_listen.py`, `temple-flow-campaign-v2.tgz`. Do not `git clean` them. Do not commit logs or tokens.

---

## The 12 items, and the obstacle each one is answering

Funds-beast listed these. Each row is the Studio fact the pack has to close, with the file that proves the obstacle existed. "Present in the PR" is filled when the link arrives.

| # | Pack claim | Obstacle this Studio already hit | Where it shows |
| --- | --- | --- | --- |
| 1 | PR #6 cancel fix | Mon 2026-09-28 the cancel lane deleted resting GTC buys because `last > cap`, even when `working_px ≤ cap`. Wave 1: ETHA `1008090346868` @19.70 and IBIT `1008090346869` @45.00. Remint: `1008090347785` / `1008090347788`, both CANCELED filledQty 0 by ~14:05 ET. Remint #3 (`1008091389255` / `1008091389256`) only survived because the desk stopped reminting until the wire changed. | `logs/digest/eod_2026-09-28.md`; `logs/digest/mv_watch_2026-09-28_1408.md`; `config/standing_rules.json` comments. The fix is **already staged** in this tree and matches PR #6's stated policy. |
| 2 | Auto-arm MV at 09:25 when cash > 20% | Law already says arm when cash/equity > 20% (AMENDMENTS §8). The wire does not do it. Tue 2026-09-29 cash was **73.21%** all session and MV stayed DISARMED because nobody typed `arm MV session`. Mon's arm was a human phrase at 13:32, after the book had been blind all morning. | `config/mv_session.json` (`armed: false`, `until` still Monday 16:00); `logs/digest/eod_2026-09-29.md`; `docs/AMENDMENTS_2026-09-15.md` §5 and §8. |
| 3 | Guaranteed 16:00 disarm | Mon 2026-09-28 the session stayed armed past 16:00. Desk Lead disarmed it by hand at ~16:09–16:10. The constitution says auto-disarm at 16:00 ET. The file is a note the desk writes; the launchd job does not read a clock and clear it. | `config/mv_session.json` `prior` / `disarm_reason`; `docs/RISK_CONSTITUTION.md` "Auto-disarm". |
| 4 | Pullback buys priced to realistic fill levels, plus a stale-flag rule | Working buys rest at 19.70 and 45.00 while marks sit near 20.29 and 47.34. They cannot fill. Rule 2 in the MV watch ("stale buy → marketable at Risk cap") is a desk habit, not a wire rule, and "marketable" must not become a chase through the cap. | `logs/digest/mv_watch_2026-09-29_1600.md`; standing-rules `_comment` "do not raise cap through mark (no chase)". |
| 5 | Sizing pulls idle cash toward the 25% target inside risk limits | Cash has sat at ~$443 (73% of ~$606 equity) since at least Friday. Amendment §6 wants cash/equity ≤ 25% by end of a full RTH week unless a hard-hold is logged. No hard-hold was logged Mon or Tue. The wire has no cash-target sizer (`cash_target` / `0.25` do not appear in `temple_flow_wire.py`). | `logs/digest/eod_2026-09-28.md`, `logs/snapshots/helix_eod_2026-09-29.txt`; `docs/AMENDMENTS_2026-09-15.md` §6. |
| 6 | Standing approvals as a config file, with a revoke switch. Risk-PASS tickets approve themselves. A repriced ticket keeps its approval. VETO, chase above cap, new names, and breaker reset stay Anthony's. | This is the redundant-tap obstacle. See the next section. It is the one Funds-beast was told to add, and it is the one most likely to be implemented as "skip the gate." | `docs/AMENDMENTS_2026-09-15.md` §7; `docs/RISK_CONSTITUTION.md` ticket protocol; `scripts/temple_flow_wire.py` `cmd_approve_plan`. |
| 7 | Schwab login check at 08:30. If the token died overnight, say so before the open. | Mon 2026-09-28 the refresh token was dead at the morning brief (`invalid_grant`). The 10:01 and 10:45 watches were still BLOCKED. Live GETs returned only after a midday OAuth on the Mac. The desk was blind through the open, which is exactly when an arm and a restamp were needed. | `logs/digest/mv_watch_2026-09-28_1001.md`, `mv_watch_2026-09-28_1045.md`; `runbooks/SCHWAB_WIRE.md`. |
| 8 | Studio drift check: warn when the Studio is behind the repo, or carrying hot-patches that were never committed. | This tree is the case, and it is the obstacle the pack is most likely to miss because a `git status` taken before the fetch said "in sync." After `git fetch` on 2026-09-29 the checkout is **5 behind** `origin/feat/campaign-v2-wp0-wp2` (`fa62b3d` vs `793aebf`) and the cancel fix is **staged, uncommitted**. Launchd executes that dirty file every 15 minutes. A seat that reads `main`, or that trusts a status line from before the fetch, will report a wire the Studio is not running. | This file's header table. `git rev-list --left-right --count HEAD...origin/feat/campaign-v2-wp0-wp2` printed `0 5`. |
| 9 | Kraken marked unverified, with the time it was last confirmed, whenever the MacBook is offline. | Mon and Tue EOD both say Kraken was not reconfirmed. Studio has no `KRAKEN_*` keys. Last narrative (XXBT 0.0012, stop `O55VHG`, ZUSD ~2.12) is unconfirmed and must not be folded into the Schwab research number. Combined $701.40 baseline was deliberately not re-baselined. | `logs/snapshots/helix_eod_2026-09-29.txt` Kraken section; `docs/campaign_v2/baselines/`. |
| 10 | Freed cash goes back to work on the next check, not the next morning. | Amendment §4 already calls a multi-session cash sit a process defect. The wire's planner runs off-hours and its only path into the outbox is a human `--approve-plan`. A fill or cancel inside the session does not resize the next ticket. Cash did not move on either of the last two sessions, so this row is law-versus-code, not a fill we watched sit. | `scripts/temple_flow_wire.py` off-hours planning lane (~line 2060); `docs/AMENDMENTS_2026-09-15.md` §4. |
| 11 | Market data falls back to Yahoo out loud when the Twelve Data key is missing, instead of failing silently. | Eyes are Twelve Data only (`TWELVE_DATA_API_KEY`). They are evidence-only and must stay off the POST path. A missing key today fails the look; the desk has been papering over that with Schwab quotes when Schwab is up, and with nothing when Schwab is dark. Yahoo already exists in `scripts/historical_backfill_secondary_daily.py` and is not wired as an eyes fallback. | `scripts/temple_flow_eyes.py` header; `docs` lock of Twelve Data as evidence-only (commit `a5aa41b`). |
| 12 | PR lists all 12 with status, plus Studio deploy and rollback commands. | Not checkable until the link is up. The commands have to match the job below, not a generic `systemctl` recipe. | This file, "Deploy and rollback". |

---

## Redundant approval taps — the obstacle, in the order it actually fires

Anthony asked that this be in the pack. It is not one bug. It is four taps for one idea.

1. **Risk PASS is not permission.** Risk stamps size. The ticket still needs an exact `approve TF-YYYYMMDD-XX`, or a live `arm MV session`, before Execution may send. Constitution ticket protocol, item 2. Amendment §7 already delegated PASS approval to Funds-beast (`desk may approve Risk-PASS tickets`, revoke phrase `desk may not approve`). The wire does not read that delegation. `cmd_approve_plan` is a hand command. Desk-approve today means a person copies a file into `config/outbox/` and types the phrase in chat.

2. **The arm is a second phrase for the same idea.** `arm MV session` was supposed to be the once-per-session tap (constitution, 2026-08-24: "human arms the session once, not every ticket"). It is itself a tap, it does not survive 16:00, and on 2026-09-29 nobody re-issued it, so two already-approved Risk-PASS tickets sat as resting orders and no new sizing ran. Auto-arm at 09:25 (item 2) removes this tap only inside the conditions Amendment §8 already states. It must not arm on a hard-hold day, a tripped breaker, or a dead Schwab token.

3. **A reprice burns the approval.** `cmd_approve_plan` refuses `outbox_ticket_already_exists` and will not clobber. A deepened pullback is a new file, a new id, and a new phrase. That is how TF-20260921-02 produced a failed copy, a `refused_cap` copy, an `.exec`, an `.intent`, a remint, and a remint3 under `logs/tickets/`. The standing-rules comment records the other half: a stale cap of 43.9 against a PASS limit of 45.00 made the wire `cancel_abandon` the remint, so the desk raised the cap and approved again. Item 6's "a repriced ticket keeps its approval" has to mean: same idea, same Risk PASS, price moved down inside the cap, no new phrase. It must not mean: a higher limit, a larger qty, or a new symbol inherits the old yes.

4. **The 24-hour plan shelf asks for the phrase again even when nothing changed.** `MAX_PLAN_AGE_HOURS = 24`. `cmd_approve_plan` returns `plan_too_old_regenerate`. A Monday-night plan cannot be approved Tuesday at the open without a regeneration and a fresh tap. That is a real safety property for a plan whose ATR and trend have gone stale. It is a redundant tap when the regenerated candidate is the same symbol, same side, same-or-lower limit, same stop, and Risk has re-stamped PASS. The pack should keep the regeneration and drop only the second human phrase in that case.

**What stays a tap, and the pack must not automate these:**

- Risk **VETO**
- Any replace that raises the limit or chases through the cap
- A name outside ETHA/IBIT live entries (NVO/NOK stay protect-only)
- Circuit-breaker reset after a 4.5% day or an 18% peak drawdown
- Changing the Risk percentages, or widening the universe
- The phrase that revokes the delegation (`desk may not approve`)

A config file of standing approvals needs a revoke that the wire reads on every cycle, defaulting closed if the file is missing, unreadable, or older than a stated bound. A missing file that means "approve everything" is the fail-open this desk has already been burned by.

---

## Acceptance checks (run these on the PR diff, before any restart)

Do not restart the job to "see if it works." The interval is 15 minutes and `--live` posts.

1. **Base.** PR base is `feat/campaign-v2-wp0-wp2` (or the PR contains those 8 commits). A PR against `main` only is not "straight to the Studio."
2. **Cancel fix is the staged policy, not a rewrite.** Resting buy with `working_px ≤ cap` is left when `last > cap`. `working_px > cap` still cancels. Unknown `working_px` does not cancel on last-through-cap alone (the staged condition requires `working_px is not None`). One-sell, no-DAY, and leftover-universe skips are untouched.
3. **Auto-arm cannot fire unless all of these are true:** cash/equity > 20% on a proven Schwab read, clock is the 09:25 ET check (not "sometime in the morning" and not a late restart at 14:00), no FOMC/CPI hard-hold flag, breaker clear, token valid. A failed book read does not arm.
4. **16:00 disarm is in the process the job already runs,** so a seat being asleep does not leave MV armed. After 16:00 ET, `mv_session.json` effective state is disarmed even if the file still says armed. Disarm does not cancel resting GTC buys and does not touch protect stops.
5. **Fillable prices never reprice up.** A stale flag is a log line and a ticket annotation. A new limit is ≤ the Risk cap and ≤ the prior working limit, or it is a proposal that still needs Anthony. "Realistic fill" is not a market order.
6. **Idle-cash sizing stays inside the box.** 2.5% risk per trade, 4.5% day, 18% peak, hard stop on, one-sell, no add to an existing long unless a later amendment says so. The 18% position cap still does not bind the MV lane; the 2.5% stop-dollar cap does. Target 25% cash is a direction, not a mandate to deploy into a name that fails Risk.
7. **Self-approval is gated.** A ticket with `approved_by: desk_lead` and Risk PASS, for an in-universe name, at or under the cap, may skip the chat phrase. The same ticket with a raised limit, a new symbol, a VETO, or a missing Risk stamp may not. Revoke file wins over the ticket's own `approved_by` field.
8. **08:30 token check is a warning, not a trade.** It does not refresh by scraping, it does not start OAuth by itself, and it does not fall open into a POST on the last-known book. The Monday failure mode was `invalid_grant` on the refresh token; detecting that before 09:30 is the whole requirement.
9. **Drift check is read-only.** It prints branch, HEAD, dirty wire files, and ahead/behind. It does not commit, stash, or reset. It must notice the staged-index case, not only unstaged edits.
10. **Kraken line carries `unverified` and a timestamp** when the MacBook path was not read this cycle. It is excluded from Schwab equity, cash target, and the friend-profit Schwab leg.
11. **Freed-cash recheck is the next wire cycle (≤15 min),** and it still passes the outbox gates. It does not POST from the planner directly.
12. **Yahoo fallback is loud and evidence-only.** The log line names Yahoo and names the missing key. `book_is_live_eligible` still requires a proven Schwab read before any POST or DELETE. A Yahoo last must not satisfy `quotes_unproven`.
13. **Tests cover the refusal directions,** not only the happy path: revoke present, token dead, cash under 20%, hard-hold day, repriced-up ticket, missing working_px, Yahoo last presented as if it were Schwab.
14. **Deploy and rollback commands match the "Deploy and rollback" section,** or they say why they differ. A command that checks out `main` is a rollback to the wrong wire.

---

## Deploy and rollback (do not run these while preparing)

The live process is the working tree. There is no separate release directory. A merge that is not checked out here changes nothing. A checkout here changes the next 15-minute tick.

**Before touching the tree**

```bash
git -C ~/temple-flow diff --cached --stat
git -C ~/temple-flow stash push --staged -m "pre-velocity-pack-index $(date +%Y%m%d-%H%M)"
git -C ~/temple-flow stash list | head -3
```

`--staged` stashes the index only. Leave `-u` off. Untracked logs, baselines, and the campaign tarball are not part of the parachute and must not be swept into a stash that a later `stash pop` might mix with the wire.

**Fast-forward this checkout first, only when Anthony says the five commits may land.** They do not touch the wire. They do add a Kraken launchd plist (`deploy/com.templetwo.temple-flow-kraken.plist`) and Kraken send-path edits. Loading that plist is a separate act from the fast-forward, and it is not part of preparing for this PR. A fast-forward with a staged index will refuse or will carry the staged wire hunk onto `793aebf`; stash the index first, ff, then `stash pop` and re-check that the cancel hunk still applies.

```bash
git -C ~/temple-flow merge --ff-only origin/feat/campaign-v2-wp0-wp2
```

**Deploy of the velocity pack, only after the acceptance checks pass and Anthony says go**

```bash
# fetch the PR head. Do not pull main over this branch.
git -C ~/temple-flow fetch origin
git -C ~/temple-flow status -sb
# merge or ff only the reviewed head, onto feat/campaign-v2-wp0-wp2
# then prove the file the job will execute:
launchctl print gui/$(id -u)/com.templetwo.temple-flow-wire | /usr/bin/grep -E 'program =|state =|runs =|last exit'
# one dry cycle, no --live, before the next interval tick:
~/spiral-broker-prod/dashboard/api/venv_new/bin/python3 \
  ~/temple-flow/scripts/temple_flow_wire.py --once
```

A `--live` hand-run is a real POST. Do not use it as a smoke test.

The job does not need a kickstart if the checkout is already the WorkingDirectory. The next StartInterval tick picks up the new file. Kickstart only if you must not wait 15 minutes, and only after the dry cycle is clean:

```bash
launchctl kickstart -k "gui/$(id -u)/com.templetwo.temple-flow-wire"
```

**Rollback**

```bash
# back to the commit the Studio was on when this sheet was written
git -C ~/temple-flow checkout feat/campaign-v2-wp0-wp2
git -C ~/temple-flow reset --hard fa62b3d
# put the staged cancel fix back. It is not inside fa62b3d.
git -C ~/temple-flow stash pop
# confirm the job will see the restored file, then let the interval pick it up
git -C ~/temple-flow diff --cached --stat
```

`reset --hard` drops uncommitted work. The stash is the only copy of the cancel fix if it was never committed. Confirm `stash list` shows it before the reset. Do not rollback by checking out `main`: that removes the campaign-v2 commits the desk is living on, and it does not contain the staged fix.

If the new code already POSTed, rollback of the file does not un-send the order. Cancel is a separate, RTH-only, ticketed act. After hours a cancel of `PENDING_ACTIVATION` returns 400; leave the stop.

---

## What this seat will do when the link arrives

1. Read the PR base, the file list, and the deploy/rollback section against this sheet.
2. Diff the cancel-lane hunk against the staged patch so we do not "upgrade" onto a weaker condition.
3. Run the pack's tests from a worktree, not from this live checkout, so a test cannot import the dirty wire or write `config/outbox/`.
4. Report which of the 12 rows are present, which are named-but-unwired, and which of the four approval taps are actually gone.
5. Stop there. Merge, checkout, and kickstart wait on Anthony.
