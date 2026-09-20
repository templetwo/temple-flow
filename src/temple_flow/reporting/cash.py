"""explain-cash: funded vs reserved vs leftover. No simulated balances."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from temple_flow.adapters.kraken import KrakenAdapter
from temple_flow.adapters.protocol import VenueUnavailable
from temple_flow.money import dstr


def explain_kraken_cash() -> dict[str, Any]:
    adapter = KrakenAdapter()
    try:
        snap = adapter.snapshot()
    except VenueUnavailable as exc:
        return {"ok": False, "unavailable": str(exc), "note": "no paper cash substituted"}
    usd = snap.cash_available or Decimal("0")
    buy_reserved = Decimal("0")
    for o in snap.working_orders:
        if (o.side or "").upper() == "BUY" and o.remaining and o.price:
            buy_reserved += o.remaining * o.price
    eligible = usd  # Balance; may still include nothing for resting buys (Kraken-specific)
    leftover = usd
    return {
        "ok": True,
        "source": snap.source,
        "as_of": snap.as_of,
        "categories": {
            "balance_zusd": dstr(usd),
            "working_buy_notional": dstr(buy_reserved),
            "eligible_for_new_entries_estimate": dstr(max(usd - buy_reserved, Decimal("0"))),
            "leftover_after_existing_book": dstr(leftover),
        },
        "positions": [{"symbol": p.symbol, "qty": dstr(p.qty)} for p in snap.positions],
        "working_orders": [
            {
                "id": o.broker_order_id,
                "side": o.side,
                "type": o.order_type,
                "symbol": o.symbol,
                "price": dstr(o.price) if o.price is not None else None,
                "stop": dstr(o.stop_price) if o.stop_price is not None else None,
                "remaining": dstr(o.remaining) if o.remaining is not None else None,
            }
            for o in snap.working_orders
        ],
        "fee_source": "assetpairs_schedule_not_tradevolume",
        "note": "Balance may not exclude resting buy notional. Deposits are not P&L.",
    }
