"""Broker truth vs ledger. Writes a local receipt, not a git secret."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from temple_flow.adapters.kraken import KrakenAdapter
from temple_flow.adapters.protocol import VenueUnavailable
from temple_flow.money import dstr


def reconcile_kraken(state_dir: Path, txids: list[str] | None = None) -> dict[str, Any]:
    adapter = KrakenAdapter()
    try:
        snap = adapter.snapshot()
    except VenueUnavailable as exc:
        return {"ok": False, "unavailable": str(exc)}
    queried = {}
    for txid in txids or []:
        try:
            queried[txid] = adapter._private("/0/private/QueryOrders", {"txid": txid, "trades": True})
        except VenueUnavailable as exc:
            queried[txid] = {"error": str(exc)}
    out = {
        "ok": True,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cash": dstr(snap.cash_available) if snap.cash_available is not None else None,
        "positions": [{"symbol": p.symbol, "qty": dstr(p.qty)} for p in snap.positions],
        "working_orders": [
            {
                "id": o.broker_order_id,
                "side": o.side,
                "type": o.order_type,
                "symbol": o.symbol,
                "price": dstr(o.price) if o.price is not None else None,
                "stop": dstr(o.stop_price) if o.stop_price is not None else None,
            }
            for o in snap.working_orders
        ],
        "query_orders": {k: "present" if v and "error" not in v else v for k, v in queried.items()},
        "known": {
            "OUNTNO-XBVAK-EPG6QI": "filled parent; do not cancel",
            "O55VHG-TY4DM-O3KIJT": "working native stop on XXBT 0.0012",
        },
    }
    dest = Path(state_dir) / "logs"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "reconcile_latest.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    out["receipt"] = str(path)
    return out
