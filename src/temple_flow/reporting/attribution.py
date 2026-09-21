"""Flow-adjusted Kraken mark vs FRIEND_PROFIT_BASELINE. Deposits are not profit."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from temple_flow.adapters.kraken import PAIR_ASSET, KrakenAdapter
from temple_flow.adapters.protocol import VenueUnavailable
from temple_flow.money import dstr, flow_adjusted_pnl


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASELINE = REPO_ROOT / "logs/snapshots/baseline_friend_profit_LATEST.json"


def load_friend_profit_baseline(path: Path | None = None) -> dict[str, Any]:
    """Read the marked baseline from the snapshot JSON. Do not hardcode 100."""
    dest = Path(path) if path is not None else DEFAULT_BASELINE
    data = json.loads(dest.read_text())
    kraken_cash = (
        data.get("kraken", {})
        .get("probe", {})
        .get("venues", {})
        .get("kraken_spot", {})
        .get("cash_available")
    )
    if kraken_cash is None or str(kraken_cash) == "":
        raise ValueError(f"baseline missing kraken cash_available: {dest}")
    schwab_eq = data.get("schwab", {}).get("equity")
    kraken_d = Decimal(str(kraken_cash))
    schwab_d = Decimal(str(schwab_eq)) if schwab_eq is not None else None
    combined = (schwab_d + kraken_d) if schwab_d is not None else None
    return {
        "path": str(dest),
        "label": data.get("label"),
        "kraken_baseline_zusd": kraken_d,
        "schwab_equity_documented": schwab_d,
        "combined_baseline_documented": combined,
        "schwab_re_read": False,
    }


def kraken_nav(*, adapter: KrakenAdapter | None = None, baseline_path: Path | None = None) -> dict[str, Any]:
    adapter = adapter or KrakenAdapter()
    try:
        snap = adapter.snapshot()
    except VenueUnavailable as exc:
        return {"ok": False, "unavailable": str(exc)}
    try:
        base = load_friend_profit_baseline(baseline_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "unavailable": f"baseline unreadable: {exc}"}
    cash = snap.cash_available or Decimal("0")
    pos_mv = Decimal("0")
    marks = []
    for p in snap.positions:
        pair = next((k for k, v in PAIR_ASSET.items() if v == p.symbol), None)
        last = None
        if pair:
            try:
                last = adapter.ticker(pair).get("last")
            except VenueUnavailable:
                last = None
        mv = (last * p.qty) if last is not None else None
        if mv is not None:
            pos_mv += mv
        marks.append(
            {
                "symbol": p.symbol,
                "qty": dstr(p.qty),
                "last": dstr(last) if last else None,
                "mv": dstr(mv) if mv else None,
            }
        )
    nav = cash + pos_mv
    pnl = flow_adjusted_pnl(dstr(base["kraken_baseline_zusd"]), dstr(nav), "0", "0")
    combined = base["combined_baseline_documented"]
    return {
        "ok": True,
        "source": snap.source,
        "kraken_nav": dstr(nav),
        "kraken_baseline_zusd": dstr(base["kraken_baseline_zusd"]),
        "kraken_flow_adjusted_pnl": dstr(pnl),
        "baseline_path": base["path"],
        "positions": marks,
        "cash": dstr(cash),
        "combined_baseline_documented": dstr(combined) if combined is not None else None,
        "schwab_re_read": False,
        "economic_evidence": "EXPERIMENTAL_UNPROVEN",
        "note": "Deposits are not P&L. Schwab leg of the combined baseline was not re-read here.",
    }
