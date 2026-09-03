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
        "sent": False,
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


def execute_action(action: dict, live: bool) -> dict:
    """Apply one planned action. Dry-run never marks sent."""
    out = deepcopy(action)
    out["dry_run"] = not live
    out["sent"] = False
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
        out["execute"] = "posted" if out["sent"] else "post_failed"
        return out
    if op == "place_protect_stop":
        res = place_protect_stop(**params)
        out["schwab"] = {k: res.get(k) for k in ("http", "order_id", "error")}
        out["sent"] = res.get("http") in (200, 201)
        out["execute"] = "posted" if out["sent"] else "post_failed"
        return out
    if op == "cancel_abandon":
        order_id = params.get("order_id")
        if not order_id:
            out["execute"] = "cancel_failed_no_order_id"
            out["sent"] = False
            return out
        res = cancel_by_id(order_id)
        out["schwab"] = {k: res.get(k) for k in ("http", "error")}
        # HTTP 200/204 = success; 400 after hours on PENDING_ACTIVATION = leave it
        if res.get("http") in (200, 204):
            out["sent"] = True
            out["execute"] = "canceled"
        elif res.get("http") == 400:
            out["sent"] = False
            out["execute"] = "cancel_refused_400_after_hours"
        else:
            out["sent"] = False
            out["execute"] = "cancel_failed"
        return out
    out["execute"] = "no_mutation"
    return out


def run_cycle(
    rules: dict,
    book: dict,
    live: bool = False,
    broker_note: str = "",
    rules_path: str = "",
) -> list[dict]:
    header = {
        "op": "cycle",
        "mode": "live" if live else "dry-run",
        "broker": broker_note or book.get("source") or "unknown",
        "rules_path": rules_path,
        "equity": book.get("equity"),
        "armed": bool(book.get("armed")),
        "in_rth": book.get("in_rth") if "in_rth" in book else in_rth(),
        "sent": False,
        "dry_run": not live,
    }
    logj(header)
    
    # Process outbox tickets first
    outbox_tickets = load_outbox_tickets()
    for ticket_data in outbox_tickets:
        e = execute_outbox_ticket(ticket_data, live=live)
        logj(e)
        # Move ticket based on result
        if e.get("sent"):
            move_ticket(ticket_data["path"], "done")
        elif e.get("execute") in ("post_failed", "cancel_failed", "unknown_action"):
            move_ticket(ticket_data["path"], "failed")
    
    planned = plan_actions(rules, book)
    executed = []
    for a in planned:
        e = execute_action(a, live=live)
        logj(e)
        executed.append(e)
    if not planned:
        logj(_action("skip", None, "no_planned_actions"))
    return [header] + executed


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
    """Scan config/outbox/*.json for approved tickets. Never re-send WORKING."""
    root = repo_root or REPO_ROOT
    outbox = root / "config" / "outbox"
    if not outbox.exists():
        return []
    tickets = []
    for p in sorted(outbox.glob("*.json")):
        try:
            t = json.loads(p.read_text())
            if t.get("status") == "approved" and t.get("risk_stamped"):
                tickets.append({"ticket": t, "path": p})
        except Exception:
            pass
    return tickets


def move_ticket(src: Path, result: str, repo_root: Path | None = None) -> None:
    """Move ticket to done/ or failed/ subfolder."""
    root = repo_root or REPO_ROOT
    dest_folder = root / "config" / "outbox" / result
    dest_folder.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest_folder / src.name)
    except Exception:
        pass


def execute_outbox_ticket(ticket_data: dict, live: bool) -> dict:
    """Execute one approved ticket. Never re-send if order_id already WORKING."""
    t = ticket_data.get("ticket") or {}
    out = {
        "op": "outbox_ticket",
        "ticket_id": t.get("id"),
        "symbol": t.get("symbol"),
        "dry_run": not live,
        "sent": False,
    }
    if not live:
        out["execute"] = "dry_run"
        return out
    
    # Check if order_id already exists and is WORKING
    existing_oid = t.get("schwab_order_id")
    if existing_oid:
        out["execute"] = "skip_already_sent"
        out["existing_order_id"] = existing_oid
        return out
    
    action = t.get("action", "").lower()
    if action == "place_gtc_bracket":
        res = place_gtc_bracket(
            symbol=t.get("symbol"),
            qty=t.get("qty"),
            limit=t.get("limit"),
            stop=t.get("stop"),
            side=t.get("side", "BUY"),
            stop_side=t.get("stop_side", "SELL"),
        )
        out["schwab"] = {k: res.get(k) for k in ("http", "order_id", "error")}
        out["sent"] = res.get("http") in (200, 201)
        out["execute"] = "posted" if out["sent"] else "post_failed"
        return out
    elif action == "cancel_by_id":
        order_id = t.get("order_id")
        if not order_id:
            out["execute"] = "cancel_failed_no_order_id"
            return out
        res = cancel_by_id(order_id)
        out["schwab"] = {k: res.get(k) for k in ("http", "error")}
        if res.get("http") in (200, 204):
            out["sent"] = True
            out["execute"] = "canceled"
        elif res.get("http") == 400:
            out["sent"] = False
            out["execute"] = "cancel_refused_400_after_hours"
        else:
            out["sent"] = False
            out["execute"] = "cancel_failed"
        return out
    else:
        out["execute"] = "unknown_action"
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
        run_cycle(rules, book, live=live, broker_note=note, rules_path=rules_path)
        if args.live and not live:
            rc = 2
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
