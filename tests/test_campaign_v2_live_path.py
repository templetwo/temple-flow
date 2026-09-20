"""Live-first path: no paper substitution; fake broker stays in fixtures."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from temple_flow.adapters.credentials import kraken_key_names
from temple_flow.adapters.protocol import VenueUnavailable
from temple_flow.campaign.authority import PAPER_DIGEST, Authority
from temple_flow.campaign.contracts import ContractError
from temple_flow.control.preview import compile_live_definition
from temple_flow.execution.reservations import ReservationError, reserve_cash
from temple_flow.execution.service import DeskService
from temple_flow.ledger.store import LedgerStore
from temple_flow.money import dstr


class NoPaperSubstitution(unittest.TestCase):
    def test_compile_refuses_empty_probe(self):
        with self.assertRaises(ValueError):
            compile_live_definition(
                {
                    "mode": "READ_ONLY",
                    "venues": {
                        "schwab": {"capability_status": "UNAVAILABLE", "snapshot_source": None},
                        "kraken_spot": {"capability_status": "UNAVAILABLE", "snapshot_source": None},
                    },
                }
            )

    def test_compile_does_not_use_paper_100(self):
        d = compile_live_definition(
            {
                "venues": {
                    "schwab": {
                        "capability_status": "DOCUMENTED_ONLY",
                        "snapshot_source": "schwab_read",
                        "cash_available": "433.47",
                    }
                }
            }
        )
        self.assertEqual(d["mode"], "live")
        self.assertEqual(d["capital"]["basis_net_usd"], "433.47")
        self.assertNotEqual(d["capital"]["basis_net_usd"], "100")
        self.assertEqual(d["objective"]["kind"], "none")
        self.assertFalse(any(x["enabled"] for x in d["optional_limits"].values()))

    def test_paper_digest_rejected_for_live_go(self):
        tmp = tempfile.TemporaryDirectory()
        store = LedgerStore(Path(tmp.name) / "l.sqlite")
        auth = Authority(store)
        doc = json.loads((ROOT / "examples/campaign_v2/campaign.paper_100_to_200.json").read_text())
        prepared = auth.prepare(doc)
        with self.assertRaises(ContractError):
            auth.go(
                doc["campaign_id"],
                doc["revision"],
                prepared["policy_digest"],
                live=True,
            )
        self.assertEqual(prepared["policy_digest"], PAPER_DIGEST)
        store.close()
        tmp.cleanup()

    def test_service_starts_unarmed(self):
        tmp = tempfile.TemporaryDirectory()
        svc = DeskService(Path(tmp.name))
        self.assertEqual(svc.mode, "READ_ONLY")
        self.assertEqual(svc.entry_permission, "DISARMED")
        with patch.object(svc.adapters["schwab"], "capabilities") as cap, patch.object(
            svc.adapters["kraken_spot"], "capabilities"
        ) as kcap:
            from temple_flow.adapters.protocol import CapabilitySnapshot

            cap.return_value = CapabilitySnapshot("schwab", "a", {}, "t", "UNAVAILABLE")
            kcap.return_value = CapabilitySnapshot("kraken_spot", "a", {}, "t", "UNAVAILABLE")
            out = svc.run_once()
        self.assertFalse(out["submitted"])
        self.assertIsNone(out["probe"]["venues"]["schwab"].get("cash_available"))
        svc.close()
        tmp.cleanup()

    def test_kraken_private_posts_the_signed_body(self):
        from temple_flow.adapters.kraken import KrakenAdapter

        posted = {}

        class FakeResp:
            status_code = 200

            def json(self):
                return {"error": [], "result": {"ZUSD": "1"}}

        def fake_post(url, headers=None, data=None, timeout=None):
            posted["url"] = url
            posted["data"] = data
            posted["content_type"] = (headers or {}).get("Content-Type")
            return FakeResp()

        adapter = KrakenAdapter()
        with patch.object(adapter, "_keys", return_value=("k" * 56, "c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0")):
            with patch("requests.post", fake_post):
                adapter._private("/0/private/Balance")
        self.assertIsInstance(posted["data"], str)
        self.assertIn("nonce=", posted["data"])
        self.assertEqual(posted["content_type"], "application/x-www-form-urlencoded")

    def test_crypto_spot_declines_short_history(self):
        from temple_flow.strategies.crypto_spot import evaluate_pullback
        from decimal import Decimal

        out = evaluate_pullback("XBTUSD", [], Decimal("100"), "0.0026", "0.0016", "100", "0.0001")
        self.assertEqual(out["result"], "DECLINE")
        self.assertEqual(out["reason"], "HISTORY_UNPROVEN")

    def test_kraken_missing_keys_are_unavailable(self):
        from temple_flow.adapters.kraken import KrakenAdapter

        with patch.dict("os.environ", {"KRAKEN_API_KEY": "", "KRAKEN_API_SECRET": ""}, clear=False):
            with patch("temple_flow.adapters.credentials.env_files", return_value=[]):
                adapter = KrakenAdapter()
                with self.assertRaises(VenueUnavailable):
                    adapter.snapshot()


class ConcurrentReservations(unittest.TestCase):
    def test_two_threads_cannot_spend_the_same_dollar(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "l.sqlite"
        store = LedgerStore(path)
        store.ensure_account("kraken_spot", "PAPER_KRAKEN", {})
        store.db.execute(
            "INSERT INTO campaign_revisions VALUES ('c',1,'{}','h','t')"
        )
        store.db.execute(
            "INSERT INTO grants VALUES ('g','c',1,'p','h',1,'ACTIVE','t',NULL)"
        )
        store.db.execute(
            "INSERT INTO decisions VALUES ('d','c',1,'h',1,'PASS','{}','t')"
        )
        store.db.execute(
            "INSERT INTO intents VALUES ('i1','d','g','kraken_spot','PAPER_KRAKEN','c1','RESERVED','{}','t')"
        )
        store.db.execute(
            "INSERT INTO intents VALUES ('i2','d','g','kraken_spot','PAPER_KRAKEN','c2','RESERVED','{}','t')"
        )
        store.db.commit()
        store.set_cash("kraken_spot", "PAPER_KRAKEN", "100", "0")
        errors: list[str] = []

        def try_reserve(rid: str, iid: str):
            other = LedgerStore(path)
            try:
                reserve_cash(other, "kraken_spot", "PAPER_KRAKEN", Decimal("80"), rid, iid)
            except ReservationError as exc:
                errors.append(str(exc))
            finally:
                other.close()

        t1 = threading.Thread(target=try_reserve, args=("r1", "i1"))
        t2 = threading.Thread(target=try_reserve, args=("r2", "i2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        avail, reserved = store.get_cash("kraken_spot", "PAPER_KRAKEN")
        self.assertEqual(Decimal(reserved) + Decimal(avail), Decimal("100"))
        self.assertEqual(len(errors), 1)
        store.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
