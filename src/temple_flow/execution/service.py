"""Persistent desk service. Starts READ_ONLY / UNARMED. Never auto-PAPER."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from temple_flow.adapters.protocol import AccountSnapshot, VenueUnavailable
from temple_flow.adapters.schwab import SchwabAdapter
from temple_flow.adapters.kraken import KrakenAdapter
from temple_flow.ledger.store import LedgerStore
from temple_flow.money import dstr


class DeskService:
    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = LedgerStore(self.state_dir / "ledger.sqlite")
        self.mode = "READ_ONLY"
        self.entry_permission = "DISARMED"
        self.adapters: dict[str, Any] = {
            "schwab": SchwabAdapter(),
            "kraken_spot": KrakenAdapter(),
        }

    def close(self) -> None:
        self.store.close()

    def probe(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mode": self.mode,
            "entry_permission": self.entry_permission,
            "venues": {},
        }
        for name, adapter in self.adapters.items():
            try:
                cap = adapter.capabilities()
                snap: AccountSnapshot | None = None
                err = None
                try:
                    snap = adapter.snapshot()
                except VenueUnavailable as exc:
                    err = str(exc)
                out["venues"][name] = {
                    "capability_status": cap.status if snap else "UNAVAILABLE",
                    "features": cap.features,
                    "snapshot_source": snap.source if snap else None,
                    "cash_available": dstr(snap.cash_available) if snap and snap.cash_available is not None else None,
                    "equity": dstr(snap.equity) if snap and snap.equity is not None else None,
                    "positions": [
                        {"symbol": p.symbol, "qty": dstr(p.qty)} for p in (snap.positions if snap else [])
                    ],
                    "working_orders": [
                        {
                            "id": o.broker_order_id,
                            "symbol": o.symbol,
                            "side": o.side,
                            "status": o.status,
                            "type": o.order_type,
                            "stop": dstr(o.stop_price) if o.stop_price is not None else None,
                        }
                        for o in (snap.working_orders if snap else [])
                    ]
                    if snap
                    else [],
                    "orders_ok": snap.orders_ok if snap else False,
                    "unavailable": err,
                    "note": "no simulated balances substituted",
                }
                if snap and snap.cash_available is not None:
                    self.store.ensure_account(name, adapter.account_alias, {"source": snap.source})
                    self.store.set_cash(name, adapter.account_alias, dstr(snap.cash_available), "0")
            except VenueUnavailable as exc:
                out["venues"][name] = {
                    "capability_status": "UNAVAILABLE",
                    "unavailable": str(exc),
                    "snapshot_source": None,
                    "cash_available": None,
                    "positions": [],
                    "working_orders": [],
                    "note": "no simulated balances substituted",
                }
        (self.state_dir / "last_probe.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
        return out

    def run_once(self) -> dict[str, Any]:
        """Reconcile reads. Does not submit. Paper is not a fallback."""
        probe = self.probe()
        return {
            "mode": self.mode,
            "entry_permission": self.entry_permission,
            "submitted": False,
            "probe": probe,
        }

    def serve(self, cycles: int = 0, interval_s: float = 5.0) -> None:
        n = 0
        while True:
            self.run_once()
            n += 1
            if cycles and n >= cycles:
                return
            time.sleep(interval_s)
