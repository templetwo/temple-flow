#!/usr/bin/env python3
"""Unit tests for temple_flow_wire.plan_actions — no network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from temple_flow_wire import (  # noqa: E402
    clip_qty,
    execute_action,
    live_authorized,
    load_rules,
    place_gtc_bracket,
    plan_actions,
    run_cycle,
)


def example_rules() -> dict:
    rules, _ = load_rules(REPO)
    return deepcopy(rules)


def base_book(**kw) -> dict:
    book = {
        "equity": 596.86,
        "peak_equity": 596.86,
        "sod_equity": 596.86,
        "day_pnl": 0.0,
        "armed": True,
        "in_rth": True,
        "positions": [
            {"symbol": "NVO", "qty": 1},
            {"symbol": "NOK", "qty": 1},
        ],
        "orders": [],
        "quotes": {"ETHA": {"last": 18.50}, "IBIT": {"last": 45.00}},
        "source": "test",
    }
    book.update(kw)
    return book


class TestThroughCap(unittest.TestCase):
    def test_through_cap_abandons_no_reprice_up(self):
        rules = example_rules()
        book = base_book(
            quotes={"ETHA": {"last": 18.92}},
            orders=[
                {
                    "id": "1007750322357",
                    "symbol": "ETHA",
                    "side": "BUY",
                    "status": "WORKING",
                    "type": "LIMIT",
                    "price": 18.75,
                    "duration": "DAY",
                    "qty": 1,
                    "filledQty": 0,
                    "remaining": 1,
                }
            ],
        )
        actions = plan_actions(rules, book)
        abandons = [
            a
            for a in actions
            if a["symbol"] == "ETHA" and a["op"] == "cancel_abandon"
        ]
        self.assertTrue(abandons, actions)
        self.assertTrue(
            any(a["reason"] == "through_cap_idea_dead" for a in abandons),
            abandons,
        )
        for a in actions:
            self.assertNotEqual(a["op"], "replace")
            self.assertNotEqual(a["op"], "reprice_up")
            px = (a.get("params") or {}).get("limit") or (a.get("params") or {}).get(
                "price"
            )
            if a["op"] == "place_gtc_bracket" and a["symbol"] == "ETHA":
                self.fail(f"must not place after through-cap: {a}")
            if px is not None and a["symbol"] == "ETHA":
                self.assertLessEqual(float(px), 18.90)
                self.assertLessEqual(float(px), 18.75)  # never raise working 18.75
        places = [
            a
            for a in actions
            if a["op"] == "place_gtc_bracket" and a["symbol"] == "ETHA"
        ]
        self.assertEqual(places, [])


class TestProtectOnly(unittest.TestCase):
    def test_nvo_protect_only_no_add(self):
        rules = example_rules()
        # even if someone enables an NVO entry, leftovers stay protect-only
        rules.setdefault("entries", {})["NVO"] = {
            "enabled": True,
            "qty": 2,
            "limit": 44.0,
            "stop": 42.5,
            "cap": 45.0,
        }
        book = base_book(orders=[], quotes={"NVO": {"last": 45.81}})
        actions = plan_actions(rules, book)
        nvo = [a for a in actions if a.get("symbol") == "NVO"]
        self.assertTrue(
            any(a["op"] == "place_protect_stop" for a in nvo),
            nvo,
        )
        self.assertFalse(
            any(a["op"] == "place_gtc_bracket" for a in nvo),
            nvo,
        )
        for a in nvo:
            self.assertNotEqual((a.get("params") or {}).get("side"), "BUY")
        # NOK already-working stop → skip, never buy
        book2 = base_book(
            orders=[
                {
                    "id": "1007691287449",
                    "symbol": "NOK",
                    "side": "SELL",
                    "status": "WORKING",
                    "type": "STOP",
                    "stopPrice": 9.45,
                    "duration": "GOOD_TILL_CANCEL",
                    "qty": 1,
                    "remaining": 1,
                }
            ]
        )
        actions2 = plan_actions(rules, book2)
        nok = [a for a in actions2 if a.get("symbol") == "NOK"]
        self.assertTrue(any(a["op"] == "skip" for a in nok), nok)
        self.assertFalse(any(a["op"] == "place_gtc_bracket" for a in nok))


class TestQtyClip(unittest.TestCase):
    def test_clip_qty_math(self):
        # 2.5% of 596.86 ≈ 14.9215; $1.00 stop → max 14
        self.assertEqual(clip_qty(20, 18.70, 17.70, 596.86, 0.025), 14)
        self.assertEqual(clip_qty(5, 18.70, 17.70, 596.86, 0.025), 5)
        self.assertEqual(clip_qty(5, 18.70, 17.70, None, 0.025), 0)

    def test_plan_clips_requested_qty(self):
        rules = example_rules()
        rules["entries"]["ETHA"]["qty"] = 20
        book = base_book(quotes={"ETHA": {"last": 18.50}})
        actions = plan_actions(rules, book)
        places = [
            a
            for a in actions
            if a["op"] == "place_gtc_bracket" and a["symbol"] == "ETHA"
        ]
        self.assertEqual(len(places), 1, actions)
        self.assertEqual(places[0]["params"]["qty"], 14)
        self.assertLessEqual(places[0]["params"]["risk_dollars"], 596.86 * 0.025)


class TestDryRunNeverSent(unittest.TestCase):
    def test_plan_never_marks_sent(self):
        rules = example_rules()
        book = base_book()
        for a in plan_actions(rules, book):
            self.assertIs(a.get("sent"), False)
            self.assertTrue(a.get("dry_run"))

    def test_execute_dry_run_never_sent(self):
        rules = example_rules()
        book = base_book()
        planned = plan_actions(rules, book)
        for a in planned:
            out = execute_action(a, live=False)
            self.assertIs(out["sent"], False)
            self.assertEqual(out.get("execute"), "dry_run")

    def test_run_cycle_dry_run_never_sent(self):
        rules = example_rules()
        book = base_book()
        out = run_cycle(rules, book, live=False, broker_note="test")
        for a in out:
            self.assertIs(a.get("sent"), False)

    def test_live_execute_posts_via_injected_fn(self):
        from temple_flow_wire import place_gtc_bracket as real

        captured = {}
        def fake_post(payload):
            captured["payload"] = payload
            return {"http": 201, "order_id": "1", "error": ""}

        res = place_gtc_bracket(symbol="ETHA", qty=5, limit=18.7, stop=17.7, post=fake_post)
        self.assertEqual(res["http"], 201)
        self.assertEqual(captured["payload"]["orderStrategyType"], "TRIGGER")
        self.assertEqual(captured["payload"]["duration"], "GOOD_TILL_CANCEL")

    def test_live_gates_closed_in_repo(self):
        ok, why = live_authorized(REPO)
        self.assertFalse(ok)
        self.assertIn("LIVE_REFUSED", why)
        self.assertFalse((REPO / "config" / "LIVE_OK").exists())

    def test_ibit_disabled_without_hold(self):
        rules = example_rules()
        book = base_book()
        actions = plan_actions(rules, book)
        ibit = [a for a in actions if a.get("symbol") == "IBIT"]
        self.assertTrue(ibit)
        self.assertFalse(any(a["op"] == "place_gtc_bracket" for a in ibit))


class TestExampleFile(unittest.TestCase):
    def test_example_schema(self):
        path = REPO / "config" / "standing_rules.example.json"
        rules = json.loads(path.read_text())
        self.assertTrue(rules["arm_required"])
        self.assertEqual(rules["universe"], ["ETHA", "IBIT"])
        self.assertEqual(rules["protect"]["NVO"]["stop"], 42.5)
        self.assertEqual(rules["protect"]["NOK"]["stop"], 9.45)
        self.assertTrue(rules["protect"]["NOK"]["already_working"])
        self.assertEqual(rules["entries"]["ETHA"]["qty"], 5)
        self.assertEqual(rules["entries"]["ETHA"]["limit"], 18.7)
        self.assertEqual(rules["entries"]["ETHA"]["stop"], 17.7)
        self.assertEqual(rules["entries"]["ETHA"]["cap"], 18.9)
        self.assertIsNone(rules["entries"]["IBIT"]["hold_reclaim"])
        self.assertFalse(rules["entries"]["IBIT"]["enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
