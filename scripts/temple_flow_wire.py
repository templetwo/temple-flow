#!/usr/bin/env python3
"""Temple Flow Act-loop wire (Studio daemon).

Default is DRY-RUN. Never prints tokens or secrets.
POST helper is real (TRIGGER GTC limit + attached stop; protect STOP GTC).
Default remains dry-run. launchd may pass --live when config/LIVE_OK exists.

Flags:
  --status         read-only book / orders / quotes (or box fallback)
  --once           one plan cycle (launchd path)
  --live           refused unless config/LIVE_OK AND TEMPLE_FLOW_LIVE=1
  --approve-plan   PLAN_FILE TICKET_ID — copy one planned candidate into the
                   outbox as an approved ticket. Offline; no broker call.

plan_actions(rules, book) is pure and unit-testable (no network).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# The off-hours idea generator, isolated in its own file ON PURPOSE: it is the
# seam Grok's spec replaces, and every risk cap stays on THIS side of it. See
# the contract at the top of temple_flow_strategy.py.
try:  # pragma: no cover - exercised by every import of this module
    import temple_flow_strategy as strategy
except ImportError:  # pragma: no cover - only when imported from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import temple_flow_strategy as strategy

try:
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-4))

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKER_ROOT = Path(
    os.environ.get("SPIRAL_BROKER_ROOT", Path.home() / "spiral-broker")
).expanduser()

LIVE_UNIVERSE = ("ETHA", "IBIT")
PROTECT_ONLY = ("NVO", "NOK")
WORKING_STATUSES = {
    "WORKING",
    "QUEUED",
    "ACCEPTED",
    "PENDING_ACTIVATION",
    "AWAITING_PARENT_ORDER",
    "AWAITING_CONDITION",
    "PENDING_REPLACE",
    "PENDING_CANCEL",
}
CLOSED_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "REPLACED"}

# Hard per-ticket notional ceiling for the outbox lane.
# Fraction of live equity. 0.35 admits one real position on a ~$600 book
# (5 ETHA @ 18.70 = $93.50; 2 IBIT @ 43.90 = $87.80) while capping a fat-finger.
# NOT the 2.5% risk_pct: that caps |limit-stop|*qty, this caps qty*limit.
MAX_TICKET_NOTIONAL_PCT_DEFAULT = 0.35
# config/cancel_refusals.json — order_ids Schwab refused with HTTP 400 today.
CANCEL_REFUSAL_STATE = ("config", "cancel_refusals.json")

# --- off-hours planning lane -----------------------------------------------
# config/plans/<YYYY-MM-DD>_<HHMM>.json. READ-ONLY output: a plan is a proposal
# a human approves, never an order. Nothing in this file writes to
# config/outbox/ except cmd_approve_plan, which a human runs by hand.
PLAN_DIR = ("config", "plans")
#: Daily candles requested per symbol. A year of sessions is ~252; asking for
#: more than the 55 the features need costs one HTTP call either way and leaves
#: room for a longer-window strategy to land on this seam without a refetch.
HISTORY_DAYS = 260
#: Fewest daily bars that can answer the feature set: 50 for the slow SMA plus
#: 5 more for its slope. Below this the plan says `insufficient_history`, which
#: is NOT the same fact as `history_unproven` (a read that failed).
MIN_HISTORY_BARS = 55
#: How old a PLAN may be and still be approvable. Plan overnight, Anthony
#: approves in the morning; anything older is regenerated, not approved.
#:
#: ITS OWN PARAMETER, NOT A MULTIPLE OF THE QUOTE BOUND. Until 2026-09-04 this
#: window was `validity.max_data_age_minutes x 24`, which coupled two unrelated
#: clocks BACKWARDS: tightening the quote-freshness bound from 60 to 15 minutes
#: — a safety tightening, and exactly what "time sensitive data" invites —
#: silently shrank the approval window from 24h to 6h, so a 20:00 plan could no
#: longer be approved at 07:00. One knob must not quietly move the other.
MAX_PLAN_AGE_HOURS = 24.0
#: How many session closes ahead cmd_approve_plan sets a ticket's `expires_at`.
#: 1 = "this idea is good until the next close". An approved ticket used to be
#: bounded by price and trend only, never by time.
APPROVAL_EXPIRES_AT_SESSIONS = 1
#: A plan ticket id becomes a filename. Generated ids are
#: TF-PLAN-<YYYYMMDD-HHMM>-<SYM>; anything with a separator, a "..", or a NUL
#: is refused rather than joined into a path.
_SAFE_TICKET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
#: Seconds a daily-history read may block. The planner's own budget.
HISTORY_TIMEOUT_S = 30.0
#: The re-evaluation refetch's budget, and it is deliberately much smaller.
#: That call happens inside gate_outbox_ticket, which run_cycle drives BEFORE
#: plan_actions — so a hung Schwab read there delays a PROTECT stop, during
#: RTH, which is when protect matters most. A slow read should defer the
#: ticket (a WAIT, re-gated in 900s) rather than hold the lane: nothing is lost
#: by waiting a cycle, and a naked position waiting on a socket is real.
HISTORY_TIMEOUT_REEVAL_S = 8.0

# --- outbox refusal disposition -------------------------------------------
# Anthony, 2026-09-03 07:49 ET:
#   "They should wait not die. Execution should start back up when the markets
#    open."
# Before that directive every refusal quarantined to config/outbox/failed/,
# so a ticket approved at 22:00 was dead by 09:30 for the single offence of
# having been written while the market was shut.

WAIT_REFUSALS = frozenset(
    {
        "outside_rth",
        "arm_required",
        "orders_unproven",
        "book_missing",
        "book_not_schwab_read",
        "equity_unknown_cannot_size",
        "new_risk_blocked",
        # --- the three re-evaluation WAITs (2026-09-04) ---
        # All three say the same thing: the daemon could not READ what a
        # `validity` block told it to check. None of them is a statement about
        # the ticket, so all three are re-gated on the next healthy cycle.
        "quotes_unproven",
        "data_stale_refetch_next_cycle",
        "history_unproven_refetch_next_cycle",
    }
)
"""Refusals that PARK the ticket in config/outbox/ to be re-gated next cycle.

THE RULE: a refusal is a WAIT only when nothing about the ticket is wrong. The
ticket is well-formed, inside the universe, inside every cap — and the only
thing standing in its way is the clock, the session arm file, a degraded broker
read, or the risk box. Every one of those is a property of the WORLD at this
instant, not of the ticket, so a later cycle can legitimately find it changed.

THE THREE 2026-09-04 ADDITIONS ARE THE SAME SHAPE, and are named here rather
than left to the frozenset because this docstring explains its members:
`quotes_unproven` (a `validity` ticket needs a live price and the quotes leg
failed), `data_stale_refetch_next_cycle` (the price is there but too old to
re-decide on — Anthony, 2026-09-03 11:47 EDT: "time sensitive data") and
`history_unproven_refetch_next_cycle` (the daily-history refetch failed, or
came back with too few bars to recompute the trend). Every one is a failed
READ. None is a verdict on the idea — the verdict is `idea_stale_reevaluated`,
which is terminal.

"THE RISK BOX RESETS DAILY" IS TRUE OF ONE OF ITS THREE CLAUSES, NOT THREE.
Only the day breaker is day-scoped. peak-DD is (peak-equity)/peak, not a daily
figure — inert on the real read path only because fetch_book stamps
peak_equity = equity. max-opens is the sharp one: count_opens counts DISTINCT
SYMBOLS holding a position with qty>0 or a working BUY entry, so the standing
NVO and NOK protect-only positions permanently occupy 2 of the default
max_opens 4, and nothing about a new day releases them.

MEASURED, and narrower than it first looks, so do not over-cite it: with the
live universe at two symbols (ETHA/IBIT), a ticket that REACHES the risk box
has no position and no working entry of its own, which caps opens at 3
(NVO, NOK, the other universe symbol) — under the default max_opens 4 the gate
passes. Saturation needs a fourth distinct symbol in the account, or a tighter
max_opens: an AAPL position alongside NVO/NOK/IBIT gives opens 4 >= 4 and
`new_risk_blocked` on the default rules, and max_opens 3 blocks at opens 3.
Both states persist across days, not until midnight.

That is FAIL-SAFE — nothing posts, and a human clearing a position or an order
releases it — but it is an INDEFINITE wait, not an overnight one, and nothing
in the default config bounds it. `outbox.max_wait_days` is the bound, and it is
absent by default, which is Anthony's call.

A parked ticket is re-gated from scratch every cycle. It is never "half
approved", it carries no permission forward, and it posts only when the full
gate list passes on a fresh book. Waiting is bounded by the ticket's optional
`expires_at` and by the optional rules field `outbox.max_wait_days`.
"""

TERMINAL_REFUSALS = frozenset(
    {
        "ticket_unreadable",
        "ticket_schema_invalid",
        "ticket_expired",
        "ticket_wait_exceeded",
        "rules_missing",
        "not_in_live_universe",
        "protect_only_no_entry",
        "ticket_limit_above_cap",
        "through_cap_idea_dead",
        "qty_clipped_to_zero",
        "ticket_qty_exceeds_risk_clip",
        "notional_cap_uncomputable",
        "ticket_notional_over_cap",
        "existing_entry_in_book",
        "one_sell_law_existing_sell",
        "already_long_no_add",
        "duplicate_working_order",
        "cancel_order_id_not_working_in_book",
        "cancel_symbol_not_in_live_universe",
        "cancel_skipped_refused_today",
        # 2026-09-04. The re-evaluation verdict: the ticket carried a
        # `validity` block, the daemon re-read the world at execution time, and
        # a condition the human approved is no longer true.
        "idea_stale_reevaluated",
    }
)
"""Refusals that QUARANTINE the ticket to config/outbox/failed/ immediately.

THE RULE, STATED AS THE SAFETY BIAS IT IS RATHER THAN AS A FACT ABOUT TIME:
the refusal names something about the ticket itself, or about a standing rule
it violates, that a later cycle is not TRUSTED to have changed. It is refused
at 03:00 exactly as it would be at 10:00 — which is why the terminal checks
that need no clock and no fresh quote run FIRST in gate_outbox_ticket.
`unknown_action` reaches here inside `ticket_schema_invalid`, which carries it
in `schema_errors`.

SEVEN OF THESE ARE NOT LITERALLY IMMUTABLE, and saying otherwise would teach
the next reader to reclassify them: `existing_entry_in_book`,
`one_sell_law_existing_sell`, `already_long_no_add` and
`duplicate_working_order` all read book state that changes when an order fills
or is canceled; `qty_clipped_to_zero` / `ticket_notional_over_cap` are derived
from equity, which moves; and `idea_stale_reevaluated` reads a live price and a
live trend, either of which can come back tomorrow. They are TERMINAL on
purpose anyway: each says the ticket collides with a position or an order that
already exists, that the account cannot carry the size approved, or that the
idea a human approved is not the idea in front of the daemon now. Re-approving
is a decision a human should make with fresh eyes, not something a daemon
should retry into overnight. Killing a ticket that might later have passed
costs one hand-moved file; a daemon quietly re-arming an idea nobody
re-approved costs money.

An unclassified reason is treated as TERMINAL (see refusal_is_wait): the
pre-directive behaviour is the fail-closed one, because a reason nobody
classified must never park a ticket on a live wire forever.
"""


def refusal_is_wait(reason: str | None) -> bool:
    """True when a refused outbox ticket should stay put and be re-gated.

    Fail-closed by construction: only a reason explicitly listed in
    WAIT_REFUSALS waits. Anything else — including a reason added to the wire
    tomorrow and never classified — quarantines, which is what the loop did
    for every refusal before 2026-09-03.
    """
    return reason in WAIT_REFUSALS


def now_et(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(ET)
    if now.tzinfo is None:
        return now.replace(tzinfo=ET)
    return now.astimezone(ET)


def in_rth(now: datetime | None = None) -> bool:
    """Weekday 09:00–16:00 America/New_York (launchd is RTH-ish)."""
    t = now_et(now)
    if t.weekday() >= 5:
        return False
    minutes = t.hour * 60 + t.minute
    return (9 * 60) <= minutes < (16 * 60)


def session_close_after(now: datetime | None = None, sessions: int = 1) -> datetime:
    """The 16:00 ET close `sessions` sessions from now. Weekdays only.

    A session is a WEEKDAY here, exactly as in_rth() defines one — the wire has
    no exchange holiday calendar. NAME THE ERROR THAT MAKES, do not hide it: a
    market holiday is counted as a session, so a deadline can fall on a day the
    exchange never opened and the ticket expires having had fewer live sessions
    than it was given. That direction is fail-safe (the idea dies, nothing
    posts, a human re-approves in one command) which is why the approximation
    is acceptable — but a reader must not expect "1 session" to mean "1 trading
    session" across Thanksgiving.

    Counting starts from the NEXT close strictly after `now`, so approving at
    16:30 Friday with sessions=1 yields Monday 16:00, not a deadline in the
    past.
    """
    t = now_et(now)
    close = t.replace(hour=16, minute=0, second=0, microsecond=0)
    if t >= close or t.weekday() >= 5:
        # push to the next calendar day; the weekday skip below lands it
        close = (t + timedelta(days=1)).replace(
            hour=16, minute=0, second=0, microsecond=0
        )
    remaining = max(1, int(sessions))
    while True:
        while close.weekday() >= 5:
            close = close + timedelta(days=1)
        remaining -= 1
        if remaining <= 0:
            return close
        close = close + timedelta(days=1)


def logj(obj: dict) -> None:
    print(json.dumps(obj, default=str, separators=(",", ":")), flush=True)


def load_rules(repo_root: Path | None = None) -> tuple[dict, Path]:
    root = repo_root or REPO_ROOT
    standing = root / "config" / "standing_rules.json"
    example = root / "config" / "standing_rules.example.json"
    path = standing if standing.exists() else example
    if not path.exists():
        raise FileNotFoundError(f"no standing rules at {standing} or {example}")
    with path.open() as f:
        rules = json.load(f)
    return rules, path


def session_armed(repo_root: Path | None = None, now: datetime | None = None) -> bool:
    """Arm file on disk. Auto-disarm at `until` (ISO) or 16:00 ET that day."""
    if os.environ.get("TEMPLE_FLOW_ARMED") == "1":
        return True
    path = (repo_root or REPO_ROOT) / "config" / "mv_session.json"
    if not path.exists():
        return False
    try:
        d = json.loads(path.read_text())
    except Exception:
        return False
    if not d.get("armed"):
        return False
    t = now_et(now)
    until = d.get("until")
    if until:
        try:
            u = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
            if u.tzinfo is None:
                u = u.replace(tzinfo=ET)
            if t >= u.astimezone(ET):
                return False
        except Exception:
            pass
    elif t.hour >= 16:
        return False
    return True


def live_authorized(repo_root: Path | None = None) -> tuple[bool, str]:
    root = repo_root or REPO_ROOT
    live_ok = (root / "config" / "LIVE_OK").exists()
    env_ok = os.environ.get("TEMPLE_FLOW_LIVE") == "1"
    if not live_ok and not env_ok:
        return False, "LIVE_REFUSED: need config/LIVE_OK and TEMPLE_FLOW_LIVE=1"
    if not live_ok:
        return False, "LIVE_REFUSED: config/LIVE_OK missing"
    if not env_ok:
        return False, "LIVE_REFUSED: TEMPLE_FLOW_LIVE!=1"
    return True, "LIVE_GATES_OPEN"


def broker_available(root: Path | None = None) -> bool:
    b = root or BROKER_ROOT
    return (b / "src" / "token_manager.py").exists()


def clip_qty(
    qty: Any,
    entry: Any,
    stop: Any,
    equity: Any,
    risk_pct: float = 0.025,
) -> int:
    """Clip share count so |entry-stop| * qty <= risk_pct * equity.

    Unknown / non-positive equity or stop distance → 0 (no unsupervised size).
    """
    try:
        q = int(qty)
    except (TypeError, ValueError):
        return 0
    if q <= 0:
        return 0
    try:
        eq = float(equity)
        risk_per_share = abs(float(entry) - float(stop))
        rp = float(risk_pct)
    except (TypeError, ValueError):
        return 0
    if eq <= 0 or risk_per_share <= 0 or rp <= 0:
        return 0
    max_qty = int(eq * rp // risk_per_share)
    return max(0, min(q, max_qty))


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _risk(rules: dict) -> dict:
    r = rules.get("risk") or {}
    return {
        "risk_pct": float(r.get("risk_pct", 0.025)),
        "day_breaker_pct": float(r.get("day_breaker_pct", 0.045)),
        "peak_dd_pct": float(r.get("peak_dd_pct", 0.18)),
        "max_opens": int(r.get("max_opens", 4)),
    }


def order_symbol(order: dict) -> str | None:
    if order.get("symbol"):
        return str(order["symbol"]).upper()
    for leg in order.get("orderLegCollection") or order.get("legs") or []:
        inst = leg.get("instrument") or {}
        sym = inst.get("symbol") or leg.get("symbol")
        if sym:
            return str(sym).upper()
    return None


def order_side(order: dict) -> str:
    if order.get("side"):
        return str(order["side"]).upper()
    for leg in order.get("orderLegCollection") or order.get("legs") or []:
        inst = str(leg.get("instruction") or "").upper()
        if "BUY" in inst:
            return "BUY"
        if "SELL" in inst:
            return "SELL"
    return ""


def order_status(order: dict) -> str:
    return str(order.get("status") or "").upper()


def order_is_working(order: dict) -> bool:
    st = order_status(order)
    if st in CLOSED_STATUSES:
        return False
    if st in WORKING_STATUSES or st == "":
        rem = order.get("remaining")
        if rem is None:
            rem = order.get("remainingQuantity")
        filled = order.get("filledQty")
        if filled is None:
            filled = order.get("filledQuantity")
        qty = order.get("qty")
        if qty is None:
            qty = order.get("quantity")
        if rem is not None:
            try:
                return float(rem) > 0
            except (TypeError, ValueError):
                pass
        if filled is not None and qty is not None:
            try:
                return float(filled) < float(qty)
            except (TypeError, ValueError):
                pass
        return st != "FILLED"
    return False


def order_is_stop(order: dict) -> bool:
    typ = str(order.get("type") or order.get("orderType") or "").upper()
    if "STOP" in typ:
        return True
    return order.get("stopPrice") is not None and "LIMIT" not in typ


def order_is_buy_entry(order: dict) -> bool:
    if order_side(order) != "BUY":
        return False
    if order_is_stop(order) and "LIMIT" not in str(
        order.get("type") or order.get("orderType") or ""
    ).upper():
        return False
    return True


def book_leg_proven(book: dict, leg: str) -> bool:
    """True only when the named broker read leg is PROVEN complete.

    fetch_book issues three independent HTTP calls (accounts, orders, quotes).
    The accounts call failing aborts the whole read, but a failed orders or
    quotes call used to leave an EMPTY collection behind with no signal, and
    every guard in this file is book-derived: an orders call that 500s handed
    the gates an empty book and they all passed. An empty list is indis-
    tinguishable from "nothing is working" unless coverage is stated.

    Absence of the flag is NOT permission. A hint book, a hand-built book, or
    any future book source that does not state its coverage is unproven by
    construction, so this fails closed on anything it has not been told about.
    """
    return book.get(leg + "_ok") is True


def book_is_live_eligible(book: Any) -> tuple[bool, str]:
    """Only a PROVEN Schwab read may drive a live POST or DELETE.

    resolve_book substitutes fallback_book whenever fetch_book returns None —
    reachable on a transient accounts-endpoint 500 with perfectly valid tokens
    and a working POST path. That hint book is assembled from the config file,
    so letting it reach the wire lets standing_rules.json answer questions only
    the broker can answer. `source` is the established discriminator here
    (plan_actions already keys its already_working branch on it).
    """
    if not isinstance(book, dict) or not book:
        return False, "book_missing"
    if book.get("source") != "schwab_read":
        return False, "book_not_schwab_read"
    return True, ""


def last_price(book: dict, symbol: str) -> float | None:
    q = (book.get("quotes") or {}).get(symbol) or (book.get("quotes") or {}).get(
        symbol.upper()
    )
    if not isinstance(q, dict):
        return None
    return _f(q.get("last") or q.get("mark") or q.get("lastPrice"))


def existing_protect(book: dict, symbol: str) -> dict | None:
    for o in book.get("orders") or []:
        if order_symbol(o) != symbol:
            continue
        if not order_is_working(o):
            continue
        if order_side(o) == "SELL" and (
            order_is_stop(o) or _f(o.get("stopPrice")) is not None
        ):
            return o
    return None


def existing_sell(book: dict, symbol: str) -> dict | None:
    """Find any working SELL order (stop or limit). One-sell law."""
    for o in book.get("orders") or []:
        if order_symbol(o) != symbol:
            continue
        if not order_is_working(o):
            continue
        if order_side(o) == "SELL":
            return o
    return None


def existing_entry(book: dict, symbol: str) -> dict | None:
    for o in book.get("orders") or []:
        if order_symbol(o) != symbol:
            continue
        if not order_is_working(o):
            continue
        if order_is_buy_entry(o):
            return o
    return None


def position_qty(book: dict, symbol: str) -> float:
    for p in book.get("positions") or []:
        if str(p.get("symbol") or "").upper() == symbol:
            try:
                return float(p.get("qty") or p.get("quantity") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def count_opens(book: dict) -> int:
    symbols = set()
    for p in book.get("positions") or []:
        sym = str(p.get("symbol") or "").upper()
        try:
            q = float(p.get("qty") or p.get("quantity") or 0)
        except (TypeError, ValueError):
            q = 0.0
        if sym and q > 0:
            symbols.add(sym)
    for o in book.get("orders") or []:
        if order_is_working(o) and order_is_buy_entry(o):
            sym = order_symbol(o)
            if sym:
                symbols.add(sym)
    return len(symbols)


def risk_box(rules: dict, book: dict) -> dict:
    """Skip new risk if daily loss / peak DD / max opens trip (when known)."""
    cfg = _risk(rules)
    reasons: list[str] = []
    equity = _f(book.get("equity"))
    peak = _f(book.get("peak_equity") or book.get("peak"))
    sod = _f(book.get("sod_equity") or book.get("sod"))
    day_pnl = _f(book.get("day_pnl"))
    deposit = _f(book.get("deposit_today")) or 0.0
    if day_pnl is None and equity is not None and sod is not None:
        day_pnl = equity - sod - deposit

    if equity is not None and day_pnl is not None:
        basis = sod if sod not in (None, 0) else equity
        if basis and day_pnl <= -cfg["day_breaker_pct"] * basis:
            reasons.append(
                f"day_breaker: day_pnl={day_pnl:.4f} <= -{cfg['day_breaker_pct']*100:.1f}% of {basis:.2f}"
            )

    if equity is not None and peak not in (None, 0):
        dd = (peak - equity) / peak
        if dd >= cfg["peak_dd_pct"]:
            reasons.append(f"peak_dd: {dd:.4f} >= {cfg['peak_dd_pct']}")

    opens = count_opens(book)
    if opens >= cfg["max_opens"]:
        reasons.append(f"max_opens: {opens} >= {cfg['max_opens']}")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "equity": equity,
        "day_pnl": day_pnl,
        "opens": opens,
        "cfg": cfg,
    }


def _action(
    op: str,
    symbol: str | None,
    reason: str,
    params: dict | None = None,
) -> dict:
    return {
        "op": op,
        "symbol": symbol,
        "reason": reason,
        "params": params or {},
        # `sent` means "an order was PLACED". A cancel never sets it.
        "sent": False,
        # `mutated` means "the broker state changed" (a place OR a cancel).
        "mutated": False,
        "dry_run": True,
    }


def plan_actions(rules: dict, book: dict) -> list[dict]:
    """Pure planner. No network. Never marks sent=True.

    Laws (2026-08-28):
      - new entries only ETHA / IBIT
      - NVO / NOK protect-only (stops, no adds)
      - GTC + attached stop; no DAY
      - never raise a working limit through Risk cap
      - through cap = cancel / abandon, do not chase
      - 2.5% risk clip, max 4 opens
      - skip new risk if daily loss >= 4.5% or DD >= 18% (when equity known)
    """
    actions: list[dict] = []
    cfg = _risk(rules)
    box = risk_box(rules, book)
    equity = box["equity"]
    armed = bool(book.get("armed"))
    arm_required = bool(rules.get("arm_required", True))
    no_day = bool(rules.get("no_day", True))
    universe = [str(s).upper() for s in (rules.get("universe") or LIVE_UNIVERSE)]
    entries = rules.get("entries") or {}
    protect = rules.get("protect") or {}
    rth = book.get("in_rth")
    if rth is None:
        rth = in_rth()

    # --- leftovers: protect only ---
    # DELIBERATE OMISSION, do not "fix" it: this lane checks universe and
    # duplicates but NOT armed, NOT rth and NOT the risk clip. A protect stop on
    # a share already held reduces risk, so it is allowed to run on a disarmed,
    # after-hours cycle. That is only safe while the DUPLICATE check can see the
    # real order book, which is why the orders-coverage gate below is not
    # optional: with a blind book this lane posts a second SELL, the exact
    # rejection Schwab returned on 2026-08-30.
    for sym in PROTECT_ONLY:
        spec = protect.get(sym) or protect.get(sym.lower()) or {}
        stop = _f(spec.get("stop"))
        qty = position_qty(book, sym)
        if qty <= 0:
            continue
        if not book_leg_proven(book, "orders"):
            actions.append(
                _action(
                    "skip",
                    sym,
                    "protect_blocked_orders_unproven",
                    {"stop": stop, "source": book.get("source")},
                )
            )
            continue
        # A stop at or above the last trade is not protection, it is a market
        # SELL on the next open. Only checkable when quotes are proven; when
        # they are not we still place, because the duplicate check above is the
        # one that makes this lane safe and it is satisfied.
        last_seen = last_price(book, sym)
        if (
            book_leg_proven(book, "quotes")
            and stop is not None
            and last_seen is not None
            and stop >= last_seen
        ):
            actions.append(
                _action(
                    "skip",
                    sym,
                    "protect_stop_at_or_above_last_would_market_sell",
                    {"stop": stop, "last": last_seen},
                )
            )
            continue
        # NOTE: the second clause is now UNREACHABLE BY CONSTRUCTION. Every
        # fallback_hint book states orders_ok False, so the coverage gate above
        # returns first. It is kept as harmless defense, but say so here: the
        # `already_working` key is live in standing_rules.json (NOK, commented
        # "Do not duplicate"), and a reader who greps for it must not conclude
        # the config still governs a branch that can no longer execute.
        if existing_protect(book, sym) or (
            spec.get("already_working") and book.get("source") == "fallback_hint"
        ):
            actions.append(
                _action(
                    "skip",
                    sym,
                    "protect_already_working",
                    {"stop": stop, "already_working": True},
                )
            )
            continue
        # one-sell law: refuse if any SELL is already working
        existing = existing_sell(book, sym)
        if existing:
            actions.append(
                _action(
                    "skip",
                    sym,
                    "one_sell_law_existing_sell",
                    {
                        "stop": stop,
                        "existing_order_id": existing.get("id") or existing.get("orderId"),
                        "existing_type": existing.get("type") or existing.get("orderType"),
                    },
                )
            )
            continue
        if stop is None:
            actions.append(_action("skip", sym, "protect_stop_missing_in_rules"))
            continue
        actions.append(
            _action(
                "place_protect_stop",
                sym,
                "protect_only_no_adds",
                {
                    "qty": int(qty),
                    "stop": stop,
                    "duration": "GTC",
                    "side": "SELL",
                    "confirm_tonight": bool(spec.get("confirm_tonight")),
                },
            )
        )

    # refuse any add on leftovers even if someone stuffed them into entries
    for sym in PROTECT_ONLY:
        if position_qty(book, sym) > 0 or (entries.get(sym) or {}).get("enabled"):
            # explicit: never emit a buy for leftovers
            pass

    # --- through-cap / no-DAY hygiene on working entries ---
    # No coverage gate needed here: an unproven orders leg yields an empty list,
    # this loop plans nothing, and no DELETE is emitted. Safe by omission — but
    # say so, because "the cancel lane did nothing" and "the cancel lane could
    # not see" are different facts and the log must not conflate them.
    if not book_leg_proven(book, "orders"):
        actions.append(
            _action(
                "skip",
                None,
                "cancel_lane_orders_unproven",
                {"source": book.get("source")},
            )
        )
    for o in book.get("orders") or []:
        if not order_is_working(o) or not order_is_buy_entry(o):
            continue
        sym = order_symbol(o)
        if not sym:
            continue
        # Cancel lane is universe-restricted. A working BUY on anything outside
        # ETHA/IBIT is a human's order — the daemon does not touch it. Protect
        # stops are SELLs and never reach here (order_is_buy_entry), but state
        # the leftover refusal explicitly rather than lean on that.
        if sym not in LIVE_UNIVERSE or sym in PROTECT_ONLY:
            actions.append(
                _action(
                    "skip",
                    sym,
                    "cancel_lane_not_in_live_universe",
                    {"order_id": o.get("id") or o.get("orderId")},
                )
            )
            continue
        spec = entries.get(sym) or {}
        cap = _f(spec.get("cap"))
        last = last_price(book, sym)
        dur = str(o.get("duration") or "").upper()
        working_px = _f(o.get("price") or o.get("limit"))
        oid = o.get("id") or o.get("orderId")

        if cap is not None and last is not None and last > cap:
            actions.append(
                _action(
                    "cancel_abandon",
                    sym,
                    "through_cap_idea_dead",
                    {
                        "order_id": oid,
                        "working_price": working_px,
                        "last": last,
                        "cap": cap,
                        "do_not_reprice_up": True,
                    },
                )
            )
            continue

        if no_day and dur == "DAY":
            actions.append(
                _action(
                    "cancel_abandon",
                    sym,
                    "no_day",
                    {
                        "order_id": oid,
                        "working_price": working_px,
                        "duration": dur,
                    },
                )
            )
            continue

        # working GTC (or unknown) still under cap: leave it. never raise.
        if working_px is not None and cap is not None and working_px > cap:
            actions.append(
                _action(
                    "cancel_abandon",
                    sym,
                    "working_limit_through_cap",
                    {
                        "order_id": oid,
                        "working_price": working_px,
                        "cap": cap,
                        "do_not_reprice_up": True,
                    },
                )
            )
            continue

        actions.append(
            _action(
                "leave",
                sym,
                "working_pullback_under_cap_no_chase",
                {
                    "order_id": oid,
                    "working_price": working_px,
                    "last": last,
                    "cap": cap,
                    "duration": dur or None,
                },
            )
        )

    abandoned = {
        a["symbol"]
        for a in actions
        if a["op"] == "cancel_abandon"
        and a["reason"] in ("through_cap_idea_dead", "working_limit_through_cap")
    }

    # --- new entries ---
    new_risk_blocked = list(box["reasons"])
    if arm_required and not armed:
        new_risk_blocked.append("arm_required")
    if not rth:
        new_risk_blocked.append("outside_rth")
    # Coverage is a precondition for NEW risk, in both directions:
    #   orders  — existing_entry / existing_sell / max_opens all mean "found
    #             something, do not act", so a blind book makes them all pass.
    #   quotes  — last_above_hold_reclaim and through_cap_idea_dead only fire
    #             when last is not None. Blind quotes make both SKIP, and the
    #             entry proceeds. That is the fail-open direction, so it must
    #             block rather than merely log.
    if not book_leg_proven(book, "orders"):
        new_risk_blocked.append("orders_unproven")
    if not book_leg_proven(book, "quotes"):
        new_risk_blocked.append("quotes_unproven")

    for sym in universe:
        if sym not in LIVE_UNIVERSE:
            actions.append(_action("skip", sym, "not_in_live_universe"))
            continue
        if sym in PROTECT_ONLY:
            actions.append(_action("skip", sym, "protect_only_no_entry"))
            continue
        spec = entries.get(sym) or {}
        if not spec.get("enabled", False):
            actions.append(
                _action(
                    "skip",
                    sym,
                    "entry_disabled",
                    {"hold_reclaim": spec.get("hold_reclaim")},
                )
            )
            continue
        hold = spec.get("hold_reclaim")
        last = last_price(book, sym)
        if hold is None and spec.get("require_hold_reclaim"):
            actions.append(_action("skip", sym, "hold_reclaim_null_disabled"))
            continue
        if hold is not None and last is not None and last > float(hold):
            actions.append(
                _action(
                    "skip",
                    sym,
                    "last_above_hold_reclaim",
                    {"last": last, "hold_reclaim": hold},
                )
            )
            continue

        if sym in abandoned:
            actions.append(
                _action(
                    "skip",
                    sym,
                    "through_cap_no_new_entry",
                    {"last": last, "cap": spec.get("cap")},
                )
            )
            continue

        if position_qty(book, sym) > 0:
            actions.append(_action("skip", sym, "already_long_no_add"))
            continue

        # One-sell law on the BRACKET path too. place_gtc_bracket carries an
        # attached child STOP SELL; if a SELL is already working on this symbol
        # Schwab treats it as owning the share and rejects the second one
        # (proven live 2026-08-30). The PROTECT_ONLY loop checked this; the
        # entry loop did not.
        existing_s = existing_sell(book, sym)
        if existing_s:
            actions.append(
                _action(
                    "skip",
                    sym,
                    "one_sell_law_existing_sell",
                    {
                        "existing_order_id": existing_s.get("id")
                        or existing_s.get("orderId"),
                        "existing_type": existing_s.get("type")
                        or existing_s.get("orderType"),
                    },
                )
            )
            continue

        working = existing_entry(book, sym)
        if working and order_symbol(working) not in abandoned:
            dur = str(working.get("duration") or "").upper()
            if not (no_day and dur == "DAY"):
                # already leaving / not chasing
                continue

        if new_risk_blocked:
            actions.append(
                _action("skip", sym, "new_risk_blocked", {"blocked": new_risk_blocked})
            )
            continue

        limit = _f(spec.get("limit"))
        stop = _f(spec.get("stop"))
        cap = _f(spec.get("cap"))
        if limit is None or stop is None:
            actions.append(_action("skip", sym, "entry_incomplete_limit_or_stop"))
            continue
        if cap is not None and last is not None and last > cap:
            actions.append(
                _action(
                    "skip",
                    sym,
                    "through_cap_idea_dead",
                    {"last": last, "cap": cap, "do_not_chase": True},
                )
            )
            continue
        if cap is not None and limit > cap:
            actions.append(
                _action(
                    "skip",
                    sym,
                    "limit_above_cap_refused",
                    {"limit": limit, "cap": cap},
                )
            )
            continue

        qty = clip_qty(
            spec.get("qty"),
            limit,
            stop,
            equity,
            cfg["risk_pct"],
        )
        if qty <= 0:
            actions.append(
                _action(
                    "skip",
                    sym,
                    "qty_clipped_to_zero",
                    {
                        "requested": spec.get("qty"),
                        "equity": equity,
                        "risk_pct": cfg["risk_pct"],
                    },
                )
            )
            continue

        # room for this symbol if it is not already counted
        tentative_opens = box["opens"]
        if existing_entry(book, sym) is None and position_qty(book, sym) <= 0:
            tentative_opens += 1
        if tentative_opens > cfg["max_opens"]:
            actions.append(_action("skip", sym, "max_opens"))
            continue

        actions.append(
            _action(
                "place_gtc_bracket",
                sym,
                "gtc_pullback_attached_stop",
                {
                    "qty": qty,
                    "requested_qty": spec.get("qty"),
                    "limit": limit,
                    "stop": stop,
                    "cap": cap,
                    "duration": "GTC",
                    "side": "BUY",
                    "stop_side": "SELL",
                    "risk_dollars": round(qty * abs(limit - stop), 4),
                },
            )
        )

    return actions


def _order_id_from_location(loc: str) -> str:
    loc = loc or ""
    if "/orders/" in loc:
        return loc.rsplit("/orders/", 1)[-1].split("?")[0]
    return ""


def schwab_post_order(payload: dict) -> dict:
    """POST one Schwab order. Never prints tokens or account hash."""
    if not broker_available():
        return {"http": 0, "error": "broker not on this machine", "order_id": ""}
    sys.path.insert(0, str(BROKER_ROOT))
    os.chdir(BROKER_ROOT)
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(BROKER_ROOT / ".env")
    except Exception:
        pass
    acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "").strip()
    if not acct:
        return {"http": 0, "error": "missing_account_hash", "order_id": ""}
    from src.token_manager import TokenManager  # type: ignore
    import requests  # type: ignore

    token = TokenManager().get_token()
    r = requests.post(
        f"https://api.schwabapi.com/trader/v1/accounts/{acct}/orders",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    loc = r.headers.get("Location") or r.headers.get("location") or ""
    return {"http": r.status_code, "order_id": _order_id_from_location(loc), "error": "" if r.status_code in (200, 201) else (r.text or "")[:180]}


def cancel_by_id(order_id: str | int) -> dict:
    """DELETE /trader/v1/accounts/{hash}/orders/{id}. Never prints tokens."""
    if not broker_available():
        return {"http": 0, "error": "broker not on this machine"}
    sys.path.insert(0, str(BROKER_ROOT))
    os.chdir(BROKER_ROOT)
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(BROKER_ROOT / ".env")
    except Exception:
        pass
    acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "").strip()
    if not acct:
        return {"http": 0, "error": "missing_account_hash"}
    from src.token_manager import TokenManager  # type: ignore
    import requests  # type: ignore

    token = TokenManager().get_token()
    r = requests.delete(
        f"https://api.schwabapi.com/trader/v1/accounts/{acct}/orders/{order_id}",
        headers={"Authorization": "Bearer " + token},
        timeout=30,
    )
    return {"http": r.status_code, "error": "" if r.status_code in (200, 204) else (r.text or "")[:180]}


def place_protect_stop(symbol: str, qty: int, stop: float, **_kwargs: Any) -> dict:
    payload = {
        "orderType": "STOP",
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderStrategyType": "SINGLE",
        "stopPrice": float(stop),
        "orderLegCollection": [
            {
                "instruction": "SELL",
                "quantity": int(qty),
                "instrument": {"symbol": str(symbol).upper(), "assetType": "EQUITY"},
            }
        ],
    }
    return schwab_post_order(payload)


def place_gtc_bracket(
    symbol: str | None = None,
    qty: int | None = None,
    limit: float | None = None,
    stop: float | None = None,
    side: str = "BUY",
    stop_side: str = "SELL",
    post: Any = None,
    **kwargs: Any,
) -> dict:
    """One Schwab mutation: GTC LIMIT + attached GTC STOP (TRIGGER)."""
    if symbol is None:
        symbol = kwargs.get("sym")
    payload = {
        "orderStrategyType": "TRIGGER",
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "LIMIT",
        "price": float(limit),
        "orderLegCollection": [
            {
                "instruction": str(side).upper(),
                "quantity": int(qty),
                "instrument": {"symbol": str(symbol).upper(), "assetType": "EQUITY"},
            }
        ],
        "childOrderStrategies": [
            {
                "orderStrategyType": "SINGLE",
                "session": "NORMAL",
                "duration": "GOOD_TILL_CANCEL",
                "orderType": "STOP",
                "stopPrice": float(stop),
                "orderLegCollection": [
                    {
                        "instruction": str(stop_side).upper(),
                        "quantity": int(qty),
                        "instrument": {"symbol": str(symbol).upper(), "assetType": "EQUITY"},
                    }
                ],
            }
        ],
    }
    fn = post or schwab_post_order
    return fn(payload)


def fallback_book(rules: dict) -> dict:
    """Hint book for the box (no spiral-broker). Not a live Schwab snapshot.

    THIS BOOK ANSWERS NO GATE IT CANNOT ANSWER HONESTLY.

    It used to hardcode `in_rth: True` and take `armed` from `armed_hint` in
    standing_rules.json. plan_actions reads both from the book, so a config
    file was answering two gates that belong to the wall clock and to
    session_armed(). On the Studio that was live: armed_hint is true while
    config/mv_session.json expired 2026-08-31, so a hint book substituted on a
    transient accounts-endpoint failure yielded armed=True, in_rth=True and an
    empty order list — enough to plan a live IBIT BUY outside RTH on an expired
    arm, duplicating a working order whose own rules comment reads
    "Do not duplicate."

    Both keys are therefore ABSENT, not False: every reader (plan_actions :414,
    run_cycle, gate_outbox_ticket) already falls back to the real in_rth() when
    the key is missing, and resolve_book stamps the real session_armed(). The
    coverage flags are stated False rather than omitted so the semantics are
    declared at the point of construction, not inferred by a reader.
    """
    protect = rules.get("protect") or {}
    positions = []
    for sym in PROTECT_ONLY:
        if protect.get(sym):
            positions.append({"symbol": sym, "qty": 1})
    return {
        "equity": _f(rules.get("equity_hint")),
        "peak_equity": _f(rules.get("peak_hint") or rules.get("equity_hint")),
        "sod_equity": _f(rules.get("equity_hint")),
        "day_pnl": 0.0,
        "cash": None,
        "positions": positions,
        "orders": [],
        "quotes": {},
        "orders_ok": False,
        "quotes_ok": False,
        "source": "fallback_hint",
    }


def fetch_book() -> tuple[dict | None, str]:
    """Read-only Schwab book. Never prints tokens, account hash, or secrets.

    UNTESTED SURFACE, named so the next reader does not mistake the green suite
    for coverage: the Schwab-JSON-to-internal mapping below (positions, orders,
    quotes) is exercised by NO test — every test hands the planner a hand-built
    book. The emitted field names are the contract the rest of this file reads
    ("price", "qty", "stopPrice", "duration", "status", "legs"); the downstream
    helpers agree with them today. A partial read used to be invisible here,
    which is one instance of this surface failing quietly.
    """
    if not broker_available():
        return None, "broker not on this machine"
    try:
        sys.path.insert(0, str(BROKER_ROOT))
        os.chdir(BROKER_ROOT)
        try:
            from dotenv import load_dotenv  # type: ignore

            load_dotenv(BROKER_ROOT / ".env")
        except Exception:
            env_path = BROKER_ROOT / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        from src.token_manager import TokenManager  # type: ignore
        import requests  # type: ignore

        tm = TokenManager()
        st = tm.get_token_status()
        safe = {
            k: st.get(k)
            for k in ("status", "refresh_valid", "access_valid")
            if isinstance(st, dict)
        }
        if isinstance(st, dict) and (
            st.get("status") == "refresh_expired" or st.get("refresh_valid") is False
        ):
            return None, f"oauth_required status={safe.get('status')}"

        token = tm.get_token()
        acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "")
        if not acct:
            return None, "missing_account_hash"
        headers = {"Authorization": "Bearer " + token}
        base = "https://api.schwabapi.com"

        def get(path: str, params: dict | None = None):
            return requests.get(base + path, headers=headers, params=params, timeout=30)

        r = get("/trader/v1/accounts", {"fields": "positions"})
        if r.status_code != 200:
            return None, f"accounts_http={r.status_code}"
        raw = r.json()
        positions = []
        equity = cash = sod = None
        for item in raw if isinstance(raw, list) else [raw]:
            a = item.get("securitiesAccount") or item.get("account") or item
            cb = a.get("currentBalances") or {}
            ib = a.get("initialBalances") or {}
            equity = cb.get("liquidationValue") or cb.get("equity") or equity
            cash = cb.get("cashBalance") or cb.get("availableFunds") or cash
            sod = ib.get("liquidationValue") or ib.get("equity") or sod
            for p in a.get("positions") or []:
                inst = p.get("instrument") or {}
                positions.append(
                    {
                        "symbol": inst.get("symbol"),
                        "qty": p.get("longQuantity") or p.get("quantity"),
                        "avg": p.get("averagePrice"),
                        "mv": p.get("marketValue"),
                        "dayPL": p.get("currentDayProfitLoss"),
                    }
                )

        now = datetime.now(timezone.utc)
        frm = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        orders: list[dict] = []
        ro = get(
            "/trader/v1/accounts/" + acct + "/orders",
            {"fromEnteredTime": frm, "toEnteredTime": to, "maxResults": 50},
        )
        # Coverage, not emptiness. A non-200 here leaves orders == [], which is
        # indistinguishable from "nothing is working" to every book-derived
        # guard downstream. State the leg's status on the book instead.
        orders_ok = ro.status_code == 200
        if orders_ok:
            data = ro.json()
            data = data if isinstance(data, list) else (data.get("orders") or [])
            for o in data:
                legs = [
                    {
                        "instruction": leg.get("instruction"),
                        "symbol": (leg.get("instrument") or {}).get("symbol"),
                        "qty": leg.get("quantity"),
                    }
                    for leg in (o.get("orderLegCollection") or [])
                ]
                orders.append(
                    {
                        "id": o.get("orderId"),
                        "status": o.get("status"),
                        "type": o.get("orderType"),
                        "price": o.get("price"),
                        "stopPrice": o.get("stopPrice"),
                        "duration": o.get("duration"),
                        "qty": o.get("quantity"),
                        "filledQty": o.get("filledQuantity"),
                        "remaining": o.get("remainingQuantity"),
                        "legs": legs,
                        "symbol": (legs[0].get("symbol") if legs else None),
                        "side": (
                            "BUY"
                            if any("BUY" in str(x.get("instruction") or "") for x in legs)
                            else "SELL"
                            if any("SELL" in str(x.get("instruction") or "") for x in legs)
                            else ""
                        ),
                    }
                )

        quotes: dict = {}
        rq = get("/marketdata/v1/quotes", {"symbols": "ETHA,IBIT,NVO,NOK"})
        quotes_ok = rq.status_code == 200
        quotes_as_of = now_et().isoformat() if quotes_ok else None
        if quotes_ok:
            q = rq.json()
            for sym, rec in (q.items() if isinstance(q, dict) else []):
                if not isinstance(rec, dict):
                    continue
                quote = rec.get("quote") or rec
                quotes[sym] = {
                    "last": quote.get("lastPrice") or quote.get("mark"),
                    "mark": quote.get("mark"),
                    "bid": quote.get("bidPrice"),
                    "ask": quote.get("askPrice"),
                    # WHEN THE PRICE WAS MADE, not when we read it. The read
                    # stamp above is always ~0 minutes old on a daemon cycle
                    # (the book is fetched once and handed straight to the
                    # gates), so a freshness gate built on it alone could never
                    # fire — experimental law #2, a gate that cannot fail is
                    # not a gate. Schwab's own quote/trade time is what catches
                    # a halted symbol, a frozen feed or a pre-market read.
                    # Epoch ms; absent on some payloads, which is why
                    # quote_age_minutes takes the OLDER of the two it can see.
                    "quote_time": quote.get("quoteTime") or quote.get("tradeTime"),
                }

        day_pnl = None
        if equity is not None and sod is not None:
            try:
                day_pnl = float(equity) - float(sod)
            except (TypeError, ValueError):
                day_pnl = None

        book = {
            "equity": _f(equity),
            "peak_equity": _f(equity),
            "sod_equity": _f(sod),
            "day_pnl": day_pnl,
            "cash": _f(cash),
            "armed": session_armed(),
            "positions": positions,
            "orders": orders,
            "quotes": quotes,
            "orders_ok": orders_ok,
            "quotes_ok": quotes_ok,
            # ET ISO stamp of the READ, present only when the quotes leg
            # proved. Absent is not permission: quote_age_minutes returns None
            # and a `validity` ticket WAITS rather than re-deciding blind.
            "quotes_as_of": quotes_as_of,
            "source": "schwab_read",
            "token_safe": safe,
        }
        if not (orders_ok and quotes_ok):
            logj(
                {
                    "op": "book_partial",
                    "orders_ok": orders_ok,
                    "orders_http": ro.status_code,
                    "quotes_ok": quotes_ok,
                    "quotes_http": rq.status_code,
                    "note": "book-derived gates refuse on the unproven leg",
                    "sent": False,
                    "mutated": False,
                }
            )
        return book, "schwab_read"
    except Exception as e:
        return None, f"broker_error:{type(e).__name__}"


def _broker_auth() -> dict:
    """Schwab auth bootstrap for the read-only marketdata calls. Never raises.

    Returns {"ok": bool, "headers": dict, "base": str, "note": str}. A dict and
    not a (value, reason) tuple on purpose: the refusal-classification tripwire
    scans every function that returns a string-literal tuple, and a note from a
    read helper is not a ticket refusal reason.

    DELIBERATE DUPLICATION OF fetch_book's BOOTSTRAP, and it is not laziness.
    fetch_book's Schwab-JSON mapping is exercised by NO test (it says so in its
    own docstring); collapsing the two into one helper is an edit to the live
    read path that the suite cannot verify. Documented duplication beats an
    unverifiable refactor on a money wire. If you DO collapse them, do it with
    a test harness for fetch_book in the same commit. The two copies must stay
    in step: token path, .env load, account hash, base URL.
    """
    if not broker_available():
        return {"ok": False, "headers": {}, "base": "", "note": "broker not on this machine"}
    try:
        # Guarded, unlike fetch_book's unconditional insert: this runs once per
        # symbol per off-hours cycle AND again on every validity refetch, so an
        # unguarded insert grows sys.path without bound in any process that
        # does not exit. The daemon is `--once` and exits each tick, so nothing
        # accumulates in production today — the guard is what keeps that true
        # if the wire is ever driven from a long-lived loop.
        if str(BROKER_ROOT) not in sys.path:
            sys.path.insert(0, str(BROKER_ROOT))
        os.chdir(BROKER_ROOT)
        try:
            from dotenv import load_dotenv  # type: ignore

            load_dotenv(BROKER_ROOT / ".env")
        except Exception:
            env_path = BROKER_ROOT / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        from src.token_manager import TokenManager  # type: ignore

        tm = TokenManager()
        st = tm.get_token_status()
        if isinstance(st, dict) and (
            st.get("status") == "refresh_expired" or st.get("refresh_valid") is False
        ):
            return {
                "ok": False,
                "headers": {},
                "base": "",
                "note": "oauth_required status=" + str(st.get("status")),
            }
        token = tm.get_token()
        return {
            "ok": True,
            "headers": {"Authorization": "Bearer " + token},
            "base": "https://api.schwabapi.com",
            "note": "schwab_auth_ok",
        }
    except Exception as e:
        return {
            "ok": False,
            "headers": {},
            "base": "",
            "note": "broker_error:" + type(e).__name__,
        }


def fetch_daily_history(
    symbol: str, days: int = HISTORY_DAYS, timeout: float = HISTORY_TIMEOUT_S
) -> dict:
    """Read-only daily candles for one symbol. Never posts, never mutates.

    `timeout` is a parameter and not a constant because the two callers sit in
    different lanes with different costs for waiting. The off-hours planner has
    the whole night; the re-evaluation refetch inside gate_outbox_ticket runs
    DURING RTH and BEFORE plan_actions in run_cycle, so every second it blocks
    is a second a protect stop is not being placed. See
    HISTORY_TIMEOUT_REEVAL_S.

    COVERAGE IS STATED, exactly like the book's legs: the return always carries
    `history_ok`, and absence of proof is not permission. A failed call yields
    `history_ok: False` with an empty candle list, never a silent [] that a
    caller could read as "the trend is flat". Same fail-closed contract as
    book_leg_proven.

    Returns:
        {"symbol", "candles": [{"datetime","open","high","low","close","volume"}],
         "history_ok": bool, "as_of": ISO ET or None, "bars": int, "note": str}

    `days` trims the TAIL of a one-year daily pull rather than doing date math
    against the exchange calendar: sessions are not days, and a startDate in
    epoch-ms that lands on a holiday is a silent short read. One HTTP call
    either way.

    INJECTABLE: every caller reaches this through the module global, so a test
    swaps it with temple_flow_wire.fetch_daily_history = fake. The suite is run
    with SPIRAL_BROKER_ROOT=/nonexistent, so even an unpatched call returns at
    the broker_available() guard in _broker_auth without touching the network.
    """
    out = {
        "symbol": str(symbol).upper(),
        "candles": [],
        "history_ok": False,
        "as_of": None,
        "bars": 0,
        "note": "",
    }
    auth = _broker_auth()
    if not auth.get("ok"):
        out["note"] = str(auth.get("note") or "auth_unavailable")
        return out
    try:
        import requests  # type: ignore

        r = requests.get(
            auth["base"] + "/marketdata/v1/pricehistory",
            headers=auth["headers"],
            params={
                "symbol": out["symbol"],
                "periodType": "year",
                "period": 1,
                "frequencyType": "daily",
                "frequency": 1,
                "needExtendedHoursData": "false",
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            out["note"] = "pricehistory_http=" + str(r.status_code)
            return out
        raw = r.json()
        if not isinstance(raw, dict) or raw.get("empty") is True:
            out["note"] = "pricehistory_empty"
            return out
        candles = []
        for c in raw.get("candles") or []:
            if not isinstance(c, dict):
                continue
            close = _f(c.get("close"))
            if close is None:
                continue
            candles.append(
                {
                    "datetime": c.get("datetime"),
                    "open": _f(c.get("open")),
                    "high": _f(c.get("high")),
                    "low": _f(c.get("low")),
                    "close": close,
                    "volume": c.get("volume"),
                }
            )
        if not candles:
            out["note"] = "pricehistory_no_usable_candles"
            return out
        try:
            n = int(days)
        except (TypeError, ValueError):
            n = HISTORY_DAYS
        if n > 0:
            candles = candles[-n:]
        out["candles"] = candles
        out["bars"] = len(candles)
        out["history_ok"] = True
        out["as_of"] = now_et().isoformat()
        out["last_bar_at"] = candles[-1].get("datetime")
        out["note"] = "schwab_pricehistory"
        return out
    except Exception as e:
        out["note"] = "history_error:" + type(e).__name__
        return out


# --- feature math ----------------------------------------------------------
# Pure, no network, no clock. Every one of these returns None rather than
# raising or substituting a plausible number: a feature the daemon could not
# compute must read as UNKNOWN downstream, because check_conditions() treats an
# unknown as False and a missing feature must never look like a passing one.


def closes_of(candles: list) -> list:
    """Closing prices, in order, skipping any candle without a usable close."""
    out = []
    for c in candles or []:
        v = _f((c or {}).get("close")) if isinstance(c, dict) else None
        if v is not None:
            out.append(v)
    return out


def sma(values: list, n: int) -> float | None:
    """Simple mean of the last n values. None when there are fewer than n."""
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / float(n)


def sma_slope(values: list, n: int, lookback: int) -> float | None:
    """Per-day change of the n-period SMA over `lookback` sessions.

    (sma_now - sma_lookback_ago) / lookback, in dollars per day. Needs
    n + lookback values; None below that rather than a slope off a short window.
    """
    if n <= 0 or lookback <= 0 or len(values) < n + lookback:
        return None
    now_sma = sma(values, n)
    then_sma = sma(values[: len(values) - lookback], n)
    if now_sma is None or then_sma is None:
        return None
    return (now_sma - then_sma) / float(lookback)


def atr(candles: list, n: int) -> float | None:
    """SIMPLE n-period mean of the true range. Not Wilder's smoothing.

    TR = max(high-low, |high - prev_close|, |low - prev_close|). Needs n+1
    candles (the first TR needs a previous close). None if any of the last n
    bars is missing a high, low or close — a partial ATR sizes a stop wrong,
    and the stop is the only thing standing between the account and the trade.
    """
    if n <= 0 or len(candles or []) < n + 1:
        return None
    trs: list = []
    for i in range(len(candles) - n, len(candles)):
        cur = candles[i] if isinstance(candles[i], dict) else {}
        prev = candles[i - 1] if isinstance(candles[i - 1], dict) else {}
        hi = _f(cur.get("high"))
        lo = _f(cur.get("low"))
        prev_close = _f(prev.get("close"))
        if hi is None or lo is None or prev_close is None:
            return None
        trs.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))
    if len(trs) != n:
        return None
    return sum(trs) / float(n)


def window_return(values: list, n: int) -> float | None:
    """(last - value n sessions ago) / that value, from CLOSES only.

    Uses closes rather than the live quote on purpose: a 5-day return that
    moves every 900s is not a 5-day return, and the plan file must be
    re-derivable hours later from the same candles.
    """
    if n <= 0 or len(values) < n + 1:
        return None
    base = values[-(n + 1)]
    if base == 0:
        return None
    return (values[-1] - base) / base


def quote_freshness(
    book: dict, symbol: str, now: datetime | None = None
) -> dict:
    """How old this symbol's price is AND WHICH CLOCK SAID SO.

    Returns {"age_minutes", "read_stamp_age", "quote_time_age",
             "read_stamp_seen", "quote_time_seen"} — every key on every call.

    THE OLDER OF TWO CLOCKS, and they are not interchangeable:
      * `book["quotes_as_of"]` — when the daemon READ the quotes leg. fetch_book
        stamps it now_et() at :1314, so on a daemon cycle it is always ~0
        minutes. It is a real fact and it is nearly useless as a freshness
        signal: it says the read happened, never that the price is current.
      * `quotes[sym]["quote_time"]` — Schwab's own quote/trade stamp. THIS is
        the clock that fires on a halted symbol, a frozen feed or a pre-market
        read, which is the case Anthony's "time sensitive data" names.

    WHY THE BOOLEANS EXIST, and they are the point of this function rather than
    a convenience: `max(ages)` over "whatever parsed" cannot distinguish
    "measured both clocks, both fresh" from "the per-symbol stamp was absent so
    the inert read clock answered alone and of course said ~0". The second is a
    gate reporting freshness it never measured — fail-open, the failure class
    this wire hunts. Callers that must not decide blind read `quote_time_seen`
    and refuse when it is False.

    `*_seen` IS SET FROM A PARSED AGE, NEVER FROM KEY PRESENCE. A stamp that is
    there but unparseable — a string that is not ISO, a non-numeric, an epoch
    out of range — leaves the flag False, because an unreadable clock measured
    nothing. Setting it from `"quote_time" in q` would rebuild the same
    fail-open one layer in.

    A stamp in the future (broker clock skew) is clamped to 0 rather than
    folded through abs() — skew is not staleness.
    """
    t_now = now_et(now)
    out: dict = {
        "age_minutes": None,
        "read_stamp_age": None,
        "quote_time_age": None,
        "read_stamp_seen": False,
        "quote_time_seen": False,
    }
    stamp = book.get("quotes_as_of") if isinstance(book, dict) else None
    if stamp:
        try:
            out["read_stamp_age"] = (
                t_now - _parse_ticket_time(stamp)
            ).total_seconds() / 60.0
            out["read_stamp_seen"] = True
        except (ValueError, TypeError):
            pass
    q = (book.get("quotes") or {}).get(symbol) if isinstance(book, dict) else None
    if isinstance(q, dict):
        raw = q.get("quote_time")
        if isinstance(raw, str) and raw.strip():
            try:
                out["quote_time_age"] = (
                    t_now - _parse_ticket_time(raw)
                ).total_seconds() / 60.0
                out["quote_time_seen"] = True
            except (ValueError, TypeError):
                pass
        else:
            epoch = _f(raw)
            if epoch is not None and epoch > 0:
                # ms since epoch above ~1e11, seconds below it
                seconds = epoch / 1000.0 if epoch > 1e11 else epoch
                try:
                    when = datetime.fromtimestamp(seconds, tz=timezone.utc)
                    out["quote_time_age"] = (
                        t_now - when.astimezone(ET)
                    ).total_seconds() / 60.0
                    out["quote_time_seen"] = True
                except (OverflowError, OSError, ValueError):
                    pass
    ages = [
        a
        for a in (out["read_stamp_age"], out["quote_time_age"])
        if a is not None
    ]
    if ages:
        out["age_minutes"] = max(0.0, max(ages))
    return out


def quote_age_minutes(
    book: dict, symbol: str, now: datetime | None = None
) -> float | None:
    """Minutes since this symbol's price was TRUE. None when unknowable.

    The OLDER of the two clocks quote_freshness() reads. None means NEITHER
    stamp was readable, and a caller must treat that as stale rather than
    fresh: a book that does not state when it was true has not proven
    freshness, and absence of proof is not permission.

    THIS NUMBER ALONE IS NOT A FRESHNESS VERDICT on a live wire. It cannot say
    which clock produced it, and the read clock is ~0 on every daemon cycle, so
    a gate built on this return value alone reports FRESH whenever the
    per-symbol stamp is missing. Use quote_freshness() and check
    `quote_time_seen` wherever a refusal depends on the answer; this wrapper is
    for logging and for callers that already know they are looking at both.
    """
    return quote_freshness(book, symbol, now)["age_minutes"]


def compute_features(symbol: str, book: dict, history: dict, rules: dict) -> dict:
    """The legible feature set one symbol is judged on. Pure.

    Every key is present on every call, set to None when it could not be
    computed, so the plan file shows the same shape for a symbol that produced
    a candidate and one that did not.
    """
    p = strategy.params(rules)
    sym = str(symbol).upper()
    candles = (history or {}).get("candles") or []
    closes = closes_of(candles)
    entry_spec = (rules.get("entries") or {}).get(sym) or {}
    cap = _f(entry_spec.get("cap"))
    last = last_price(book, sym) if book_leg_proven(book, "quotes") else None

    fast = int(p["sma_fast"])
    slow = int(p["sma_slow"])
    sma_fast = sma(closes, fast)
    sma_slow = sma(closes, slow)
    working = existing_entry(book, sym) if book_leg_proven(book, "orders") else None

    feats = {
        "symbol": sym,
        "last": last,
        "cap": cap,
        "bars": len(closes),
        "sma20": sma_fast,
        "sma50": sma_slow,
        "sma20_slope": sma_slope(closes, fast, int(p["slope_lookback"])),
        "sma50_slope": sma_slope(closes, slow, int(p["slope_lookback"])),
        "atr14": atr(candles, int(p["atr_period"])),
        "ret5d": window_return(closes, 5),
        "last_vs_cap": (
            round(last - cap, 4) if (last is not None and cap is not None) else None
        ),
        "dist_to_sma20_pct": (
            (last - sma_fast) / sma_fast
            if (last is not None and sma_fast not in (None, 0))
            else None
        ),
        "position_qty": position_qty(book, sym),
        "has_working_entry": working is not None,
        "working_entry_id": (
            (working.get("id") or working.get("orderId")) if working else None
        ),
        "history_ok": bool((history or {}).get("history_ok")),
        "history_as_of": (history or {}).get("as_of"),
        "quotes_ok": book_leg_proven(book, "quotes"),
        "quote_as_of": book.get("quotes_as_of"),
        "sma_fast_period": fast,
        "sma_slow_period": slow,
        "atr_period": int(p["atr_period"]),
        "slope_lookback": int(p["slope_lookback"]),
    }
    return feats


def _cancel_refusal_path(repo_root: Path | None = None) -> Path:
    return (repo_root or REPO_ROOT).joinpath(*CANCEL_REFUSAL_STATE)


def load_cancel_refusals(repo_root: Path | None = None) -> dict:
    """{order_id: 'YYYY-MM-DD'} — the ET day Schwab last refused that cancel."""
    p = _cancel_refusal_path(repo_root)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
    except Exception as e:
        logj(
            {
                "op": "cancel_refusal_state",
                "execute": "unreadable",
                "error": type(e).__name__,
                "path": str(p),
                "sent": False,
                "mutated": False,
            }
        )
        return {}
    return d if isinstance(d, dict) else {}


def record_cancel_refusal(
    order_id: str | int,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> None:
    """Persist a 400 so the same order is not re-DELETEd every 900s."""
    p = _cancel_refusal_path(repo_root)
    state = load_cancel_refusals(repo_root)
    state[str(order_id)] = now_et(now).strftime("%Y-%m-%d")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, p)
    except Exception as e:
        logj(
            {
                "op": "cancel_refusal_state",
                "execute": "write_failed",
                "error": type(e).__name__,
                "path": str(p),
                "order_id": str(order_id),
                "sent": False,
                "mutated": False,
            }
        )


def cancel_refused_today(
    order_id: str | int,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> bool:
    return load_cancel_refusals(repo_root).get(str(order_id)) == now_et(now).strftime(
        "%Y-%m-%d"
    )


def execute_action(
    action: dict,
    live: bool,
    rth: bool | None = None,
    repo_root: Path | None = None,
    now: datetime | None = None,
    book: dict | None = None,
) -> dict:
    """Apply one planned action. Dry-run never marks sent.

    `sent` = an order was PLACED. `mutated` = broker state changed (place OR
    cancel). A cancel reports execute='canceled' + mutated=True, never sent.

    `book` is REQUIRED for live=True. It is the execute-boundary copy of the
    planner's checks: defense in depth, so this function cannot be handed an
    action derived from a hint book (or, later, from a caller that is not
    run_cycle) and fire it at the broker anyway.
    """
    out = deepcopy(action)
    out["dry_run"] = not live
    out["sent"] = False
    out.setdefault("mutated", False)
    out["mutated"] = False
    if not live:
        out["execute"] = "dry_run"
        return out
    op = action.get("op")
    params = dict(action.get("params") or {})
    params["symbol"] = action.get("symbol")

    # Nothing mutates on a book that is not a proven Schwab read.
    if op in ("place_gtc_bracket", "place_protect_stop", "cancel_abandon"):
        eligible, why = book_is_live_eligible(book)
        if not eligible:
            out["execute"] = "refused"
            out["reason"] = why
            return out

    # Universe restriction, mirrored from the planner. plan_actions already
    # refuses a cancel outside ETHA/IBIT, but the same was true of
    # execute_outbox_ticket before the PR shipped it to a live daemon: a check
    # that lives in exactly one caller is one refactor from being gone.
    sym_now = str(action.get("symbol") or "").upper()
    if op == "cancel_abandon" and (
        sym_now not in LIVE_UNIVERSE or sym_now in PROTECT_ONLY
    ):
        out["execute"] = "refused"
        out["reason"] = "cancel_symbol_not_in_live_universe"
        return out
    if op == "place_gtc_bracket":
        res = place_gtc_bracket(**params)
        out["schwab"] = {k: res.get(k) for k in ("http", "order_id", "error")}
        out["sent"] = res.get("http") in (200, 201)
        out["mutated"] = out["sent"]
        out["execute"] = "posted" if out["sent"] else "post_failed"
        return out
    if op == "place_protect_stop":
        res = place_protect_stop(**params)
        out["schwab"] = {k: res.get(k) for k in ("http", "order_id", "error")}
        out["sent"] = res.get("http") in (200, 201)
        out["mutated"] = out["sent"]
        out["execute"] = "posted" if out["sent"] else "post_failed"
        return out
    if op == "cancel_abandon":
        order_id = params.get("order_id")
        if not order_id:
            out["execute"] = "cancel_failed_no_order_id"
            return out
        # RTH gate: a cancel of a PENDING_ACTIVATION order after hours returns
        # 400 (proven live 2026-08-30). Plan it, do not fire it.
        rth_now = in_rth(now) if rth is None else bool(rth)
        if not rth_now:
            out["execute"] = "cancel_deferred_outside_rth"
            return out
        # A 400 already logged today is not retried until the next trading day.
        if cancel_refused_today(order_id, repo_root, now):
            out["execute"] = "cancel_skipped_refused_today"
            return out
        res = cancel_by_id(order_id)
        out["schwab"] = {k: res.get(k) for k in ("http", "error")}
        if res.get("http") in (200, 204):
            out["mutated"] = True
            out["execute"] = "canceled"
            record_in_cycle_cancel(book, order_id)
        elif res.get("http") == 400:
            record_cancel_refusal(order_id, repo_root, now)
            out["execute"] = "cancel_refused_400_after_hours"
        else:
            out["execute"] = "cancel_failed"
        return out
    out["execute"] = "no_mutation"
    return out


# --- off-hours planning lane ------------------------------------------------
# Anthony, 2026-09-03 07:49 EDT: "on market off hours, there should be more
# strategy being defined and planning on the trends."
#
# THE PLANNER PLACES NO ORDERS. It reads, it computes, it writes one JSON file
# to config/plans/, and it prints. The only path from that file to the outbox
# is a human running --approve-plan. Nothing here touches config/outbox/, and
# the whole lane runs OUTSIDE RTH only: during the session the daemon's job is
# to execute what was already approved, not to think up new trades.


def plan_dir(repo_root: Path | None = None) -> Path:
    return (repo_root or REPO_ROOT).joinpath(*PLAN_DIR)


def plan_file_path(repo_root: Path | None = None, now: datetime | None = None) -> Path:
    """config/plans/<YYYY-MM-DD>_<HHMM>.json, from the cycle's own clock.

    Minute resolution, so a hand-run and a daemon tick in the same minute write
    the same path and the later one WINS. That is deliberate and harmless: both
    are read-only proposals derived from the same rules, and a plan is only
    ever consumed by a human naming it explicitly.
    """
    t = now_et(now)
    return plan_dir(repo_root) / (t.strftime("%Y-%m-%d_%H%M") + ".json")


def size_candidate(candidate: dict, rules: dict, equity: float | None) -> dict:
    """Turn a strategy proposal into a share count. THE RISK LAW LIVES HERE.

    The strategy proposes prices and may hint a size; this function is the only
    thing that decides how many shares, and it uses the SAME primitives the
    outbox gate will re-apply minutes later — `clip_qty` with `risk.risk_pct`,
    and `ticket_notional_cap`. Sizing here with the gate's own tools is what
    keeps the planner from writing tickets that die at their own gate.

    Returns {"qty": int, ...}; qty 0 carries `reason`, which is the string the
    plan file records as the decision. `qty_hint` can only shrink the result.
    """
    limit = _f(candidate.get("limit"))
    stop = _f(candidate.get("stop"))
    out: dict = {"qty": 0, "limit": limit, "stop": stop, "equity": equity}
    if limit is None or stop is None or limit <= 0 or stop <= 0:
        out["reason"] = "candidate_prices_unusable"
        return out
    if stop >= limit:
        out["reason"] = "stop_not_below_limit"
        return out
    if equity is None or equity <= 0:
        out["reason"] = "equity_unknown"
        return out
    cfg = _risk(rules)
    out["risk_pct"] = cfg["risk_pct"]
    per_share = limit - stop
    qty = int((equity * cfg["risk_pct"]) // per_share)
    cap_notional = ticket_notional_cap(rules, equity)
    out["max_ticket_notional"] = cap_notional
    if cap_notional is None:
        out["reason"] = "notional_cap_uncomputable"
        return out
    qty = min(qty, int(cap_notional // limit))
    hint = candidate.get("qty_hint")
    if isinstance(hint, int) and not isinstance(hint, bool) and hint > 0:
        qty = min(qty, hint)
    # clip_qty is the authority, not a second opinion: it is the exact call the
    # gate makes, so a ticket this planner writes cannot exceed the clip.
    qty = clip_qty(qty, limit, stop, equity, cfg["risk_pct"])
    if qty <= 0:
        out["reason"] = "qty_clipped_to_zero"
        return out
    out["qty"] = qty
    out["notional"] = round(qty * limit, 4)
    out["risk_dollars"] = round(qty * per_share, 4)
    return out


def build_plan(
    rules: dict,
    book: dict,
    repo_root: Path | None = None,
    now: datetime | None = None,
    rules_path: str = "",
) -> dict:
    """Read-only pass over LIVE_UNIVERSE. Returns the plan dict; writes nothing.

    Iterates the MODULE constant LIVE_UNIVERSE, minus PROTECT_ONLY — not
    `rules["universe"]`. The outbox gate checks the module constant, so a
    planner honouring the rules field could emit a ticket that dies at its own
    gate with `not_in_live_universe`. One universe, one answer.
    """
    t_now = now_et(now)
    p = strategy.params(rules)
    equity = _f(book.get("equity"))
    box = risk_box(rules, book)
    stamp = t_now.strftime("%Y%m%d-%H%M")
    plan: dict = {
        "schema": "temple_flow_plan_v1",
        "planned_at": t_now.isoformat(),
        "planner": "temple_flow_wire.build_plan",
        "strategy_module": "temple_flow_strategy",
        "strategy_params": p,
        "rules_path": rules_path,
        "equity": equity,
        "in_rth": False,
        "book_source": book.get("source"),
        "coverage": {
            "quotes_ok": book_leg_proven(book, "quotes"),
            "orders_ok": book_leg_proven(book, "orders"),
            "history_ok": {},
        },
        "data_as_of": {"quotes": book.get("quotes_as_of"), "history": {}},
        "risk_box": {"ok": box["ok"], "reasons": box["reasons"], "opens": box["opens"]},
        "symbols": {},
        "candidates": [],
        "note": (
            "READ-ONLY PROPOSAL. The planner places no orders and never writes "
            "to config/outbox/. Approve one candidate with: "
            "temple_flow_wire.py --approve-plan <this file> <ticket id>"
        ),
    }

    for sym in LIVE_UNIVERSE:
        if sym in PROTECT_ONLY:
            continue
        entry: dict = {"decision": "none", "reason": "", "ticket": None}

        # 0. the risk box. Its max_opens clause is NOT day-scoped (see the
        #    WAIT_REFUSALS docstring): count_opens counts distinct symbols
        #    holding a position or a working entry, so a saturated box is a
        #    structural state that tomorrow does not clear. Proposing into it
        #    puts a candidate in front of a human that cannot execute today or
        #    tomorrow. The box is already computed above; this spends nothing.
        if not box["ok"]:
            entry["reason"] = "risk_box_blocked"
            entry["risk_box"] = box["reasons"]
            entry["features"] = compute_features(sym, book, {}, rules)
            plan["symbols"][sym] = entry
            continue

        # 1. quotes. No live price, no idea — and a blind quotes leg is the
        #    fail-open direction (every price test below only fires when `last`
        #    is known), so it is answered before anything is fetched.
        if not book_leg_proven(book, "quotes") or last_price(book, sym) is None:
            entry["reason"] = "quotes_unproven"
            entry["features"] = compute_features(sym, book, {}, rules)
            plan["symbols"][sym] = entry
            continue

        # 1b. orders. THE SAME FAIL-OPEN SHAPE AS THE QUOTES LEG, one lane over,
        #    and it was live until 2026-09-04. compute_features sets
        #    has_working_entry from `existing_entry(...) if
        #    book_leg_proven(book, "orders") else None`, so an UNPROVEN orders
        #    leg yields False, and strategy.check_conditions then computes
        #    no_open_exposure = pos <= 0 and not has_working_entry = TRUE. The
        #    plan file would assert "nothing is open on this symbol" on a cycle
        #    where the daemon COULD NOT LOOK — the exact inversion the strategy
        #    contract forbids at temple_flow_strategy.py:168-170 ("a missing
        #    feature makes its condition FALSE, never True").
        #
        #    No wrong order could reach Schwab through it (gate_outbox_ticket
        #    refuses `orders_unproven` before anything posts), so the cost was
        #    a false statement in front of the human whose approval is the
        #    money door. That is reason enough: the plan file is the document
        #    the approval is given ON.
        if not book_leg_proven(book, "orders"):
            entry["reason"] = "orders_unproven"
            entry["features"] = compute_features(sym, book, {}, rules)
            plan["symbols"][sym] = entry
            continue

        # 2. history. Coverage stated, never inferred from an empty list.
        history = fetch_daily_history(sym, HISTORY_DAYS)
        plan["coverage"]["history_ok"][sym] = bool(history.get("history_ok"))
        plan["data_as_of"]["history"][sym] = history.get("as_of")
        features = compute_features(sym, book, history, rules)
        entry["features"] = features
        if not history.get("history_ok"):
            entry["reason"] = "history_unproven"
            entry["history_note"] = history.get("note")
            plan["symbols"][sym] = entry
            continue
        if features["bars"] < MIN_HISTORY_BARS:
            # A DIFFERENT FACT from history_unproven: the read succeeded and
            # the answer is "not enough sessions to judge". Never merge them.
            entry["reason"] = "insufficient_history"
            entry["bars_needed"] = MIN_HISTORY_BARS
            plan["symbols"][sym] = entry
            continue

        # 3. the strategy seam. checks are recorded either way, so a plan says
        #    WHY it declined and not merely that it did.
        checks = {}
        if hasattr(strategy, "check_conditions"):
            checks = strategy.check_conditions(sym, features, rules)
            entry["checks"] = checks
        candidate = strategy.evaluate(sym, features, rules)
        if not candidate:
            failed = sorted(k for k, v in (checks or {}).items() if not v)
            entry["reason"] = "strategy_declined"
            entry["failed_checks"] = failed
            plan["symbols"][sym] = entry
            continue
        entry["rationale"] = candidate.get("rationale")

        # 4. sizing, by the gate's own primitives.
        sized = size_candidate(candidate, rules, equity)
        entry["sizing"] = sized
        if sized["qty"] <= 0:
            entry["reason"] = sized.get("reason") or "qty_clipped_to_zero"
            plan["symbols"][sym] = entry
            continue

        limit = float(sized["limit"])
        stop = float(sized["stop"])
        cap = _f(features.get("cap"))
        last = float(features["last"])
        drift = float(p["max_drift_pct"])
        # FLOORED to the tick, never rounded: this is a MAXIMUM, and rounding a
        # maximum up loosens it by a cent on nothing but a float's binary
        # representation (18.50 * 1.01 = 18.685, which is not exactly 18.685).
        # Floor is deterministic and errs toward refusing the trade.
        max_last = strategy.floor_to_tick(last * (1.0 + drift))
        if cap is not None:
            max_last = min(max_last, cap)
        # THE SYMMETRIC FLOOR, from the SAME max_drift_pct — one band, one
        # number in the rules file. A gap DOWN is not a bargain on a bracket:
        # the stop was placed 2*ATR under the PLANNED last, so filling well
        # below it leaves a stop a few cents away that ordinary noise takes
        # out. The hard `last <= stop` refusal in the gate catches the lethal
        # case; this catches the merely-degraded one and hands it back to the
        # human, who can re-plan on the new price in one command.
        min_last = strategy.ceil_to_tick(last * (1.0 - drift))
        ticket_id = "TF-PLAN-" + stamp + "-" + sym
        entry["decision"] = "candidate"
        entry["reason"] = "strategy_candidate"
        entry["ticket"] = {
            # the exact outbox dialect the loader reads, with the two fields
            # that keep it INERT until a human changes them.
            "id": ticket_id,
            "status": "proposed",
            "risk_stamped": False,
            "action": "place_gtc_bracket",
            "symbol": sym,
            "side": "BUY",
            "stop_side": "SELL",
            "qty": int(sized["qty"]),
            "limit": limit,
            "stop": stop,
            "planned_at": plan["planned_at"],
            "source_plan": plan_file_path(repo_root, t_now).name,
            "validity": {
                "max_last": max_last,
                "min_last": min_last,
                "min_sma20_over_sma50": True,
                "max_data_age_minutes": float(p["max_data_age_minutes"]),
                "planned_last": last,
                "planned_atr": features.get("atr14"),
                "rationale": candidate.get("rationale"),
            },
        }
        plan["candidates"].append(ticket_id)
        plan["symbols"][sym] = entry

    return plan


def write_plan_file(
    plan: dict, repo_root: Path | None = None, now: datetime | None = None
) -> Path | None:
    """Atomic write to config/plans/. temp + os.replace, same directory.

    A half-written plan a human reads at 07:00 is worse than no plan, and the
    temp file stays on the same filesystem so os.replace is atomic. Returns the
    path, or None after logging the failure — a failed plan write must never
    look like a plan that said nothing.
    """
    dest = plan_file_path(repo_root, now)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(json.dumps(plan, indent=2, sort_keys=True, default=str))
        os.replace(tmp, dest)
        return dest
    except Exception as e:
        logj(
            {
                "op": "plan_file",
                "execute": "write_failed",
                "error": type(e).__name__,
                "path": str(dest),
                "sent": False,
                "mutated": False,
                "dry_run": True,
            }
        )
        return None


def run_planning_pass(
    rules: dict,
    book: dict,
    repo_root: Path | None = None,
    now: datetime | None = None,
    rules_path: str = "",
) -> list:
    """Build the plan, write it, print one legible line per symbol.

    Returns the log lines so run_cycle can hand them back with the rest of the
    cycle. Every line carries `sent: False` and `mutated: False` LITERALLY —
    this lane cannot post, and a caller iterating the cycle's output must be
    able to assert that without a missing key reading as None.
    """
    plan = build_plan(rules, book, repo_root=repo_root, now=now, rules_path=rules_path)
    lines: list = []
    for sym in LIVE_UNIVERSE:
        entry = plan["symbols"].get(sym)
        if entry is None:
            continue
        f = entry.get("features") or {}
        t = entry.get("ticket") or {}
        lines.append(
            {
                "op": "plan",
                "symbol": sym,
                "decision": entry.get("decision"),
                "reason": entry.get("reason"),
                "last": f.get("last"),
                "cap": f.get("cap"),
                "sma20": f.get("sma20"),
                "sma50": f.get("sma50"),
                "sma20_slope": f.get("sma20_slope"),
                "sma50_slope": f.get("sma50_slope"),
                "atr14": f.get("atr14"),
                "ret5d": f.get("ret5d"),
                "dist_to_sma20_pct": f.get("dist_to_sma20_pct"),
                "bars": f.get("bars"),
                "history_ok": f.get("history_ok"),
                "ticket_id": t.get("id"),
                "qty": t.get("qty"),
                "limit": t.get("limit"),
                "stop": t.get("stop"),
                "failed_checks": entry.get("failed_checks"),
                "note": "read_only_proposal_no_order_placed",
                "sent": False,
                "mutated": False,
                "dry_run": True,
            }
        )
    path = write_plan_file(plan, repo_root=repo_root, now=now)
    lines.append(
        {
            "op": "plan_file",
            "execute": "written" if path else "write_failed",
            "path": str(path) if path else None,
            "planned_at": plan["planned_at"],
            "candidates": plan["candidates"],
            "note": "approve with --approve-plan <file> <ticket id>",
            "sent": False,
            "mutated": False,
            "dry_run": True,
        }
    )
    for line in lines:
        logj(line)
    return lines


# Ticket outcomes that clear the outbox into done/. Everything else moves to
# failed/ — with ONE exception, `deferred`, which is the only outcome that
# leaves the ticket where it is. See _TICKET_WAIT and WAIT_REFUSALS.
_TICKET_DONE = ("posted", "canceled", "skip_already_sent")
# The outcome that does not move the file at all. Named rather than inlined so
# the "does this ticket move?" decision has exactly one place to read.
_TICKET_WAIT = ("deferred",)


def run_cycle(
    rules: dict,
    book: dict,
    live: bool = False,
    broker_note: str = "",
    rules_path: str = "",
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> list[dict]:
    # `now` is threaded to every lane so one cycle is internally consistent:
    # the clock that answers RTH is the clock that stamps first_seen_at and the
    # clock that decides whether a ticket has expired.
    rth = book.get("in_rth") if "in_rth" in book else in_rth(now)
    header = {
        "op": "cycle",
        "mode": "live" if live else "dry-run",
        "broker": broker_note or book.get("source") or "unknown",
        "rules_path": rules_path,
        "equity": book.get("equity"),
        "armed": bool(book.get("armed")),
        "in_rth": rth,
        "sent": False,
        "mutated": False,
        "dry_run": not live,
    }
    logj(header)

    # --- outbox lane ---
    # Every ticket is gated against the same rules/book as a planned entry, and
    # every ticket is wrapped: a poison ticket must never stop the protect lane
    # below it. run_cycle ALWAYS reaches plan_actions.
    outbox_results: list[dict] = []
    try:
        outbox_tickets = load_outbox_tickets(repo_root)
    except Exception as e:
        outbox_tickets = []
        logj(
            {
                "op": "outbox_scan",
                "execute": "exception",
                "error": type(e).__name__,
                "sent": False,
                "mutated": False,
                "dry_run": not live,
            }
        )
    for ticket_data in outbox_tickets:
        path = ticket_data.get("path")
        try:
            e = execute_outbox_ticket(
                ticket_data,
                live=live,
                rules=rules,
                book=book,
                repo_root=repo_root,
                now=now,
            )
        except Exception as exc:
            e = {
                "op": "outbox_ticket",
                "ticket_id": (ticket_data.get("ticket") or {}).get("id"),
                "symbol": (ticket_data.get("ticket") or {}).get("symbol"),
                "execute": "exception",
                "error": type(exc).__name__,
                "sent": False,
                "mutated": False,
                "dry_run": not live,
            }
        logj(e)
        outbox_results.append(e)
        if e.get("dry_run"):
            continue
        if e.get("execute") in _TICKET_WAIT:
            # Anthony 2026-09-03: "They should wait not die." The ticket stays
            # in config/outbox/ and is re-gated from scratch next cycle. Note
            # the shape: `deferred` is an ALLOWLIST of one, so an unrecognised
            # outcome still quarantines rather than silently parking forever.
            continue
        if path is not None:
            move_ticket(
                path,
                "done" if e.get("execute") in _TICKET_DONE else "failed",
                repo_root,
            )

    planned = plan_actions(rules, book)
    executed = []
    for a in planned:
        # Same quarantine the outbox lane got: neither schwab_post_order nor
        # cancel_by_id wraps requests, so a network exception out of one action
        # used to escape run_cycle and abandon every action behind it. Ordering
        # limits the damage (protect stops go first) but does not close it.
        try:
            e = execute_action(
                a, live=live, rth=rth, repo_root=repo_root, now=now, book=book
            )
        except Exception as exc:
            e = dict(a)
            e["execute"] = "exception"
            e["error"] = type(exc).__name__
            e["sent"] = False
            e["mutated"] = False
            e["dry_run"] = not live
        logj(e)
        executed.append(e)
    if not planned:
        logj(_action("skip", None, "no_planned_actions"))

    # --- off-hours planning lane, LAST and OUTSIDE RTH ONLY ---
    # Anthony 2026-09-03 07:49 ET. Last so it can never delay the protect lane
    # or an approved ticket; outside RTH only so the daemon spends the session
    # executing what a human already approved rather than inventing trades.
    # Wrapped like every other lane: a planner exception must not be able to
    # retro-actively poison a cycle that already posted correctly.
    plan_results: list = []
    if not rth:
        try:
            plan_results = run_planning_pass(
                rules, book, repo_root=repo_root, now=now, rules_path=rules_path
            )
        except Exception as exc:
            plan_results = [
                {
                    "op": "plan",
                    "execute": "exception",
                    "error": type(exc).__name__,
                    "sent": False,
                    "mutated": False,
                    "dry_run": True,
                }
            ]
            logj(plan_results[0])
    return [header] + outbox_results + executed + plan_results


def cmd_status(rules: dict, book: dict, broker_note: str, rules_path: str) -> int:
    slim_orders = []
    for o in book.get("orders") or []:
        slim_orders.append(
            {
                "id": o.get("id") or o.get("orderId"),
                "symbol": order_symbol(o),
                "side": order_side(o),
                "status": order_status(o),
                "type": o.get("type") or o.get("orderType"),
                "price": o.get("price"),
                "stopPrice": o.get("stopPrice"),
                "duration": o.get("duration"),
                "qty": o.get("qty") or o.get("quantity"),
            }
        )
    logj(
        {
            "op": "status",
            "mode": "dry-run",
            "broker": broker_note,
            "rules_path": rules_path,
            "note": broker_note,
            "equity": book.get("equity"),
            "cash": book.get("cash"),
            "armed": bool(book.get("armed")),
            "positions": book.get("positions") or [],
            "orders": slim_orders,
            "quotes": book.get("quotes") or {},
            "sent": False,
            "dry_run": True,
        }
    )
    if broker_note == "broker not on this machine":
        logj({"op": "note", "msg": "broker not on this machine", "sent": False})
    return 0


def resolve_book(rules: dict) -> tuple[dict, str]:
    book, note = fetch_book()
    if book is None:
        fb = fallback_book(rules)
        fb["broker_note"] = note
        # armed is answered HERE, by the session file, not by armed_hint in
        # standing_rules.json. This is the I/O layer; plan_actions is a pure
        # planner and must not reach the filesystem to answer it. in_rth is
        # deliberately left unstamped so each reader consults the wall clock.
        fb["armed"] = session_armed()
        return fb, note
    return book, note


def load_outbox_tickets(repo_root: Path | None = None) -> list[dict]:
    """Scan config/outbox/*.json for approved tickets.

    An unreadable file is RETURNED with a load_error rather than swallowed, so
    the caller quarantines it instead of leaving it to be re-read every cycle.
    """
    root = repo_root or REPO_ROOT
    outbox = root / "config" / "outbox"
    if not outbox.exists():
        return []
    tickets = []
    for p in sorted(outbox.glob("*.json")):
        try:
            t = json.loads(p.read_text())
        except Exception as e:
            tickets.append({"ticket": {}, "path": p, "load_error": type(e).__name__})
            continue
        if not isinstance(t, dict):
            tickets.append({"ticket": {}, "path": p, "load_error": "not_a_json_object"})
            continue
        # Unapproved / un-stamped tickets are left in place: they are waiting
        # for a human, not failing.
        if t.get("status") == "approved" and t.get("risk_stamped") is True:
            tickets.append({"ticket": t, "path": p})
    return tickets


def move_ticket(src: Path, result: str, repo_root: Path | None = None) -> bool:
    """Move ticket to done/ or failed/. Returns success; never swallows silently."""
    root = repo_root or REPO_ROOT
    dest_folder = root / "config" / "outbox" / result
    dest = dest_folder / src.name
    try:
        dest_folder.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest_folder / f"{src.stem}.{now_et().strftime('%Y%m%dT%H%M%S')}{src.suffix}"
        os.replace(src, dest)
        return True
    except Exception as e:
        logj(
            {
                "op": "outbox_move",
                "execute": "move_failed",
                "error": type(e).__name__,
                "src": str(src),
                "dest": str(dest),
                "note": "ticket left in outbox; a stamped ticket will skip next cycle",
                "sent": False,
                "mutated": False,
            }
        )
        return False


def _is_num(v: Any) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(float(v))
    )


def _ticket_schema_errors(t: dict) -> list[str]:
    """Type-check a ticket BEFORE any value is used. No float(None) paths."""
    errs: list[str] = []
    tid = t.get("id")
    if not isinstance(tid, str) or not tid.strip():
        errs.append("id_must_be_nonempty_string")
    action = t.get("action")
    if not isinstance(action, str) or not action.strip():
        return errs + ["action_must_be_nonempty_string"]
    a = action.strip().lower()
    if a == "place_gtc_bracket":
        sym = t.get("symbol")
        if not isinstance(sym, str) or not sym.strip():
            errs.append("symbol_must_be_nonempty_string")
        qty = t.get("qty")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            errs.append("qty_must_be_positive_int")
        px_ok = True
        for k in ("limit", "stop"):
            v = t.get(k)
            if not _is_num(v) or float(v) <= 0:
                errs.append(f"{k}_must_be_positive_number")
                px_ok = False
        side = t.get("side", "BUY")
        if not isinstance(side, str) or side.strip().upper() != "BUY":
            errs.append("side_must_be_BUY")
        stop_side = t.get("stop_side", "SELL")
        if not isinstance(stop_side, str) or stop_side.strip().upper() != "SELL":
            errs.append("stop_side_must_be_SELL")
        if px_ok and float(t.get("stop")) >= float(t.get("limit")):
            errs.append("stop_must_be_below_limit_for_buy")
    elif a == "cancel_by_id":
        oid = t.get("order_id")
        if (
            isinstance(oid, bool)
            or not isinstance(oid, (str, int))
            or (isinstance(oid, str) and not oid.strip())
        ):
            errs.append("order_id_must_be_nonempty_string_or_int")
    else:
        errs.append("unknown_action")
    return errs


def working_order_by_id(book: dict, order_id: Any) -> dict | None:
    """Working order with this id. Ids arrive as int from Schwab, str in tickets."""
    want = str(order_id).strip()
    for o in book.get("orders") or []:
        oid = o.get("id") if o.get("id") is not None else o.get("orderId")
        if oid is None:
            continue
        if str(oid).strip() == want and order_is_working(o):
            return o
    return None


def duplicate_working_order(
    book: dict, symbol: str, side: str, qty: Any, limit: Any
) -> dict | None:
    """Working order matching symbol+side+qty+limit. Prices compared at cents."""
    try:
        want_qty = int(qty)
        want_px = round(float(limit), 2)
    except (TypeError, ValueError):
        return None
    for o in book.get("orders") or []:
        if order_symbol(o) != symbol or not order_is_working(o):
            continue
        if order_side(o) != str(side).upper():
            continue
        px = _f(o.get("price") if o.get("price") is not None else o.get("limit"))
        oq = o.get("qty") if o.get("qty") is not None else o.get("quantity")
        try:
            if px is None or int(float(oq)) != want_qty:
                continue
        except (TypeError, ValueError):
            continue
        if round(px, 2) == want_px:
            return o
    return None


def ticket_notional_cap(rules: dict, equity: float | None) -> float | None:
    """Hard per-ticket notional ceiling in dollars, or None if uncomputable.

    `max_ticket_notional`     — absolute dollars (optional, unambiguous unit)
    `max_ticket_notional_pct` — fraction of live equity (default 0.35)
    Both present → the tighter one wins.
    """
    r = rules.get("risk") or {}
    caps: list[float] = []
    try:
        pct = float(r.get("max_ticket_notional_pct", MAX_TICKET_NOTIONAL_PCT_DEFAULT))
    except (TypeError, ValueError):
        pct = MAX_TICKET_NOTIONAL_PCT_DEFAULT
    if equity is not None and equity > 0 and pct > 0:
        caps.append(equity * pct)
    usd = r.get("max_ticket_notional")
    if usd is not None:
        try:
            u = float(usd)
            if u > 0:
                caps.append(u)
        except (TypeError, ValueError):
            pass
    return min(caps) if caps else None


def _parse_ticket_time(value: Any) -> datetime:
    """Parse a ticket ISO timestamp. A bare stamp means ET; raises ValueError.

    now_et() does the tz work: naive → stamped ET, offset-carrying → converted
    to ET, so both compare correctly against a wall clock the human reads.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO string")
    s = value.strip()
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    return now_et(datetime.fromisoformat(s))


def outbox_max_wait_days(rules: dict) -> tuple[float | None, str | None]:
    """rules['outbox']['max_wait_days'] → (days, problem).

    ABSENT BY DEFAULT AND THAT IS ANTHONY'S CALL: with no value, a ticket waits
    indefinitely and only `expires_at` or a human bounds it. A value that will
    not parse is reported as a problem and treated as absent — the failure mode
    of a bad config here is a ticket waiting, which posts nothing.

    THAT PROMISE WAS ONCE FALSE FOR A LARGE VALUE, and the failure was the
    dangerous direction: `max_wait_days: 1e12` (or a 999999999999 sentinel
    meaning "never expire") parsed clean here, then overflowed
    `timedelta`/`datetime` in the caller, and run_cycle caught the exception
    into execute="exception" and quarantined the ticket to failed/. A config
    saying "wait forever" killed every waiting ticket. The caller now measures
    ELAPSED time instead of constructing a future timestamp, so no finite value
    can overflow and a huge one means what a human reading it thinks it means.

    A bool is rejected rather than accepted as 1.0: `max_wait_days: true` reads
    as "enabled", and silently becoming a ONE-DAY limit kills tickets.
    """
    o = rules.get("outbox")
    if not isinstance(o, dict) or "max_wait_days" not in o:
        return None, None
    raw = o.get("max_wait_days")
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return None, f"max_wait_days_unparseable:{type(raw).__name__}"
    try:
        days = float(raw)
    except (TypeError, ValueError):
        return None, f"max_wait_days_unparseable:{type(raw).__name__}"
    if not math.isfinite(days) or days < 0:
        return None, f"max_wait_days_out_of_range:{raw}"
    return days, None


def ticket_wait_bounds_refusal(
    t: dict, rules: dict, now: datetime | None = None
) -> tuple[str | None, dict]:
    """Human-set bounds on how long a ticket may wait. Checked before every gate.

    Waiting exists because Anthony said a timing refusal should wait, not die.
    These two fields are how he ends a wait without being at the glass:

      ticket `expires_at`        — ISO, ET or with an offset. Past it, the
                                   ticket is TERMINAL (`ticket_expired`).
      rules  outbox.max_wait_days — N days measured from the `first_seen_at`
                                   the daemon stamped on the FIRST deferral.
                                   Past it, TERMINAL (`ticket_wait_exceeded`).

    A stamp that will not parse is a corrupt ticket, not a fresh one: it is
    refused as a schema error rather than silently restarting the clock.
    """
    detail: dict = {}
    t_now = now_et(now)

    if t.get("expires_at") is not None:
        try:
            expires = _parse_ticket_time(t.get("expires_at"))
        except (ValueError, TypeError):
            return "ticket_schema_invalid", {"schema_errors": ["expires_at_not_iso"]}
        detail["expires_at"] = expires.isoformat()
        if t_now > expires:
            detail["now"] = t_now.isoformat()
            return "ticket_expired", detail

    if t.get("first_seen_at") is not None:
        try:
            first_seen = _parse_ticket_time(t.get("first_seen_at"))
        except (ValueError, TypeError):
            return "ticket_schema_invalid", {"schema_errors": ["first_seen_at_not_iso"]}
        detail["first_seen_at"] = first_seen.isoformat()
        days, problem = outbox_max_wait_days(rules)
        if problem:
            detail["max_wait_days_problem"] = problem
        if days is not None:
            detail["max_wait_days"] = days
            # Measured as ELAPSED, never as `first_seen + timedelta(days)`:
            # that add raises OverflowError for any days past datetime.max
            # (1e12 fails in timedelta, 999999999 fails in the add), run_cycle
            # catches it into execute="exception", and the ticket is
            # quarantined. A config meant to say "never expire" would kill
            # exactly the tickets it meant to protect. This form is total over
            # every finite value and keeps the same strict comparison.
            elapsed_days = (t_now - first_seen).total_seconds() / 86400.0
            detail["waited_days"] = round(elapsed_days, 4)
            if elapsed_days > days:
                detail["now"] = t_now.isoformat()
                return "ticket_wait_exceeded", detail

    return None, detail


def gate_outbox_ticket(
    t: dict, rules: dict, book: dict, now: datetime | None = None
) -> tuple[str | None, dict]:
    """Apply the plan_actions gates to an outbox ticket.

    Returns (refusal_reason | None, detail). A ticket that clears every gate
    returns (None, detail) and only then may be POSTed.

    ORDER IS LOAD-BEARING SINCE 2026-09-03, and it is the whole of what makes
    "wait, don't die" safe. A WAIT refusal parks the ticket for the next cycle,
    so if a WAIT check ran before a TERMINAL one, a ticket that can NEVER pass
    would sit in the outbox until the open just to be killed at 09:30 — the
    daemon would spend the night deferring a ticket for SOFI. So every TERMINAL
    check that needs neither the clock nor a fresh quote runs FIRST:

        wait bounds (expires_at / max_wait_days)   terminal
        schema                                     terminal
        orders leg proven                          WAIT   (book-derived gates
                                                           below are all blind
                                                           without it)
        universe / protect-only                    terminal
        limit vs cap                               terminal
        equity known                               WAIT
        risk clip, then notional cap               terminal
        existing entry / one-sell / long / dup     terminal
        risk box (breaker, peak-DD, max-opens)     WAIT
        arm                                        WAIT
        RTH                                        WAIT
        validity re-evaluation (if the ticket
          carries `validity`)                      WAIT then terminal
        last vs cap (through_cap_idea_dead)        terminal, evaluated LAST

    Two orderings inside that list are deliberate, not incidental:
      * the risk CLIP is checked before the NOTIONAL cap. They are different
        caps and both bind; clip-first is what makes an oversized ticket report
        the size law it broke rather than the buying-power one.
      * `through_cap_idea_dead` is terminal but sits at the end because it is
        the one terminal check that reads a live quote. Killing a ticket at
        03:00 on an overnight print, when the gate exists to say "the idea is
        dead in the session that is about to open", would be the wrong death.

    THREE EXCEPTIONS TO "TERMINAL FIRST", STATED SO NOBODY READS THE LIST AS
    AN ABSOLUTE. All three are WAITs sitting ahead of terminals, and all three
    are deliberate:

      1. `orders_unproven` runs ahead of the universe check (a terminal that
         needs no book at all). During a Schwab outage a ticket for a symbol
         the daemon may never trade therefore DEFERS instead of dying, and only
         dies on the next healthy read. That is the cost of keeping the "no
         book-derived gate is evaluated on a blind book" rule absolute, which
         is the stronger safety property: the alternative is a gate order where
         some checks read a book that has not proven itself.
      2. `equity_unknown_cannot_size` runs ahead of four terminals that read no
         equity at all — `existing_entry_in_book`,
         `one_sell_law_existing_sell`, `already_long_no_add` and
         `duplicate_working_order`. So a ticket duplicating a working order
         DEFERS rather than dies whenever equity is unreadable. Reachability is
         low (an accounts-call failure aborts the whole read, which yields
         `orders_unproven` first, exception 1). The four are NOT moved above
         the equity gate: reordering gates on a live money wire to change the
         disposition of a low-reachability edge is a worse trade than
         documenting it, and deferring is the fail-safe direction anyway.
      3. The `validity` block (2026-09-04) runs three WAITs — `quotes_unproven`,
         `data_stale_refetch_next_cycle`,
         `history_unproven_refetch_next_cycle` — ahead of its own terminal
         `idea_stale_reevaluated`, for exactly the reason in exception 1: the
         terminal verdict is a comparison against fresh data, so it CANNOT be
         evaluated until the read proves itself. Refusing to re-decide on data
         the daemon could not read is the whole point of the block. It also
         sits ahead of `through_cap_idea_dead`, which for a validity ticket
         therefore never fires: `validity.max_last` is the tighter bound and it
         reports the planned-vs-now numbers, so one terminal with numbers beats
         two terminals racing. Both are terminal, so the DISPOSITION is
         identical either way — only the reason string changes.

    ANTHONY, 2026-09-03 11:47 EDT, the directive the validity block exists for:
    "if the trade doesn't go through when it was supposed to go through or when
    it was planned, it should be reevaluate with updated data time sensitive
    data". A ticket planned last night is an IDEA, not a permission. The
    `validity` block is that idea's falsifier, carried in the ticket file, and
    it runs at the moment of execution against a fresh read.
    """
    detail: dict = {}

    # Bounds a human set on waiting. Ahead of everything, including schema:
    # an expired ticket is not worth a gate list, and neither field is
    # meaningful once the daemon has decided the ticket is malformed.
    reason, bounds = ticket_wait_bounds_refusal(t, rules, now)
    detail.update(bounds)
    if reason is not None:
        return reason, detail

    errs = _ticket_schema_errors(t)
    if errs:
        return "ticket_schema_invalid", {**detail, "schema_errors": errs}

    action = str(t.get("action")).strip().lower()
    detail["action"] = action
    rth = book.get("in_rth")
    if rth is None:
        rth = in_rth(now)
    detail["in_rth"] = bool(rth)

    # Every gate below this line is answered by the order book. An unproven
    # orders leg makes all of them pass, so it refuses first. MEASURED: with
    # orders=[], a ticket for 11 ETHA @ 18.70 clears every gate and POSTs a
    # duplicate of an order already working.
    if not book_leg_proven(book, "orders"):
        detail["source"] = book.get("source")
        return "orders_unproven", detail

    if action == "cancel_by_id":
        # Terminal first, WAIT last, same law as the bracket lane below: an id
        # that is not working, or is working on a symbol the daemon may not
        # touch, is refused at 03:00. Only the clock defers.
        order_id = t.get("order_id")
        detail["order_id"] = str(order_id)
        target = working_order_by_id(book, order_id)
        if target is None:
            return "cancel_order_id_not_working_in_book", detail
        sym = order_symbol(target)
        detail["symbol"] = sym
        if sym not in LIVE_UNIVERSE or sym in PROTECT_ONLY:
            return "cancel_symbol_not_in_live_universe", detail
        if not rth:
            return "outside_rth", detail
        return None, detail

    # --- place_gtc_bracket ---
    sym = str(t.get("symbol")).strip().upper()
    qty = int(t.get("qty"))
    limit = float(t.get("limit"))
    stop = float(t.get("stop"))
    detail.update({"symbol": sym, "ticket_qty": qty, "limit": limit, "stop": stop})

    if sym not in LIVE_UNIVERSE:
        return "not_in_live_universe", detail
    if sym in PROTECT_ONLY:
        return "protect_only_no_entry", detail

    # The 2026-08-28 no-chase law, which the outbox lane did not carry.
    # AWAY_MODE.md: "The outbox is not a side door around the standing rules."
    # The rules file states the cap as an IDEA-level threshold ("No chase
    # through 18.90", "through cap = idea dead"), not as a guardrail on the
    # daemon's own repricing, so a human-approved ticket is inside its scope.
    # limit-vs-cap needs no quotes and is always checkable, so it is terminal
    # here; last-vs-cap needs a proven quotes leg and is evaluated at the end.
    entry_spec = (rules.get("entries") or {}).get(sym) or {}
    entry_cap = _f(entry_spec.get("cap"))
    detail["cap"] = entry_cap
    if entry_cap is not None and limit > entry_cap:
        return "ticket_limit_above_cap", detail

    # Sizing. Both caps are terminal, but both need live equity, so an unknown
    # equity WAITS rather than killing a ticket over a number the daemon could
    # not read. equity is the same field risk_box reports; risk_box itself runs
    # further down because its verdict is a resettable daily box, not a
    # property of the ticket.
    equity = _f(book.get("equity"))
    detail["equity"] = equity
    if equity is None or equity <= 0:
        return "equity_unknown_cannot_size", detail

    # the same risk primitive plan_actions uses to size a new entry
    cfg = _risk(rules)
    clipped = clip_qty(qty, limit, stop, equity, cfg["risk_pct"])
    detail["clipped_qty"] = clipped
    detail["risk_pct"] = cfg["risk_pct"]
    if clipped <= 0:
        return "qty_clipped_to_zero", detail
    if qty > clipped:
        return "ticket_qty_exceeds_risk_clip", detail

    cap = ticket_notional_cap(rules, equity)
    notional = round(qty * limit, 4)
    detail["notional"] = notional
    detail["max_ticket_notional"] = cap
    if cap is None:
        return "notional_cap_uncomputable", detail
    if notional > cap:
        return "ticket_notional_over_cap", detail

    existing = existing_entry(book, sym)
    if existing:
        detail["existing_order_id"] = existing.get("id") or existing.get("orderId")
        return "existing_entry_in_book", detail
    sell = existing_sell(book, sym)
    if sell:
        detail["existing_order_id"] = sell.get("id") or sell.get("orderId")
        return "one_sell_law_existing_sell", detail
    if position_qty(book, sym) > 0:
        return "already_long_no_add", detail

    dup = duplicate_working_order(book, sym, "BUY", qty, limit)
    if dup:
        detail["duplicate_order_id"] = dup.get("id") or dup.get("orderId")
        return "duplicate_working_order", detail

    # --- from here down every refusal WAITS ---
    # the same risk box a planned entry passes through. A tripped breaker,
    # peak-DD or max_opens is a state of the day, and the day turns over.
    box = risk_box(rules, book)
    detail["opens"] = box["opens"]
    if not box["ok"]:
        detail["risk_box"] = box["reasons"]
        return "new_risk_blocked", detail

    # arm + RTH, exactly as plan_actions gates a new entry. These two are the
    # reason the whole deferral machinery exists.
    if bool(rules.get("arm_required", True)) and not bool(book.get("armed")):
        return "arm_required", detail
    if not rth:
        return "outside_rth", detail

    # --- re-evaluation with fresh data (tickets carrying `validity`) ---
    # Written INLINE rather than factored into a helper, on purpose: the
    # refusal-classification tripwire scans this function's string literals, so
    # a helper returning (reason, detail) would ship reasons the tripwire never
    # sees. A tuple-returning helper here is the fail-open, not the tidy-up.
    #
    # A ticket without `validity` behaves exactly as it did before this block
    # existed. That is the compatibility contract: the hand-written outbox
    # ticket in AWAY_MODE.md still works, unchanged.
    validity = t.get("validity")
    if isinstance(validity, dict) and validity:
        planned_last = _f(validity.get("planned_last"))
        max_last = _f(validity.get("max_last"))
        min_last = _f(validity.get("min_last"))
        max_age = _f(validity.get("max_data_age_minutes"))
        check = {
            "planned_last": planned_last,
            "planned_atr": _f(validity.get("planned_atr")),
            "max_last": max_last,
            "min_last": min_last,
            "max_data_age_minutes": max_age,
            "min_sma20_over_sma50": bool(validity.get("min_sma20_over_sma50")),
        }
        detail["reevaluation"] = check

        # The price this whole block compares against must be a PROVEN read.
        if not book_leg_proven(book, "quotes"):
            check["failed"] = ["quotes_leg_unproven"]
            return "quotes_unproven", detail
        last_now = last_price(book, sym)
        detail["last"] = last_now
        check["last_now"] = last_now
        if last_now is None:
            check["failed"] = ["no_last_for_symbol"]
            return "quotes_unproven", detail

        # Freshness. `max_data_age_minutes` absent or unparseable is NOT a free
        # pass: a validity block that cannot say how fresh its data must be
        # cannot be re-evaluated, so it waits for a cycle whose ticket says.
        #
        # WHICH CLOCK ANSWERED IS RECORDED, AND ONE OF THEM DOES NOT COUNT ON
        # ITS OWN. `quotes_as_of` is stamped now_et() at fetch time (:1314), so
        # it reads ~0 minutes on every daemon cycle: if the per-symbol Schwab
        # stamp is missing for ANY reason — field absent from the payload, a
        # key Schwab renamed, a symbol returned without quoteTime/tradeTime —
        # then max(ages) is the inert read clock and the gate would report
        # FRESH having measured nothing. That is the fail-open shape this wire
        # exists to close, so an unmeasured quote clock is UNPROVEN, and
        # unproven WAITS for a cycle that can measure it.
        fresh = quote_freshness(book, sym, now)
        age = fresh["age_minutes"]
        check["quote_age_minutes"] = None if age is None else round(age, 3)
        check["quote_time_seen"] = fresh["quote_time_seen"]
        check["read_stamp_seen"] = fresh["read_stamp_seen"]
        check["quote_time_age_minutes"] = (
            None
            if fresh["quote_time_age"] is None
            else round(fresh["quote_time_age"], 3)
        )
        if max_age is None or max_age <= 0:
            check["failed"] = ["max_data_age_minutes_missing"]
            return "data_stale_refetch_next_cycle", detail
        if not fresh["quote_time_seen"]:
            # Ordered BEFORE the age comparison because it is the more honest
            # fact: "I never measured the clock that can fire" is not the same
            # statement as "what I measured is old", and the log line should
            # say which one happened.
            check["failed"] = ["quote_time_unmeasured"]
            return "data_stale_refetch_next_cycle", detail
        if age is None or age > max_age:
            check["failed"] = ["quote_age"]
            return "data_stale_refetch_next_cycle", detail

        # THE DOWNSIDE HALF OF THE BAND, and it is the half that can cost money
        # rather than an opportunity. Until 2026-09-04 this block bounded drift
        # UP only, so a gap DOWN through the planned stop passed every check:
        # plan last 18.50 / stop 17.98 (= last - 2*ATR) with the market opened
        # at 17.60 is under max_last, under the cap, and one session barely
        # moves a 20/50 SMA stack. The bracket would then POST with its child
        # stop already through the market, and both of Schwab's answers are
        # bad — accept it and the parent fills at ~17.60 with the stop
        # triggering at once (a position opened and closed in a shape no human
        # approved), reject the child and the parent still fills, leaving the
        # account long and NAKED, which is the exact outcome this wire exists
        # to prevent. A ~2.9% overnight gap is ordinary for a crypto ETF.
        #
        # Terminal, not a wait: a price at or below the protective stop means
        # the setup the human approved is gone, not merely early.
        if last_now <= stop:
            check["failed"] = ["last_at_or_below_stop"]
            check["stop"] = stop
            return "idea_stale_reevaluated", detail

        # The idea's own bounds, then the standing cap. All terminal: the
        # market moved past the trade a human approved, and re-approving is
        # the human's call with fresh eyes, not the daemon's at 09:31.
        if max_last is not None and last_now > max_last:
            check["failed"] = ["last_above_max_last"]
            return "idea_stale_reevaluated", detail
        # `min_last` is the symmetric floor: the planner derives it from the
        # SAME max_drift_pct that produces max_last, so the band is one number
        # in the rules file and not two. It is optional — a hand-written ticket
        # without it keeps the plain stop check above and nothing else.
        if min_last is not None and last_now < min_last:
            check["failed"] = ["last_below_min_last"]
            return "idea_stale_reevaluated", detail
        if entry_cap is not None and last_now > entry_cap:
            check["failed"] = ["last_above_cap"]
            return "idea_stale_reevaluated", detail

        if check["min_sma20_over_sma50"]:
            hist = fetch_daily_history(
                sym, HISTORY_DAYS, timeout=HISTORY_TIMEOUT_REEVAL_S
            )
            check["history_ok"] = bool((hist or {}).get("history_ok"))
            check["history_as_of"] = (hist or {}).get("as_of")
            check["history_bars"] = (hist or {}).get("bars")
            if not check["history_ok"]:
                check["failed"] = ["history_refetch_failed"]
                check["history_note"] = (hist or {}).get("note")
                return "history_unproven_refetch_next_cycle", detail
            p = strategy.params(rules)
            closes = closes_of((hist or {}).get("candles") or [])
            sma_fast_now = sma(closes, int(p["sma_fast"]))
            sma_slow_now = sma(closes, int(p["sma_slow"]))
            check["sma20_now"] = sma_fast_now
            check["sma50_now"] = sma_slow_now
            if sma_fast_now is None or sma_slow_now is None:
                # Fetched, but too few bars to recompute the trend. A read that
                # cannot answer is the same class as a read that failed.
                check["failed"] = ["insufficient_history_for_trend"]
                return "history_unproven_refetch_next_cycle", detail
            if not sma_fast_now > sma_slow_now:
                check["failed"] = ["trend_flipped_sma20_under_sma50"]
                return "idea_stale_reevaluated", detail

        check["verdict"] = "validity_holds"

    # Terminal, and last: it is the only terminal check that reads a quote, so
    # it is answered by the session that is actually about to trade. For a
    # `validity` ticket the block above has already bounded `last` more
    # tightly, so this is the plain-ticket path.
    if book_leg_proven(book, "quotes"):
        last_now = last_price(book, sym)
        detail["last"] = last_now
        if entry_cap is not None and last_now is not None and last_now > entry_cap:
            return "through_cap_idea_dead", detail

    return None, detail


def record_in_cycle_order(book: dict, detail: dict, order_id: Any) -> None:
    """Append a just-placed bracket's legs to the in-memory book.

    The cycle holds one book snapshot. Every guard that reads the book —
    existing_entry, existing_sell, duplicate_working_order, position/max_opens —
    must be able to see an order this cycle already placed, or the guard is
    blind exactly when two tickets arrive together.

    duration MUST be GOOD_TILL_CANCEL: plan_actions runs after the outbox on
    this same book, and its no_day branch would plan a cancel_abandon on the
    bracket the outbox just placed if the leg looked like a DAY order.
    """
    oid = str(order_id or "in_cycle")
    sym = detail["symbol"]
    qty = detail["ticket_qty"]
    book.setdefault("orders", []).extend(
        [
            {
                "id": oid,
                "symbol": sym,
                "side": "BUY",
                "status": "WORKING",
                "type": "LIMIT",
                "price": detail["limit"],
                "duration": "GOOD_TILL_CANCEL",
                "qty": qty,
                "remaining": qty,
                "in_cycle": True,
            },
            {
                "id": oid + "-stop",
                "symbol": sym,
                "side": "SELL",
                "status": "PENDING_ACTIVATION",
                "type": "STOP",
                "stopPrice": detail["stop"],
                "duration": "GOOD_TILL_CANCEL",
                "qty": qty,
                "remaining": qty,
                "in_cycle": True,
            },
        ]
    )


def record_in_cycle_cancel(book: dict | None, order_id: Any) -> None:
    """Mark a just-canceled order CANCELED in the in-memory book.

    The symmetric twin of record_in_cycle_order, and of the same bug: the cycle
    holds ONE book snapshot, so an order the outbox just canceled still reads as
    WORKING to plan_actions, which runs afterward on that same book and can plan
    a second cancel_abandon on the same id. MEASURED before this fix: an ETHA
    DAY BUY id 555 plus an approved cancel_by_id ticket for 555 fired TWO
    DELETEs on 555 in a single cycle. Live, the second 400s and
    record_cancel_refusal then poisons that id for the rest of the trading day.

    order_is_working() reads status, so flipping status is enough to make every
    downstream guard see the cancel.
    """
    if not isinstance(book, dict):
        return
    target = str(order_id)
    for o in book.get("orders") or []:
        if str(o.get("id") or o.get("orderId")) == target:
            o["status"] = "CANCELED"
            o["in_cycle_canceled"] = True


def stamp_ticket_order_id(path: Path, ticket: dict, order_id: Any) -> bool:
    """Write the broker order_id back into the ticket file, atomically.

    Runs BEFORE the move. If the move then fails, the ticket still carries
    schwab_order_id and later cycles skip it instead of double-sending.
    """
    try:
        data = dict(ticket)
        data["schwab_order_id"] = str(order_id)
        data["stamped_at"] = now_et().isoformat()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, path)
        return True
    except Exception as e:
        logj(
            {
                "op": "outbox_stamp",
                "execute": "stamp_failed",
                "error": type(e).__name__,
                "path": str(path),
                "order_id": str(order_id),
                "note": "ORDER IS LIVE AT THE BROKER AND THE TICKET IS UNSTAMPED",
                "sent": False,
                "mutated": False,
            }
        )
        return False


def stamp_ticket_first_seen(
    path: Path | None, ticket: dict, now: datetime | None = None
) -> str | None:
    """Stamp first_seen_at on the FIRST deferral. Returns the stamp, or None.

    Same temp + os.replace shape as stamp_ticket_order_id: the ticket file is
    never observed half-written.

    A ticket that already carries first_seen_at is NEVER rewritten. That stamp
    is the clock outbox.max_wait_days measures from, and a stamp refreshed each
    cycle makes the bound unfireable — the ticket would wait forever while a
    field claimed it had just arrived. `deferrals` rides along on that one write
    for the same reason: it marks "this ticket has been deferred before", so the
    log line can say second-or-later without the file being rewritten every
    900s.
    """
    if path is None or ticket.get("first_seen_at"):
        return None
    stamp = now_et(now).isoformat()
    try:
        data = dict(ticket)
        data["first_seen_at"] = stamp
        data["deferrals"] = 1
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, path)
        return stamp
    except Exception as e:
        logj(
            {
                "op": "outbox_defer_stamp",
                "execute": "stamp_failed",
                "error": type(e).__name__,
                "path": str(path),
                "note": "ticket waits unstamped; max_wait_days cannot bound it yet",
                "sent": False,
                "mutated": False,
            }
        )
        return None


def execute_outbox_ticket(
    ticket_data: dict,
    live: bool,
    rules: dict,
    book: dict,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Execute one approved ticket, under the same gates as a planned entry.

    rules and book are REQUIRED: the PR shipped this path with neither, so a
    ticket could name any symbol, any size, at any hour. Gates are evaluated in
    dry-run too, so a dry cycle reports exactly what a live cycle would refuse.

    Every refusal leaves through _refuse(), which reads WAIT_REFUSALS and
    returns execute='deferred' or execute='refused'. One exit, so a branch
    added later cannot forget to classify itself.
    """
    t = ticket_data.get("ticket") or {}
    path = ticket_data.get("path")
    out: dict = {
        "op": "outbox_ticket",
        "ticket_id": t.get("id"),
        "symbol": t.get("symbol"),
        "dry_run": not live,
        "sent": False,
        "mutated": False,
    }

    def _refuse(reason: str, detail: dict | None = None) -> dict:
        """The one exit for a refused ticket. WAIT parks it; TERMINAL kills it."""
        if detail is not None:
            out["gate"] = detail
        out["reason"] = reason
        if not refusal_is_wait(reason):
            out["execute"] = "refused"
            return out
        out["execute"] = "deferred"
        try:
            prior = int(t.get("deferrals") or 0)
        except (TypeError, ValueError):
            prior = 0
        # The file is written once, so this reads 1 on the cycle that stamps
        # and 2 on every cycle after: "second or later", not an exact tally.
        out["deferrals"] = prior + 1
        seen = t.get("first_seen_at")
        # A dry run must not touch the ticket. Stamping in one would start the
        # max_wait_days clock from a hand-run that posted nothing.
        if live:
            stamped = stamp_ticket_first_seen(path, t, now)
            if stamped:
                seen = stamped
                out["stamped_first_seen"] = True
        out["first_seen_at"] = seen
        return out

    if ticket_data.get("load_error"):
        out["error"] = ticket_data["load_error"]
        return _refuse("ticket_unreadable")
    if not isinstance(rules, dict) or not rules:
        return _refuse("rules_missing")

    # Already sent is answered before anything about the world: the ticket is
    # finished, and neither an absent book nor an elapsed deadline changes
    # that. It moves to done/, which is where a sent ticket belongs.
    existing_oid = t.get("schwab_order_id")
    if existing_oid:
        out["execute"] = "skip_already_sent"
        out["existing_order_id"] = existing_oid
        return out

    # The human's wait bounds run BEFORE the book check, not only inside
    # gate_outbox_ticket. `book_missing` is a WAIT and returns above the gate,
    # so a ticket whose expires_at passed in 2020 used to defer forever on an
    # empty book — the deadline could never fire because nothing evaluated it.
    # `book == {}` is not reachable from the daemon (resolve_book always
    # substitutes a fallback book), so this closes a direct-call hole, not a
    # live one. Cheap, and it keeps "the deadline always gets read" true
    # without depending on which caller you came through.
    bounds_reason, bounds = ticket_wait_bounds_refusal(t, rules, now)
    if bounds:
        out["gate"] = bounds
    if bounds_reason is not None:
        return _refuse(bounds_reason, bounds)

    if not isinstance(book, dict) or not book:
        # WAIT: an absent book is a read that failed, not a bad ticket.
        return _refuse("book_missing")

    reason, detail = gate_outbox_ticket(t, rules, book, now)
    out["gate"] = detail
    if reason is not None:
        return _refuse(reason)

    if not live:
        out["execute"] = "dry_run"
        out["reason"] = "gates_passed_would_post"
        return out

    # A hint book must never reach the wire. gate_outbox_ticket already refuses
    # an unproven orders leg; this is the boundary copy of the same rule.
    eligible, why = book_is_live_eligible(book)
    if not eligible:
        return _refuse(why)

    action = detail["action"]
    if action == "place_gtc_bracket":
        res = place_gtc_bracket(
            symbol=detail["symbol"],
            qty=detail["ticket_qty"],
            limit=detail["limit"],
            stop=detail["stop"],
            side="BUY",
            stop_side="SELL",
        )
        out["schwab"] = {k: res.get(k) for k in ("http", "order_id", "error")}
        posted = res.get("http") in (200, 201)
        out["sent"] = posted
        out["mutated"] = posted
        out["execute"] = "posted" if posted else "post_failed"
        if posted:
            # The book is fetched ONCE per cycle and handed to every ticket and
            # then to plan_actions. Without this, the duplicate / one-sell /
            # max_opens guards are blind to an order placed moments ago in this
            # same cycle: two approved tickets on one symbol would both clear
            # every gate and both POST. Record what we just placed.
            record_in_cycle_order(book, detail, res.get("order_id"))
        if posted and path is not None:
            # stamp BEFORE the move — idempotency does not depend on the move
            out["stamped"] = stamp_ticket_order_id(
                path, t, res.get("order_id") or "posted_no_location"
            )
        return out

    # cancel_by_id — gated above to a working order on a live-universe symbol
    order_id = t.get("order_id")
    if cancel_refused_today(order_id, repo_root, now):
        return _refuse("cancel_skipped_refused_today")
    res = cancel_by_id(order_id)
    out["schwab"] = {k: res.get(k) for k in ("http", "error")}
    if res.get("http") in (200, 204):
        out["mutated"] = True
        out["execute"] = "canceled"
        # plan_actions runs after this on the SAME book snapshot; without this
        # it re-plans a cancel_abandon on the id we just canceled.
        record_in_cycle_cancel(book, order_id)
    elif res.get("http") == 400:
        record_cancel_refusal(order_id, repo_root, now)
        out["execute"] = "cancel_refused_400_after_hours"
    else:
        out["execute"] = "cancel_failed"
    return out


def cmd_approve_plan(
    plan_file: str,
    ticket_id: str,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> int:
    """THE ONLY PATH FROM A PLAN TO THE OUTBOX. Offline; no broker call.

    Copies exactly one candidate out of a plan file into
    config/outbox/<id>.json with `status: approved`, `risk_stamped: true` and a
    `human_approved_at` stamp. Safe to run from any Terminal at any hour: it
    reads two files and writes one, it never resolves a book, it never needs
    LIVE_OK, and it cannot place an order.

    IT REFUSES, and each refusal is the safe direction:
      * plan unreadable, or the id is not a CANDIDATE in that plan;
      * the ticket's `validity` does not state `max_data_age_minutes` — a
        window is not invented on a money path, the plan is regenerated;
      * the plan is older than MAX_PLAN_AGE_HOURS. A stale plan must be
        REGENERATED, not approved: its prices, its trend and its ATR were true
        of a market that has moved on;
      * the plan is stamped in the future (clock skew, or a hand-edited file);
      * the ticket id is not [A-Za-z0-9._-]+. Generated ids are
        TF-PLAN-<YYYYMMDD-HHMM>-<SYM>, so nothing legitimate is excluded; the
        check exists because the id is interpolated into a path below and a
        hand-edited plan carrying a separator would write outside the outbox;
      * config/outbox/<id>.json already exists. Never clobber a ticket that may
        already be waiting, stamped, or half-way through its own life.

    IT STAMPS A DEADLINE. `expires_at` = 16:00 ET of the next session on or
    after approval (APPROVAL_EXPIRES_AT_SESSIONS ahead), which
    ticket_wait_bounds_refusal already enforces terminally as `ticket_expired`.
    Without it an approved ticket was bounded by PRICE and TREND only, so an
    idea approved Monday could post Thursday if the market happened back into
    the band. A human-approved idea now has a shelf life stated in its own
    file, and a human who wants longer edits one field.

    `risk_stamped: true` here is a LOADER PRECONDITION, not a risk waiver.
    Every gate in gate_outbox_ticket still runs on a fresh book, and the
    `validity` block re-decides the idea against fresh data at execution.
    """
    root = repo_root or REPO_ROOT
    t_now = now_et(now)
    out: dict = {
        "op": "approve_plan",
        "plan_file": str(plan_file),
        "ticket_id": str(ticket_id),
        "sent": False,
        "mutated": False,
        "dry_run": True,
    }

    def _fail(why: str, **extra: Any) -> int:
        out["execute"] = "refused"
        out["reason"] = why
        out.update(extra)
        logj(out)
        return 2

    path = Path(plan_file).expanduser()
    try:
        plan = json.loads(path.read_text())
    except Exception as e:
        return _fail("plan_unreadable", error=type(e).__name__)
    if not isinstance(plan, dict):
        return _fail("plan_not_a_json_object")

    found = None
    for sym, entry in (plan.get("symbols") or {}).items():
        if not isinstance(entry, dict):
            continue
        t = entry.get("ticket")
        if not isinstance(t, dict):
            continue
        if str(t.get("id")) == str(ticket_id) and entry.get("decision") == "candidate":
            found = t
            out["symbol"] = sym
            break
    if found is None:
        return _fail(
            "ticket_not_a_candidate_in_this_plan",
            candidates=plan.get("candidates"),
        )

    validity = found.get("validity")
    max_age = _f(validity.get("max_data_age_minutes")) if isinstance(validity, dict) else None
    if max_age is None or max_age <= 0:
        return _fail("validity_missing_max_data_age_minutes")

    try:
        planned_at = _parse_ticket_time(plan.get("planned_at"))
    except (ValueError, TypeError):
        return _fail("plan_planned_at_not_iso", planned_at=plan.get("planned_at"))
    age_minutes = (t_now - planned_at).total_seconds() / 60.0
    limit_minutes = MAX_PLAN_AGE_HOURS * 60.0
    out["plan_age_minutes"] = round(age_minutes, 2)
    out["max_plan_age_minutes"] = limit_minutes
    if age_minutes < -1.0:
        return _fail("plan_timestamp_in_the_future", planned_at=planned_at.isoformat())
    if age_minutes > limit_minutes:
        return _fail("plan_too_old_regenerate", planned_at=planned_at.isoformat())

    # The id lands in a path on the next line. Validated here rather than
    # trusted: plan ids are generated from LIVE_UNIVERSE so a daemon-written
    # plan can never carry a separator, but this function's whole input is a
    # FILE plus an ARGV string, and a hand-edited plan is an ordinary thing for
    # a human to make.
    if not _SAFE_TICKET_ID.match(str(ticket_id)):
        return _fail("ticket_id_not_path_safe")

    dest = root / "config" / "outbox" / (str(ticket_id) + ".json")
    if dest.exists():
        return _fail("outbox_ticket_already_exists", path=str(dest))

    approved = dict(found)
    approved["status"] = "approved"
    approved["risk_stamped"] = True
    approved["human_approved_at"] = t_now.isoformat()
    approved["approved_from_plan"] = str(path)
    # A shelf life, in the file, in the human's own units. Not stamped when the
    # plan already carries one — a hand-set deadline is the human's call.
    if approved.get("expires_at") is None:
        approved["expires_at"] = session_close_after(
            t_now, APPROVAL_EXPIRES_AT_SESSIONS
        ).isoformat()
    out["expires_at"] = approved["expires_at"]
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(json.dumps(approved, indent=2, sort_keys=True))
        os.replace(tmp, dest)
    except Exception as e:
        return _fail("outbox_write_failed", error=type(e).__name__, path=str(dest))

    out["execute"] = "approved"
    out["path"] = str(dest)
    out["symbol"] = approved.get("symbol")
    out["qty"] = approved.get("qty")
    out["limit"] = approved.get("limit")
    out["stop"] = approved.get("stop")
    out["human_approved_at"] = approved["human_approved_at"]
    out["note"] = "gates and validity re-run at execution; approval is not a waiver"
    logj(out)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Temple Flow Act-loop wire (default dry-run)")
    p.add_argument("--status", action="store_true", help="read-only book/orders/quotes")
    p.add_argument("--once", action="store_true", help="one plan cycle")
    p.add_argument(
        "--live",
        action="store_true",
        help="POST when LIVE_OK + TEMPLE_FLOW_LIVE=1",
    )
    p.add_argument(
        "--approve-plan",
        nargs=2,
        metavar=("PLAN_FILE", "TICKET_ID"),
        default=None,
        help="copy one planned candidate into config/outbox/ as approved (offline)",
    )
    p.add_argument("--rules", default="", help="optional rules JSON path")
    args = p.parse_args(argv)

    # FIRST, before rules are loaded and before any book is resolved: approving
    # a plan is an offline file copy. It must work with no broker on the
    # machine, no LIVE_OK, and no standing_rules.json, from any Terminal.
    if args.approve_plan:
        return cmd_approve_plan(
            args.approve_plan[0], args.approve_plan[1], repo_root=REPO_ROOT
        )

    if args.rules:
        path = Path(args.rules).expanduser()
        rules = json.loads(path.read_text())
        rules_path = str(path)
    else:
        rules, path = load_rules()
        rules_path = str(path)

    if args.live:
        ok, why = live_authorized()
        if not ok:
            print(f"HARD WARNING: {why}. No Schwab POST.", file=sys.stderr)
            logj(
                {
                    "op": "refuse_live",
                    "reason": why,
                    "sent": False,
                    "dry_run": True,
                    "mode": "dry-run",
                }
            )
            return 2
        print("LIVE gates open. Bracket helper will POST.", file=sys.stderr)

    book, note = resolve_book(rules)
    do_status = args.status
    do_once = args.once or (not args.status and not args.once)

    rc = 0
    if do_status:
        rc = cmd_status(rules, book, note, rules_path)
    if do_once:
        live = bool(args.live) and live_authorized()[0]
        run_cycle(
            rules,
            book,
            live=live,
            broker_note=note,
            rules_path=rules_path,
            repo_root=REPO_ROOT,
        )
        if args.live and not live:
            rc = 2
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
