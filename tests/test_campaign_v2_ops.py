"""Flatten/cash/attribution helpers. No live send."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from temple_flow.adapters.protocol import AccountSnapshot, Position, WorkingOrder
from temple_flow.money import flow_adjusted_pnl


def _snap():
    return AccountSnapshot(
        venue="kraken_spot",
        account_alias="KRAKEN_RESEARCH",
        source="kraken_read",
        as_of="t",
        version=1,
        cash_available=Decimal("2.1165"),
        equity=None,
        sod_equity=None,
        positions=[Position(symbol="XXBT", qty=Decimal("0.0012"))],
        working_orders=[
            WorkingOrder(
                broker_order_id="O55VHG-TY4DM-O3KIJT",
                symbol="XBTUSD",
                side="SELL",
                status="open",
                order_type="stop-loss",
                price=Decimal("78454.6"),
                stop_price=Decimal("78454.6"),
                qty=Decimal("0.0012"),
                remaining=Decimal("0.0012"),
            )
        ],
        quotes={},
        orders_ok=True,
        quotes_ok=False,
    )


class OpsTests(unittest.TestCase):
    def test_flatten_dry_run_lists_stop_then_sell(self):
        from temple_flow.execution.flatten import flatten_kraken

        with patch("temple_flow.execution.flatten.KrakenAdapter.snapshot", return_value=_snap()):
            with patch("temple_flow.execution.flatten.WriterLease.permit", return_value="live-writer-1"):
                out = flatten_kraken(Path("/tmp"), send=False)
        self.assertTrue(out["dry_run"])
        self.assertFalse(out["submitted"])
        actions = [s["action"] for s in out["plan"]]
        self.assertIn("cancel", actions)
        self.assertIn("market_sell", actions)

    def test_deposit_not_pnl(self):
        self.assertEqual(flow_adjusted_pnl("100", "200", "100", "0"), 0)


if __name__ == "__main__":
    unittest.main()
