"""Venue flatten. Default dry-run. Does not touch Schwab from this host."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from temple_flow.adapters.kraken import PAIR_ASSET, KrakenAdapter
from temple_flow.adapters.protocol import SubmitAck, VenueUnavailable
from temple_flow.execution.writer import WriterLease
from temple_flow.money import dstr


def flatten_kraken(state_dir, *, send: bool) -> dict[str, Any]:
    adapter = KrakenAdapter()
    snap = adapter.snapshot()
    lease = WriterLease(state_dir, "kraken_spot", adapter.account_alias)
    permit = lease.permit()
    plan: list[dict[str, Any]] = []
    for o in snap.working_orders:
        plan.append(
            {
                "action": "cancel",
                "id": o.broker_order_id,
                "symbol": o.symbol,
                "side": o.side,
                "type": o.order_type,
            }
        )
    for p in snap.positions:
        if not p.qty or p.qty <= 0:
            continue
        pair = next((k for k, v in PAIR_ASSET.items() if v == p.symbol), p.symbol)
        plan.append({"action": "market_sell", "symbol": pair, "qty": dstr(p.qty)})
    if not send:
        return {
            "dry_run": True,
            "submitted": False,
            "plan": plan,
            "cash": dstr(snap.cash_available) if snap.cash_available is not None else None,
            "note": "Pass --send to execute. Cancels working orders then market-sells adopted qty.",
        }
    if not permit:
        return {"dry_run": False, "submitted": False, "error": "blocked_no_writer", "plan": plan}
    results = []
    for step in plan:
        if step["action"] == "cancel":
            ack = adapter.cancel(step["id"], permit)
            results.append({**step, "result": ack.result, "detail": ack.detail})
        elif step["action"] == "market_sell":
            try:
                fees = adapter.pair_fees(step["symbol"])
                payload = {
                    "pair": step["symbol"],
                    "type": "sell",
                    "ordertype": "market",
                    "volume": step["qty"],
                }
                rec = adapter._private("/0/private/AddOrder", payload)
                txid = (rec.get("txid") or [None])[0]
                ack = SubmitAck("ACCEPTED", txid, "flatten_market")
            except VenueUnavailable as exc:
                ack = SubmitAck("UNKNOWN", None, str(exc))
            results.append({**step, "result": ack.result, "order_id": ack.broker_order_id, "detail": ack.detail})
    return {"dry_run": False, "submitted": True, "plan": results, "fee_source": "assetpairs_schedule_not_tradevolume"}
