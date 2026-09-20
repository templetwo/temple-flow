"""Flow-adjusted Kraken mark vs FRIEND_PROFIT_BASELINE. Deposits are not profit."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from temple_flow.adapters.kraken import PAIR_ASSET, KrakenAdapter
from temple_flow.adapters.protocol import VenueUnavailable
from temple_flow.money import dstr, flow_adjusted_pnl


KRAKEN_BASELINE_ZUSD = Decimal("100")
COMBINED_BASELINE = Decimal("701.40")  # documented mark, not re-verified Schwab


def kraken_nav() -> dict[str, Any]:
    adapter = KrakenAdapter()
    try:
        snap = adapter.snapshot()
    except VenueUnavailable as exc:
        return {"ok": False, "unavailable": str(exc)}
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
        marks.append({"symbol": p.symbol, "qty": dstr(p.qty), "last": dstr(last) if last else None, "mv": dstr(mv) if mv else None})
    nav = cash + pos_mv
    # No Kraken deposit after baseline in this campaign.
    pnl = flow_adjusted_pnl(dstr(KRAKEN_BASELINE_ZUSD), dstr(nav), "0", "0")
    return {
        "ok": True,
        "source": snap.source,
        "kraken_nav": dstr(nav),
        "kraken_baseline_zusd": dstr(KRAKEN_BASELINE_ZUSD),
        "kraken_flow_adjusted_pnl": dstr(pnl),
        "positions": marks,
        "cash": dstr(cash),
        "combined_baseline_documented": dstr(COMBINED_BASELINE),
        "schwab_re_read": False,
        "economic_evidence": "EXPERIMENTAL_UNPROVEN",
        "note": "Deposits are not P&L. Schwab leg of the combined baseline was not re-read here.",
    }
