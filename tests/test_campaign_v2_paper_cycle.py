"""Paper campaign-to-fill cycle. Isolated state. Fake broker. No live sends."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from temple_flow.allocation.allocator import allocate_funded_weighted_v1
from temple_flow.campaign.contracts import ContractError
from temple_flow.control.commands import Desk
from temple_flow.ledger.store import LedgerStore
from temple_flow.money import dstr


class PaperCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.desk = Desk(self.state)
        self.campaign = ROOT / "examples/campaign_v2/campaign.paper_100_to_200.json"

    def tearDown(self):
        self.desk.store.close()
        self.tmp.cleanup()

    def test_paper_cycle_without_human_ticket(self):
        out = self.desk.paper_cycle(self.campaign)
        self.assertTrue(out["go_repeat_idempotent"])
        self.assertEqual(out["fee_negative"]["result"], "DECLINE")
        self.assertIn("NO_NET_EDGE", out["fee_negative"]["reason_codes"])
        self.assertEqual(out["qualifying"]["result"], "PASS")
        self.assertEqual(out["submit"]["result"], "ACCEPTED")
        self.assertTrue(out["fills"]["first_applied"])
        self.assertTrue(out["fills"]["duplicate_noop"])
        self.assertTrue(out["fills"]["second_applied"])
        self.assertEqual(out["unknown_recovery"], "ACCEPTED")
        self.assertGreaterEqual(out["restart_lot_count"], 2)
        self.assertEqual(out["restart_fill_count"], 2)
        self.assertEqual(out["status"]["entry_permission"], "ENABLED")
        self.assertEqual(out["status"]["economic_evidence"], "EXPERIMENTAL_UNPROVEN")
        # No per-trade approve field on the path
        self.assertFalse(json.loads(self.campaign.read_text())["execution"]["per_trade_human_approval"])

    def test_stale_digest_is_rejected(self):
        prepared = self.desk.prepare(self.campaign)
        with self.assertRaises(ContractError):
            self.desk.go(
                prepared["campaign"]["campaign_id"],
                prepared["campaign"]["revision"],
                "0" * 64,
            )

    def test_forged_activation_in_file_is_not_a_grant(self):
        from temple_flow.campaign.contracts import validate_document

        doc = json.loads(self.campaign.read_text())
        doc["activation"]["enabled"] = True
        doc["activation"]["grant_id"] = "forged"
        doc["activation"]["deployment_receipt_id"] = "forged"
        doc["activation"]["policy_digest"] = "0" * 64
        validate_document(doc)
        self.assertIsNone(self.desk.store.get_active_grant(doc["campaign_id"]))

    def test_full_loss_allocator_is_not_18_percent(self):
        sized = allocate_funded_weighted_v1(
            "100",
            [
                {
                    "candidate_id": "A",
                    "venue": "kraken_spot",
                    "instrument_id": "FIXTURE/USD",
                    "weight": "1",
                    "worst_entry": "10",
                    "modeled_exit": "11",
                    "entry_fee_fraction": "0.004",
                    "exit_fee_fraction": "0.004",
                    "increment": "0.01",
                }
            ],
            profile="full_loss_research",
        )
        self.assertEqual(len(sized), 1)
        self.assertGreater(sized[0]["quantity"] * Decimal("10"), Decimal("18"))
        self.assertLessEqual(sized[0]["cash_required"], Decimal("100"))

    def test_proportional_weights(self):
        sized = allocate_funded_weighted_v1(
            "100",
            [
                {
                    "candidate_id": "A",
                    "venue": "kraken_spot",
                    "instrument_id": "A/USD",
                    "weight": "3",
                    "worst_entry": "1",
                    "modeled_exit": "2",
                    "entry_fee_fraction": "0",
                    "exit_fee_fraction": "0",
                    "increment": "1",
                },
                {
                    "candidate_id": "B",
                    "venue": "kraken_spot",
                    "instrument_id": "B/USD",
                    "weight": "1",
                    "worst_entry": "1",
                    "modeled_exit": "2",
                    "entry_fee_fraction": "0",
                    "exit_fee_fraction": "0",
                    "increment": "1",
                },
            ],
            profile="full_loss_research",
        )
        by_id = {c["candidate_id"]: c for c in sized}
        self.assertEqual(by_id["A"]["cash_required"], Decimal("75"))
        self.assertEqual(by_id["B"]["cash_required"], Decimal("25"))

    def test_restart_reconstructs_lots(self):
        self.desk.paper_cycle(self.campaign)
        path = self.desk.store.path
        self.desk.store.close()
        restarted = LedgerStore(path)
        lots = restarted.lots("TF-CAMPAIGN-PAPER-DEMO")
        self.assertGreaterEqual(len(lots), 2)
        restarted.close()
        # reopen for tearDown
        self.desk.store = LedgerStore(path)


class DDLSmoke(unittest.TestCase):
    def test_fill_unique_and_money_text(self):
        import sqlite3

        db = sqlite3.connect(":memory:")
        db.executescript((ROOT / "src/temple_flow/ledger_schema.sql").read_text())
        db.execute("INSERT INTO campaign_revisions VALUES ('c',1,'{}','hash','t')")
        db.execute("INSERT INTO accounts VALUES ('paper','a','{}','v1')")
        db.execute("INSERT INTO grants VALUES ('g','c',1,'fixture','hash',1,'fixture','t',NULL)")
        db.execute("INSERT INTO decisions VALUES ('d','c',1,'hash',1,'PASS','{}','t')")
        db.execute("INSERT INTO intents VALUES ('i','d','g','paper','a','client','RESERVED','{}','t')")
        db.execute("INSERT INTO broker_orders VALUES ('paper','a','o','i',NULL,'OPEN','fixture')")
        row = ("paper", "a", "f", "o", "1", "10", "0.04", "USD", "t", "t", "fixture")
        db.execute("INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
        db.close()


if __name__ == "__main__":
    unittest.main()
