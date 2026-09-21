"""Flatten/cash/attribution/cycle leftovers. No live send."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from temple_flow.adapters.protocol import AccountSnapshot, Position, SubmitAck, WorkingOrder
from temple_flow.ledger.store import LedgerStore
from temple_flow.money import flow_adjusted_pnl, min_entry_notional


DIGEST = "a" * 64


def _snap(*, cash="2.1165", extra_orders=None):
    orders = [
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
    ]
    if extra_orders:
        orders.extend(extra_orders)
    return AccountSnapshot(
        venue="kraken_spot",
        account_alias="KRAKEN_RESEARCH",
        source="kraken_read",
        as_of="t",
        version=1,
        cash_available=Decimal(cash),
        equity=None,
        sod_equity=None,
        positions=[Position(symbol="XXBT", qty=Decimal("0.0012"))],
        working_orders=orders,
        quotes={},
        orders_ok=True,
        quotes_ok=False,
    )


def _eth_pass(**overrides):
    ev = {
        "result": "PASS",
        "reason": "TREND_CONTINUATION_POC",
        "pair": "ETHUSD",
        "quantity_hint": "0.001",
        "limit": "2627.87",
        "stop": "2500.00",
        "modeled_exit": "2700.00",
        "net": "1",
        "economic_evidence": "EXPERIMENTAL_UNPROVEN",
        "weight": "1",
        "entry_fee_fraction": "0.0026",
        "exit_fee_fraction": "0.0026",
        "increment": "0.001",
        "worst_entry": "2627.87",
    }
    ev.update(overrides)
    return ev


def _campaign():
    return {
        "campaign_id": "TF-CAMPAIGN-LIVE",
        "revision": 1,
        "mode": "live",
        "profile": "full_loss_research",
        "economic_evidence": "EXPERIMENTAL_UNPROVEN",
        "execution": {
            "poc_trend_continuation": True,
            "emergency_exit_protocol_id": "native-stop-then-flatten",
        },
    }


def _grant():
    return {"grant_id": "g1", "generation": 1, "policy_digest": DIGEST}


def _seed(store: LedgerStore):
    store.put_campaign_revision(
        {"campaign_id": "TF-CAMPAIGN-LIVE", "revision": 1},
        DIGEST,
    )
    store.set_entry_permission("TF-CAMPAIGN-LIVE", "ENABLED")


def _fees(pair="ETHUSD"):
    if pair == "XBTUSD":
        return {
            "taker": "0.0026",
            "maker": "0.0016",
            "pair_decimals": "1",
            "lot_decimals": "8",
            "ordermin": "0.00005",
            "wsname": "XBT/USD",
            "fee_source": "assetpairs_schedule_not_tradevolume",
        }
    return {
        "taker": "0.0026",
        "maker": "0.0016",
        "pair_decimals": "2",
        "lot_decimals": "8",
        "ordermin": "0.001",
        "wsname": "ETH/USD",
        "fee_source": "assetpairs_schedule_not_tradevolume",
    }


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
        cancel = next(s for s in out["plan"] if s["action"] == "cancel")
        self.assertEqual(cancel["role"], "covering_stop")
        self.assertIn("Cycle never cancels covering stops", out["note"])

    def test_flatten_labels_orphaned_working_buy(self):
        from temple_flow.execution.flatten import flatten_kraken

        extra = WorkingOrder(
            broker_order_id="ORPHAN-BUY",
            symbol="ETHUSD",
            side="BUY",
            status="open",
            order_type="limit",
            price=Decimal("2000"),
            qty=Decimal("0.01"),
            remaining=Decimal("0.01"),
        )
        with patch("temple_flow.execution.flatten.KrakenAdapter.snapshot", return_value=_snap(extra_orders=[extra])):
            with patch("temple_flow.execution.flatten.WriterLease.permit", return_value="live-writer-1"):
                out = flatten_kraken(Path("/tmp"), send=False)
        roles = {s["id"]: s["role"] for s in out["plan"] if s["action"] == "cancel"}
        self.assertEqual(roles["O55VHG-TY4DM-O3KIJT"], "covering_stop")
        self.assertEqual(roles["ORPHAN-BUY"], "orphaned")

    def test_deposit_not_pnl(self):
        self.assertEqual(flow_adjusted_pnl("100", "200", "100", "0"), 0)

    def test_min_entry_notional_eth_dust(self):
        n = min_entry_notional(Decimal("2627.87"), "0.001", "0.0026")
        self.assertGreater(n, Decimal("2.1165"))
        self.assertLess(n, Decimal("3"))

    def test_explain_cash_names_dust(self):
        from temple_flow.reporting.cash import explain_kraken_cash

        adapter = MagicMock()
        adapter.snapshot.return_value = _snap()

        def ticker(pair):
            return {"last": Decimal("81070.1") if pair == "XBTUSD" else Decimal("2627.87")}

        def fees(pair):
            return _fees(pair)

        adapter.ticker.side_effect = ticker
        adapter.pair_fees.side_effect = fees
        out = explain_kraken_cash(adapter=adapter)
        self.assertTrue(out["ok"])
        cats = out["categories"]
        self.assertEqual(cats["settled_available_zusd"], "2.1165")
        self.assertEqual(cats["leftover_after_fill"], "2.1165")
        self.assertTrue(cats["ineligible_dust"])
        self.assertEqual(out["working_orders"][0]["role"], "covering_stop")
        covers = {p["pair"]: p["leftover_covers"] for p in out["ineligible_dust_vs_pair_min"]}
        self.assertFalse(covers["ETHUSD"])
        self.assertFalse(covers["XBTUSD"])

    def test_attribution_parses_baseline_json(self):
        from temple_flow.reporting.attribution import kraken_nav, load_friend_profit_baseline

        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "base.json"
        path.write_text(
            json.dumps(
                {
                    "label": "FRIEND_PROFIT_BASELINE",
                    "kraken": {
                        "probe": {
                            "venues": {
                                "kraken_spot": {"cash_available": "100"}
                            }
                        }
                    },
                    "schwab": {"equity": 601.4},
                }
            )
        )
        base = load_friend_profit_baseline(path)
        self.assertEqual(base["kraken_baseline_zusd"], Decimal("100"))
        self.assertEqual(base["combined_baseline_documented"], Decimal("701.4"))
        adapter = MagicMock()
        adapter.snapshot.return_value = _snap()
        adapter.ticker.return_value = {"last": Decimal("80000")}
        out = kraken_nav(adapter=adapter, baseline_path=path)
        self.assertTrue(out["ok"])
        self.assertEqual(out["kraken_baseline_zusd"], "100")
        self.assertNotEqual(out["kraken_nav"], "100")
        self.assertEqual(out["baseline_path"], str(path))
        tmp.cleanup()

    def test_attribution_reads_repo_baseline(self):
        from temple_flow.reporting.attribution import load_friend_profit_baseline

        base = load_friend_profit_baseline()
        self.assertEqual(str(base["kraken_baseline_zusd"]), "100")
        self.assertEqual(base["label"], "FRIEND_PROFIT_BASELINE")


class CycleLeftoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = LedgerStore(Path(self.tmp.name) / "l.sqlite")
        _seed(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _run(self, pullback, *, cash="2.1165", send=True, permit="live-writer-1", submit=None):
        from temple_flow.execution.kraken_cycle import run_kraken_cycle

        adapter = MagicMock()
        adapter.account_alias = "KRAKEN_RESEARCH"
        adapter.snapshot.return_value = _snap(cash=cash)
        adapter.ticker.return_value = {"last": Decimal("2627.87")}
        adapter.ohlc.return_value = [[0] * 6] * 60
        adapter.pair_fees.return_value = _fees("ETHUSD")
        adapter.submit.return_value = submit or SubmitAck("ACCEPTED", "OID", "accepted")
        with patch("temple_flow.execution.kraken_cycle.KrakenAdapter", return_value=adapter):
            with patch("temple_flow.execution.kraken_cycle.evaluate_pullback", return_value=pullback):
                with patch(
                    "temple_flow.execution.kraken_cycle.WriterLease.permit",
                    return_value=permit,
                ):
                    out = run_kraken_cycle(
                        self.store,
                        Path(self.tmp.name),
                        _campaign(),
                        _grant(),
                        send=send,
                    )
        out["_adapter"] = adapter
        return out

    def test_dust_skips_send_and_persists(self):
        out = self._run(_eth_pass(), send=True)
        eth = next(e for e in out["evaluations"] if e["pair"] == "ETHUSD")
        xbt = next(e for e in out["evaluations"] if e["pair"] == "XBTUSD")
        self.assertEqual(xbt["reason"], "ALREADY_LONG")
        self.assertEqual(eth["result"], "PASS")
        self.assertEqual(eth["send"], "leftover_below_ordermin")
        self.assertEqual(out["submitted"], [])
        out["_adapter"].submit.assert_not_called()
        rows = self.store.db.execute("SELECT result, decision_json FROM decisions").fetchall()
        reasons = []
        for result, body in rows:
            reasons.extend(json.loads(body)["reason_codes"])
        self.assertIn("ALREADY_LONG", reasons)
        self.assertIn("INELIGIBLE_DUST", reasons)

    def test_missing_stop_refuses_send(self):
        out = self._run(_eth_pass(stop=None), cash="100", send=True)
        eth = next(e for e in out["evaluations"] if e["pair"] == "ETHUSD")
        self.assertEqual(eth["send"], "blocked_stop_missing")
        self.assertEqual(out["submitted"], [])
        out["_adapter"].submit.assert_not_called()
        bodies = [
            json.loads(r[0])
            for r in self.store.db.execute("SELECT decision_json FROM decisions").fetchall()
        ]
        codes = [c for b in bodies for c in b["reason_codes"]]
        self.assertIn("STOP_MISSING", codes)

    def test_funded_pass_submits_once(self):
        out = self._run(_eth_pass(), cash="100", send=True)
        eth = next(e for e in out["evaluations"] if e["pair"] == "ETHUSD")
        self.assertEqual(eth["result"], "PASS")
        self.assertEqual(out["submitted"][0]["result"], "ACCEPTED")
        out["_adapter"].submit.assert_called_once()
        intent = out["_adapter"].submit.call_args[0][0]
        self.assertTrue(Decimal(intent["protective_stop_price"]) > 0)
        pass_rows = self.store.db.execute(
            "SELECT result FROM decisions WHERE result='PASS'"
        ).fetchall()
        self.assertEqual(len(pass_rows), 1)


if __name__ == "__main__":
    unittest.main()
