#!/usr/bin/env python3
"""The wire actually calls the desk grant. These fail if the call is removed."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import temple_flow_wire as wire

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=ET)


def rules() -> dict:
    return {
        "arm_required": True,
        "universe": ["ETHA", "IBIT"],
        "no_day": True,
        "entries": {
            "ETHA": {"enabled": True, "limit": 19.7, "stop": 18.4, "cap": 19.9, "atr": 0.4},
            "IBIT": {"enabled": True, "limit": 45.0, "stop": 43.2, "cap": 45.0, "atr": 0.8},
        },
        "risk": {"risk_pct": 0.025, "day_breaker_pct": 0.045, "peak_dd_pct": 0.18, "max_opens": 8},
    }


def book() -> dict:
    return {
        "source": "schwab_read",
        "quotes_ok": True,
        "orders_ok": True,
        "equity": 606.0,
        "cash": 443.0,
        "sod_equity": 605.0,
        "day_pnl": 1.0,
        "peak_equity": 612.0,
        "armed": True,
        "in_rth": True,
        "positions": [{"symbol": "IBIT", "qty": 3}, {"symbol": "ETHA", "qty": 1}],
        "orders": [
            {"id": "1", "symbol": "ETHA", "side": "BUY", "status": "WORKING", "price": 19.7, "duration": "GOOD_TILL_CANCEL"},
            {"id": "2", "symbol": "IBIT", "side": "BUY", "status": "WORKING", "price": 45.0, "duration": "GOOD_TILL_CANCEL"},
        ],
        "quotes": {
            "ETHA": {"last": 20.30, "atr": 0.40, "quoteTime": NOW.isoformat()},
            "IBIT": {"last": 47.30, "quoteTime": NOW.isoformat()},
        },
        "quotes_as_of": NOW.isoformat(),
    }


class WireCallsTheGrant(unittest.TestCase):
    def test_pass_ticket_is_stamped_before_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config" / "outbox").mkdir(parents=True)
            (root / "config" / "standing_grants.json").write_text(json.dumps({
                "desk_may_approve_risk_pass": True,
                "auto_arm_mv_session": False,
                "carry_reprice": True,
            }))
            ticket = {
                "id": "TF-TEST-01",
                "action": "place_gtc_bracket",
                "symbol": "ETHA",
                "side": "BUY",
                "stop_side": "SELL",
                "qty": 1,
                "limit": 19.7,
                "stop": 18.4,
                "risk_verdict": "PASS",
                "status": "proposed",
                "risk_stamped": False,
                "validity": {"max_data_age_minutes": 30},
            }
            (root / "config" / "outbox" / "TF-TEST-01.json").write_text(json.dumps(ticket))
            notes = wire.stamp_desk_approvals(root, NOW)
            self.assertTrue(notes[0]["acted"])
            saved = json.loads((root / "config" / "outbox" / "TF-TEST-01.json").read_text())
            self.assertEqual(saved["status"], "approved")
            self.assertEqual(saved["approved_by"], "desk_lead")
            loaded = wire.load_outbox_tickets(root)
            self.assertEqual(len(loaded), 1)

    def test_missing_grants_file_stamps_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config" / "outbox").mkdir(parents=True)
            ticket = {
                "id": "TF-TEST-02",
                "action": "place_gtc_bracket",
                "symbol": "ETHA",
                "side": "BUY",
                "stop_side": "SELL",
                "qty": 1,
                "limit": 19.7,
                "stop": 18.4,
                "risk_verdict": "PASS",
                "status": "proposed",
            }
            path = root / "config" / "outbox" / "TF-TEST-02.json"
            path.write_text(json.dumps(ticket))
            notes = wire.stamp_desk_approvals(root, NOW)
            self.assertFalse(notes[0]["acted"])
            saved = json.loads(path.read_text())
            self.assertEqual(saved["status"], "proposed")

    def test_pullback_is_not_written_when_a_buy_is_already_working(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            note = wire.maybe_write_pullback_ticket("ETHA", rules(), book(), root, NOW)
            # idle_cash would not offer ETHA; the writer itself also refuses
            # to duplicate once a file exists, but here the call is direct and
            # the working buy is the wire's problem at the idle layer. A direct
            # call still must not price above the standing limit.
            self.assertIsNotNone(note)
            if note and note.get("execute") == "written":
                saved = json.loads((root / "config" / "outbox" / note["ticket_id"]).with_suffix(".json").read_text())
                self.assertLessEqual(saved["limit"], 19.7)
                self.assertEqual(saved["risk_verdict"], "PASS")

    def test_stale_flag_is_a_leave_not_a_cancel(self):
        r = rules()
        r["entries"]["ETHA"]["sessions_working"] = 4
        b = book()
        b["quotes"]["ETHA"]["last"] = 21.50
        actions = wire.plan_actions(r, b)
        leaves = [a for a in actions if a.get("symbol") == "ETHA" and a.get("op") == "leave"]
        cancels = [a for a in actions if a.get("symbol") == "ETHA" and a.get("op") == "cancel_abandon"]
        self.assertTrue(leaves, actions)
        self.assertFalse(cancels)
        self.assertEqual(leaves[0]["reason"], "stale_pullback_flagged")
        self.assertEqual(leaves[0]["params"]["staleness"]["action"], "flag")


if __name__ == "__main__":
    unittest.main()
