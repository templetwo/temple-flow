#!/usr/bin/env python3
"""Temple Flow Act-loop wire (Studio daemon).

Default is DRY-RUN. Never prints tokens or secrets.
POST helper is real (TRIGGER GTC limit + attached stop; protect STOP GTC).
Default remains dry-run. launchd may pass --live when config/LIVE_OK exists.

Flags:
  --status   read-only book / orders / quotes (or box fallback)
  --once     one plan cycle (launchd path)
  --live     refused unless config/LIVE_OK AND TEMPLE_FLOW_LIVE=1

plan_actions(rules, book) is pure and unit-testable (no network).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
    for sym in PROTECT_ONLY:
        spec = protect.get(sym) or protect.get(sym.lower()) or {}
        stop = _f(spec.get("stop"))
        qty = position_qty(book, sym)
        if qty <= 0:
            continue
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
    """Hint book for the box (no spiral-broker). Not a live Schwab snapshot."""
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
        "armed": bool(rules.get("armed_hint", False)),
        "positions": positions,
        "orders": [],
        "quotes": {},
        "source": "fallback_hint",
        "in_rth": True,
    }


def fetch_book() -> tuple[dict | None, str]:
    """Read-only Schwab book. Never prints tokens, account hash, or secrets."""
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
        if ro.status_code == 200:
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
        if rq.status_code == 200:
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
            "source": "schwab_read",
            "token_safe": safe,
        }
        return book, "schwab_read"
    except Exception as e:
        return None, f"broker_error:{type(e).__name__}"


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
) -> dict:
    """Apply one planned action. Dry-run never marks sent.

    `sent` = an order was PLACED. `mutated` = broker state changed (place OR
    cancel). A cancel reports execute='canceled' + mutated=True, never sent.
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
        elif res.get("http") == 400:
            record_cancel_refusal(order_id, repo_root, now)
            out["execute"] = "cancel_refused_400_after_hours"
        else:
            out["execute"] = "cancel_failed"
        return out
    out["execute"] = "no_mutation"
    return out


# Ticket outcomes that clear the outbox. Everything else quarantines to
# failed/ — a refused ticket is never retried silently on the next cycle.
_TICKET_DONE = ("posted", "canceled", "skip_already_sent")


def run_cycle(
    rules: dict,
    book: dict,
    live: bool = False,
    broker_note: str = "",
    rules_path: str = "",
    repo_root: Path | None = None,
) -> list[dict]:
    rth = book.get("in_rth") if "in_rth" in book else in_rth()
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
                ticket_data, live=live, rules=rules, book=book, repo_root=repo_root
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
        if path is not None:
            move_ticket(
                path,
                "done" if e.get("execute") in _TICKET_DONE else "failed",
                repo_root,
            )

    planned = plan_actions(rules, book)
    executed = []
    for a in planned:
        e = execute_action(a, live=live, rth=rth, repo_root=repo_root)
        logj(e)
        executed.append(e)
    if not planned:
        logj(_action("skip", None, "no_planned_actions"))
    return [header] + outbox_results + executed


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


def gate_outbox_ticket(
    t: dict, rules: dict, book: dict, now: datetime | None = None
) -> tuple[str | None, dict]:
    """Apply the plan_actions gates to an outbox ticket.

    Returns (refusal_reason | None, detail). A ticket that clears every gate
    returns (None, detail) and only then may be POSTed.
    """
    detail: dict = {}
    errs = _ticket_schema_errors(t)
    if errs:
        return "ticket_schema_invalid", {"schema_errors": errs}

    action = str(t.get("action")).strip().lower()
    detail["action"] = action
    rth = book.get("in_rth")
    if rth is None:
        rth = in_rth(now)
    detail["in_rth"] = bool(rth)

    if action == "cancel_by_id":
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

    # arm + RTH, exactly as plan_actions gates a new entry
    if bool(rules.get("arm_required", True)) and not bool(book.get("armed")):
        return "arm_required", detail
    if not rth:
        return "outside_rth", detail

    # the same risk box a planned entry passes through
    box = risk_box(rules, book)
    if not box["ok"]:
        detail["risk_box"] = box["reasons"]
        return "new_risk_blocked", detail

    equity = box["equity"]
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

    if ticket_data.get("load_error"):
        out["execute"] = "refused"
        out["reason"] = "ticket_unreadable"
        out["error"] = ticket_data["load_error"]
        return out
    if not isinstance(rules, dict) or not rules:
        out["execute"] = "refused"
        out["reason"] = "rules_missing"
        return out
    if not isinstance(book, dict) or not book:
        out["execute"] = "refused"
        out["reason"] = "book_missing"
        return out

    existing_oid = t.get("schwab_order_id")
    if existing_oid:
        out["execute"] = "skip_already_sent"
        out["existing_order_id"] = existing_oid
        return out

    reason, detail = gate_outbox_ticket(t, rules, book, now)
    out["gate"] = detail
    if reason is not None:
        out["execute"] = "refused"
        out["reason"] = reason
        return out

    if not live:
        out["execute"] = "dry_run"
        out["reason"] = "gates_passed_would_post"
        return out

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
        out["execute"] = "refused"
        out["reason"] = "cancel_skipped_refused_today"
        return out
    res = cancel_by_id(order_id)
    out["schwab"] = {k: res.get(k) for k in ("http", "error")}
    if res.get("http") in (200, 204):
        out["mutated"] = True
        out["execute"] = "canceled"
    elif res.get("http") == 400:
        record_cancel_refusal(order_id, repo_root, now)
        out["execute"] = "cancel_refused_400_after_hours"
    else:
        out["execute"] = "cancel_failed"
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Temple Flow Act-loop wire (default dry-run)")
    p.add_argument("--status", action="store_true", help="read-only book/orders/quotes")
    p.add_argument("--once", action="store_true", help="one plan cycle")
    p.add_argument(
        "--live",
        action="store_true",
        help="POST when LIVE_OK + TEMPLE_FLOW_LIVE=1",
    )
    p.add_argument("--rules", default="", help="optional rules JSON path")
    args = p.parse_args(argv)

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
