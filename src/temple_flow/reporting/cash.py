"""explain-cash: funded vs reserved vs leftover. No simulated balances."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from temple_flow.adapters.kraken import SPOT_PAIRS, KrakenAdapter
from temple_flow.adapters.protocol import VenueUnavailable
from temple_flow.execution.flatten import held_assets, working_order_role
from temple_flow.money import dstr, min_entry_notional


def explain_kraken_cash(*, adapter: KrakenAdapter | None = None) -> dict[str, Any]:
    adapter = adapter or KrakenAdapter()
    try:
        snap = adapter.snapshot()
    except VenueUnavailable as exc:
        return {"ok": False, "unavailable": str(exc), "note": "no paper cash substituted"}
    usd = snap.cash_available or Decimal("0")
    buy_reserved = Decimal("0")
    held = held_assets(snap.positions)
    for o in snap.working_orders:
        if (o.side or "").upper() == "BUY" and o.remaining and o.price:
            buy_reserved += o.remaining * o.price
    leftover = usd - buy_reserved
    if leftover < 0:
        leftover = Decimal("0")
    pair_mins: list[dict[str, Any]] = []
    dust_pairs: list[str] = []
    for pair in SPOT_PAIRS:
        rec: dict[str, Any] = {"pair": pair}
        try:
            last = adapter.ticker(pair).get("last")
            fees = adapter.pair_fees(pair)
            if last is None:
                rec["error"] = "NO_LAST"
                pair_mins.append(rec)
                continue
            min_n = min_entry_notional(last, fees["ordermin"], fees["taker"])
            rec.update(
                {
                    "last": dstr(last),
                    "ordermin": fees["ordermin"],
                    "min_entry_notional": dstr(min_n),
                    "leftover_covers": leftover >= min_n,
                }
            )
            if leftover < min_n:
                dust_pairs.append(pair)
        except VenueUnavailable as exc:
            rec["error"] = str(exc)[:200]
        pair_mins.append(rec)
    return {
        "ok": True,
        "source": snap.source,
        "as_of": snap.as_of,
        "categories": {
            "settled_available_zusd": dstr(usd),
            "working_buy_notional": dstr(buy_reserved),
            "leftover_after_fill": dstr(leftover),
            "eligible_for_new_entries_estimate": dstr(leftover),
            "ineligible_dust": leftover > 0 and len(dust_pairs) == len(SPOT_PAIRS) and all(
                "error" not in p for p in pair_mins
            ),
        },
        "ineligible_dust_vs_pair_min": pair_mins,
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
                "role": working_order_role(o, held),
            }
            for o in snap.working_orders
        ],
        "fee_source": "assetpairs_schedule_not_tradevolume",
        "note": (
            "settled_available is Kraken Balance ZUSD. leftover_after_fill subtracts "
            "working buy notional. ineligible_dust is leftover below every pair ordermin. "
            "Deposits are not P&L."
        ),
    }
