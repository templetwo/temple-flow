#!/usr/bin/env python3
"""Desk momentum: the four taps, the session clock, and the cash that sat idle.

This module is the law Anthony already gave the desk, made executable:

  * Amendment §7 — Funds-beast may approve a Risk-PASS ticket. Revoke phrase
    ``desk may not approve``. VETO, a raise through the cap, a new name, and
    a breaker reset stay Anthony's.
  * Amendment §8 — arm when cash/equity is over 20% and no hard-hold is
    logged. Disarm at 16:00 ET without a person in the chair.
  * Amendment §4 and §6 — cash freed by a close goes back to a fillable
    pullback on the next check. The weekly target is 25% cash. The 2.5%
    stop-dollar box still sizes the ticket.

Nothing here places an order. The wire calls these functions and then runs
the same outbox gates it already trusts. A missing file, a bad file, or a
revoked grant fails closed.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-4))

# The phrase Anthony reserved. Present and true, the desk may not approve.
REVOKE_PHRASE = "desk may not approve"
# Cash/equity above this is the §8 arm condition. Strictly greater.
ARM_CASH_PCT = 0.20
# §6 weekly target. Cash above this is idle and may be offered a pullback.
CASH_TARGET_PCT = 0.25
# A resting buy this many ATRs under last, for this many sessions, is stale.
# A flag, not a cancel. The cancel lane is a different law.
STALE_ATR = 2.0
STALE_SESSIONS = 3
# How far under last a fresh pullback is priced. Inside the cap, never above
# the prior working limit.
PULLBACK_ATR = 1.0
# The 09:25 check is a window, not "any time the job happens to run."
# A restart at 14:00 must not arm.
ARM_WINDOW_START = time(9, 25)
ARM_WINDOW_END = time(9, 40)
DISARM_TIME = time(16, 0)

# Closed. A missing or unreadable grants file is this, not the example.
_CLOSED_GRANTS = {
    "desk_may_approve_risk_pass": False,
    "revoked": False,
    "auto_arm_mv_session": False,
    "auto_disarm_mv_session": True,
    "carry_reprice": False,
}


def now_et(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=ET)
    return base.astimezone(ET)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def grants_path(repo_root: Path) -> Path:
    return repo_root / "config" / "standing_grants.json"


def load_grants(repo_root: Path) -> dict:
    """Read the grants file. Missing, unreadable, or revoked means closed.

    ``revoked`` is true when the file carries Anthony's phrase, or when the
    file cannot be trusted. A caller that treats a load error as "no opinion"
    would approve on a broken disk. This function does not do that.
    """
    path = grants_path(repo_root)
    closed = dict(_CLOSED_GRANTS)
    closed["source"] = str(path)
    if not path.exists():
        closed["revoked"] = True
        closed["reason"] = "grants_file_missing"
        return closed
    try:
        raw = json.loads(path.read_text())
    except Exception as exc:
        closed["revoked"] = True
        closed["reason"] = "grants_unreadable:" + type(exc).__name__
        return closed
    if not isinstance(raw, dict):
        closed["revoked"] = True
        closed["reason"] = "grants_not_an_object"
        return closed

    phrase = raw.get("revoke") or raw.get("revoke_phrase")
    if phrase == REVOKE_PHRASE or raw.get("desk_may_approve_risk_pass") is not True:
        closed["revoked"] = True
        closed["reason"] = (
            "revoke_phrase" if phrase == REVOKE_PHRASE else "desk_may_approve_not_true"
        )
        # Disarm stays on even when approval is revoked. A revoke must not
        # leave a session armed past 16:00.
        closed["auto_disarm_mv_session"] = raw.get("auto_disarm_mv_session") is not False
        return closed

    closed["revoked"] = False
    closed["reason"] = "granted"
    closed["desk_may_approve_risk_pass"] = True
    closed["auto_arm_mv_session"] = raw.get("auto_arm_mv_session") is True
    closed["auto_disarm_mv_session"] = raw.get("auto_disarm_mv_session") is not False
    closed["carry_reprice"] = raw.get("carry_reprice") is not False
    return closed


def load_hard_hold(repo_root: Path, day: datetime) -> dict:
    """A hard-hold is a file the desk writes. Absence means no hold.

    Shape: ``config/hard_hold.json`` with ``date`` as ``YYYY-MM-DD`` (ET) and
    ``reason``. A hold for a different date does not bind. An unreadable file
    on the named date is a hold — failing open into an arm on a day the desk
    tried to flag is the wrong direction.
    """
    path = repo_root / "config" / "hard_hold.json"
    out = {"held": False, "reason": None, "path": str(path)}
    if not path.exists():
        return out
    try:
        raw = json.loads(path.read_text())
    except Exception as exc:
        out["held"] = True
        out["reason"] = "hard_hold_unreadable:" + type(exc).__name__
        return out
    if not isinstance(raw, dict):
        out["held"] = True
        out["reason"] = "hard_hold_not_an_object"
        return out
    if str(raw.get("date") or "") != day.strftime("%Y-%m-%d"):
        return out
    out["held"] = True
    out["reason"] = str(raw.get("reason") or "hard_hold")
    return out


def in_arm_window(t: datetime) -> bool:
    """09:25 inclusive through 09:40 exclusive, weekdays, ET."""
    t = now_et(t)
    if t.weekday() >= 5:
        return False
    return ARM_WINDOW_START <= t.time() < ARM_WINDOW_END


def past_disarm(t: datetime) -> bool:
    t = now_et(t)
    return t.time() >= DISARM_TIME


def cash_pct(book: dict) -> float | None:
    equity = _num(book.get("equity"))
    cash = _num(book.get("cash"))
    if equity is None or cash is None or equity <= 0:
        return None
    return cash / equity


def breaker_clear(book: dict, rules: dict) -> tuple[bool, str]:
    """The day breaker and the peak drawdown. max-opens is not a breaker.

    Amendment §9 removed the open-count ceiling as a reason to refuse cash.
    A tripped 4.5% day or an 18% peak drawdown still blocks an arm, and the
    reset of either stays Anthony's.
    """
    risk = rules.get("risk") or {}
    try:
        day_pct = float(risk.get("day_breaker_pct", 0.045))
        peak_pct = float(risk.get("peak_dd_pct", 0.18))
    except (TypeError, ValueError):
        return False, "risk_config_unreadable"
    equity = _num(book.get("equity"))
    sod = _num(book.get("sod_equity") or book.get("sod"))
    day = _num(book.get("day_pnl"))
    if day is None and equity is not None and sod is not None:
        day = equity - sod - (_num(book.get("deposit_today")) or 0.0)
    if equity is None or day is None:
        return False, "breaker_unmeasurable"
    basis = sod if sod not in (None, 0) else equity
    if basis and day <= -day_pct * basis:
        return False, "day_breaker"
    peak = _num(book.get("peak_equity") or book.get("peak"))
    if peak not in (None, 0) and (peak - equity) / peak >= peak_pct:
        return False, "peak_drawdown"
    return True, "clear"


def arm_decision(
    book: dict,
    rules: dict,
    grants: dict,
    hold: dict,
    now: datetime,
) -> dict:
    """Whether this cycle may write an armed session. Never writes.

    Every refusal is named. The first one wins, and the order is the order
    a reviewer should read: revoke, flag, clock, book, cash, breaker.
    """
    t = now_et(now)
    out = {
        "arm": False,
        "reason": None,
        "cash_pct": cash_pct(book),
        "at": t.isoformat(),
    }
    if grants.get("revoked") or not grants.get("desk_may_approve_risk_pass"):
        out["reason"] = "grants_revoked"
        return out
    if not grants.get("auto_arm_mv_session"):
        out["reason"] = "auto_arm_disabled"
        return out
    if hold.get("held"):
        out["reason"] = "hard_hold:" + str(hold.get("reason"))
        return out
    if not in_arm_window(t):
        out["reason"] = "outside_arm_window"
        return out
    if book.get("source") != "schwab_read":
        out["reason"] = "book_not_schwab_read"
        return out
    if book.get("quotes_ok") is not True or book.get("orders_ok") is not True:
        out["reason"] = "book_unproven"
        return out
    pct = out["cash_pct"]
    if pct is None:
        out["reason"] = "cash_unmeasurable"
        return out
    if pct <= ARM_CASH_PCT:
        out["reason"] = "cash_at_or_under_20"
        return out
    clear, why = breaker_clear(book, rules)
    if not clear:
        out["reason"] = why
        return out
    out["arm"] = True
    out["reason"] = "cash_over_20_inside_window"
    return out


def session_should_disarm(session: dict | None, now: datetime, grants: dict) -> dict:
    """True when the file still says armed and the clock is at or past 16:00.

    Disarm does not depend on the approval grant. A revoked desk still gets
    the kill switch. ``auto_disarm_mv_session: false`` is the only off switch,
    and a missing grants file does not set it.
    """
    t = now_et(now)
    armed = bool(session and session.get("armed"))
    if not grants.get("auto_disarm_mv_session", True):
        return {"disarm": False, "reason": "auto_disarm_disabled", "at": t.isoformat()}
    if not past_disarm(t):
        return {"disarm": False, "reason": "before_1600", "at": t.isoformat()}
    if not armed:
        return {"disarm": False, "reason": "already_disarmed", "at": t.isoformat()}
    return {
        "disarm": True,
        "reason": "rth_end_1600",
        "at": t.isoformat(),
    }


def write_session(path: Path, session: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(session, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def apply_session_clock(
    repo_root: Path,
    book: dict,
    rules: dict,
    now: datetime,
) -> dict:
    """Write the arm or the disarm this cycle owes. Idempotent.

    Arm writes a fresh file whose ``until`` is 16:00 ET today. Disarm clears
    ``armed`` and keeps the rest of the file, so the reason is on disk for
    the next seat. Neither path cancels an order.
    """
    grants = load_grants(repo_root)
    hold = load_hard_hold(repo_root, now_et(now))
    path = repo_root / "config" / "mv_session.json"
    current = None
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            current = loaded if isinstance(loaded, dict) else None
        except Exception:
            current = None
    disarm = session_should_disarm(current, now, grants)
    if disarm["disarm"] and current is not None:
        updated = dict(current)
        updated["armed"] = False
        updated["effective"] = "DISARMED"
        updated["disarmed_at"] = disarm["at"]
        updated["disarm_reason"] = "RTH end 16:00 auto-disarm (wire)"
        write_session(path, updated)
        return {"op": "session_clock", "wrote": "disarm", **disarm}
    decision = arm_decision(book, rules, grants, hold, now)
    if decision["arm"] and not (current and current.get("armed")):
        t = now_et(now)
        until = t.replace(hour=16, minute=0, second=0, microsecond=0)
        session = {
            "armed": True,
            "armed_at": t.isoformat(),
            "until": until.isoformat(),
            "source": "wire auto-arm 09:25 (cash %.1f%% > 20%%)" % ((decision["cash_pct"] or 0) * 100),
            "ticket": None,
            "effective": "ARMED",
            "auto": True,
        }
        write_session(path, session)
        return {"op": "session_clock", "wrote": "arm", **decision}
    return {
        "op": "session_clock",
        "wrote": None,
        "arm": decision,
        "disarm": disarm,
    }


def risk_verdict(ticket: dict) -> str | None:
    """The verdict Risk stamped, or None when the ticket does not carry one.

    Accepted shapes, in order: ``risk_verdict``, ``risk.verdict``,
    ``verdict``. The string must be exactly PASS or VETO. Anything else,
    including a missing field, is not a PASS.
    """
    raw = ticket.get("risk_verdict")
    if raw is None and isinstance(ticket.get("risk"), dict):
        raw = ticket["risk"].get("verdict")
    if raw is None:
        raw = ticket.get("verdict")
    if not isinstance(raw, str):
        return None
    word = raw.strip().upper()
    if word in ("PASS", "VETO"):
        return word
    return None


def prior_approval(ticket: dict) -> dict | None:
    """The approval a reprice wants to carry. None when there is nothing to carry."""
    prior = ticket.get("carries_approval")
    if not isinstance(prior, dict):
        return None
    limit = _num(prior.get("limit"))
    if limit is None:
        return None
    if prior.get("symbol") and str(prior.get("symbol")).upper() != str(ticket.get("symbol") or "").upper():
        return None
    return {
        "limit": limit,
        "stop": _num(prior.get("stop")),
        "qty": prior.get("qty"),
        "approved_by": prior.get("approved_by"),
        "ticket_id": prior.get("ticket_id"),
    }


def reprice_keeps_approval(ticket: dict) -> tuple[bool, str]:
    """A reprice keeps its yes only when nothing about the risk got larger.

    Same symbol (enforced by prior_approval). New limit at or under the
    approved limit. New stop at or under the approved stop, when both are
    present — a tighter stop is less risk, a wider stop is a new idea.
    New qty at or under the approved qty. A missing prior is not a yes.
    """
    prior = prior_approval(ticket)
    if prior is None:
        return False, "no_prior_approval"
    new_limit = _num(ticket.get("limit"))
    if new_limit is None:
        return False, "reprice_limit_unreadable"
    if new_limit > prior["limit"] + 1e-9:
        return False, "reprice_limit_raised"
    if prior["stop"] is not None:
        new_stop = _num(ticket.get("stop"))
        if new_stop is None or new_stop > prior["stop"] + 1e-9:
            return False, "reprice_stop_widened"
    if isinstance(prior["qty"], int) and not isinstance(prior["qty"], bool):
        try:
            new_qty = int(ticket.get("qty"))
        except (TypeError, ValueError):
            return False, "reprice_qty_unreadable"
        if new_qty > prior["qty"]:
            return False, "reprice_qty_raised"
    return True, "reprice_inside_prior"


def approve_ticket(ticket: dict, grants: dict, now: datetime) -> dict:
    """Return the ticket to write, and whether the desk's grant covered it.

    A ticket that is already ``approved`` with ``risk_stamped`` is unchanged.
    A PASS becomes approved, stamped ``desk_lead``, with a one-session shelf.
    A VETO is never approved here. A reprice carries the prior yes only
    inside reprice_keeps_approval. The caller still runs gate_outbox_ticket.
    """
    t = now_et(now)
    if ticket.get("status") == "approved" and ticket.get("risk_stamped") is True:
        return {"ticket": ticket, "acted": False, "reason": "already_approved"}
    if grants.get("revoked") or not grants.get("desk_may_approve_risk_pass"):
        return {"ticket": ticket, "acted": False, "reason": "grants_revoked"}
    verdict = risk_verdict(ticket)
    if verdict == "VETO":
        return {"ticket": ticket, "acted": False, "reason": "risk_veto"}
    carried, why = reprice_keeps_approval(ticket)
    if verdict != "PASS" and not (carried and grants.get("carry_reprice")):
        return {"ticket": ticket, "acted": False, "reason": why if verdict is None else "not_a_pass"}
    if verdict == "PASS" and ticket.get("carries_approval") and not carried:
        # A PASS that also claims a prior, and the prior says the risk grew,
        # does not get to wear the PASS as a way around the reprice rule.
        return {"ticket": ticket, "acted": False, "reason": why}
    stamped = dict(ticket)
    stamped["status"] = "approved"
    stamped["risk_stamped"] = True
    stamped["approved_by"] = "desk_lead"
    stamped["auth"] = "AMENDMENTS_2026-09-15 §7 standing grant"
    stamped["desk_approved_at"] = t.isoformat()
    if carried:
        stamped["approval_carried_from"] = prior_approval(ticket).get("ticket_id")
    return {"ticket": stamped, "acted": True, "reason": "desk_approved" if verdict == "PASS" else why}


def suggest_pullback(last: float, atr: float, cap: float | None, prior_limit: float | None) -> dict:
    """A buy limit one ATR under last, floored to the cent, never above the cap,
    never above the prior working limit.

    ``fillable`` is false when the only legal price is more than STALE_ATR
    under last. That is a flag for the desk, not a license to lift the cap.
    """
    if last <= 0 or atr <= 0:
        return {"limit": None, "reason": "price_unusable", "fillable": False}
    raw = last - PULLBACK_ATR * atr
    limit = math.floor(raw * 100.0 + 1e-9) / 100.0
    capped = False
    if cap is not None and limit > cap:
        limit = math.floor(cap * 100.0 + 1e-9) / 100.0
        capped = True
    if prior_limit is not None and limit > prior_limit:
        limit = prior_limit
    if limit <= 0:
        return {"limit": None, "reason": "limit_not_positive", "fillable": False}
    distance = (last - limit) / atr
    fillable = distance <= STALE_ATR
    reason = "one_atr_under_last"
    if capped and not fillable:
        reason = "cap_leaves_price_unstale_only_as_a_flag"
    elif capped:
        reason = "floored_to_cap"
    return {
        "limit": round(limit, 2),
        "distance_atr": round(distance, 3),
        "fillable": fillable,
        "reason": reason,
    }


def staleness(working_px: float, last: float, atr: float, sessions: int, cap: float | None) -> dict:
    """Flag a resting buy. Never an instruction to cancel.

    A buy at or under the cap while last is through the cap is a resting
    pullback. That is the order the cancel fix exists to keep. It is flagged
    stale only when it is also STALE_ATR under last for STALE_SESSIONS.
    """
    if atr <= 0 or last <= 0 or working_px <= 0:
        return {"action": "ok", "reason": "unmeasurable"}
    distance = (last - working_px) / atr
    resting = cap is not None and last > cap and working_px <= cap
    if sessions < STALE_SESSIONS:
        return {
            "action": "ok",
            "reason": "younger_than_3_sessions",
            "distance_atr": round(distance, 3),
            "resting_pullback": resting,
        }
    if distance > STALE_ATR:
        return {
            "action": "flag",
            "reason": "stale_pullback",
            "distance_atr": round(distance, 3),
            "resting_pullback": resting,
            "sessions": sessions,
        }
    return {
        "action": "ok",
        "reason": "inside_2_atr",
        "distance_atr": round(distance, 3),
        "resting_pullback": resting,
    }


def idle_cash(book: dict, rules: dict) -> dict:
    """Dollars above the 25% target, and the names that may take a pullback.

    Names are the live universe only. NOK and NVO are protect-only and are
    not offered. A name that already has a position or a working buy is not
    offered — the wire's own gate would kill that ticket, and proposing it
    is how the desk spent a week reminting into its own refusal.
    """
    equity = _num(book.get("equity"))
    cash = _num(book.get("cash"))
    out: dict = {
        "excess": 0.0,
        "cash_pct": None,
        "names": [],
        "reason": None,
    }
    if equity is None or cash is None or equity <= 0:
        out["reason"] = "cash_unmeasurable"
        return out
    pct = cash / equity
    out["cash_pct"] = round(pct, 4)
    if pct <= CASH_TARGET_PCT:
        out["reason"] = "cash_at_or_under_target"
        return out
    out["excess"] = round(cash - equity * CASH_TARGET_PCT, 2)
    positions = {
        str(p.get("symbol") or "").upper()
        for p in (book.get("positions") or [])
        if _num(p.get("qty")) not in (None, 0)
    }
    working = set()
    for order in book.get("orders") or []:
        status = str(order.get("status") or "").upper()
        if status in ("CANCELED", "CANCELLED", "FILLED", "REPLACED", "REJECTED", "EXPIRED"):
            continue
        side = str(order.get("side") or "").upper()
        if not side:
            for leg in order.get("legs") or order.get("orderLegCollection") or []:
                if "BUY" in str(leg.get("instruction") or "").upper():
                    side = "BUY"
        if side == "BUY":
            sym = order.get("symbol")
            if not sym:
                for leg in order.get("legs") or order.get("orderLegCollection") or []:
                    sym = (leg.get("instrument") or {}).get("symbol") or leg.get("symbol")
                    if sym:
                        break
            if sym:
                working.add(str(sym).upper())
    live = [str(s).upper() for s in (rules.get("universe") or ("ETHA", "IBIT"))]
    protect = {"NVO", "NOK"}
    for sym in live:
        if sym in protect or sym not in ("ETHA", "IBIT"):
            continue
        if sym in positions or sym in working:
            continue
        out["names"].append(sym)
    out["reason"] = "idle_cash" if out["names"] else "no_free_live_name"
    return out


def git_drift(repo_root: Path) -> dict:
    """Branch, HEAD, behind-count, and whether the wire file is dirty.

    Read-only. Does not fetch, commit, stash, or reset. The behind-count is
    against the remote SHA already on disk; a seat that has not fetched
    recently will under-count, and the line says so.
    """
    def _git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    sha = _git("rev-parse", "--short", "HEAD")
    remote = _git("rev-parse", "--short", f"origin/{branch}") if branch else None
    behind = None
    if branch and remote:
        counted = _git("rev-list", "--count", f"HEAD..origin/{branch}")
        if counted is not None and counted.isdigit():
            behind = int(counted)
    dirty = _git("status", "--porcelain", "--", "scripts/temple_flow_wire.py", "scripts/test_temple_flow_wire.py")
    return {
        "op": "git_drift",
        "branch": branch,
        "sha": sha,
        "remote_sha": remote,
        "behind": behind,
        "wire_dirty": bool(dirty),
        "wire_dirty_lines": (dirty or "").splitlines(),
        "fetched": False,
        "sent": False,
    }


def kraken_stamp() -> dict:
    """This Studio has no verified Kraken read. Say so, with the clock.

    Key presence is not verification. The MacBook is the only host that has
    confirmed a balance, and this function does not call it.
    """
    return {
        "op": "kraken_stamp",
        "status": "UNVERIFIED",
        "confirmed_at": None,
        "reason": "no Kraken read from this host this cycle",
        "sent": False,
    }


def yahoo_fallback_stamp(key_present: bool) -> dict:
    """The line the eyes path must print when Twelve Data cannot be asked.

    This does not fetch Yahoo. A Yahoo last is evidence, and the wire's
    live-eligibility check still requires a Schwab read before any POST.
    The stamp exists so a missing key is a log line instead of a silent miss.
    """
    if key_present:
        return {"op": "market_data", "source": "twelve_data", "fallback": None, "sent": False}
    return {
        "op": "market_data",
        "source": "yahoo_fallback",
        "fallback": "TWELVE_DATA_API_KEY missing; Yahoo is evidence-only and cannot authorize a POST",
        "sent": False,
    }
