#!/usr/bin/env python3
"""Unit tests for temple_flow_wire — no network, no live repo state.

Two standing rules for this file, both earned:
  1. Nothing here reads config/standing_rules.json or config/LIVE_OK. The
     Studio's live copy of this repo HAS LIVE_OK and an edited rules file; a
     test that reads them passes here and lies there.
  2. Every test that runs live=True monkeypatches place_gtc_bracket /
     cancel_by_id / schwab_post_order. No code path may reach requests.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

import temple_flow_wire  # noqa: E402
from temple_flow_wire import (  # noqa: E402
    clip_qty,
    duplicate_working_order,
    execute_action,
    execute_outbox_ticket,
    gate_outbox_ticket,
    live_authorized,
    load_outbox_tickets,
    move_ticket,
    place_gtc_bracket,
    plan_actions,
    run_cycle,
    ticket_notional_cap,
    working_order_by_id,
)

EXAMPLE_RULES_PATH = REPO / "config" / "standing_rules.example.json"


def example_rules() -> dict:
    """Always the EXAMPLE file, explicitly.

    load_rules() prefers config/standing_rules.json when it exists, which on the
    Studio is Anthony's live edited file. Tests must not depend on it.
    """
    return deepcopy(json.loads(EXAMPLE_RULES_PATH.read_text()))


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


def ticket(**kw) -> dict:
    t = {
        "id": "TF-TEST-01",
        "status": "approved",
        "risk_stamped": True,
        "action": "place_gtc_bracket",
        "symbol": "ETHA",
        "qty": 11,
        "limit": 18.70,
        "stop": 17.70,
        "side": "BUY",
        "stop_side": "SELL",
    }
    t.update(kw)
    return t


@contextlib.contextmanager
def patched(name: str, fn):
    """Swap a module-level helper. Restores even on failure."""
    original = getattr(temple_flow_wire, name)
    setattr(temple_flow_wire, name, fn)
    try:
        yield
    finally:
        setattr(temple_flow_wire, name, original)


@contextlib.contextmanager
def no_network():
    """Hard tripwire: any unmocked broker call fails the test loudly."""

    def boom(*a, **k):
        raise AssertionError("test reached a broker helper")

    with patched("schwab_post_order", boom), patched("cancel_by_id", boom):
        yield


@contextlib.contextmanager
def recording_broker():
    """Capture every would-be broker call instead of making one.

    run_cycle(live=True) legitimately reaches the protect lane (base_book holds
    a naked NVO share), so tests that drive a whole live cycle need a recorder
    rather than a tripwire — and then assert on what was NOT posted.
    """
    calls: dict[str, list] = {"post": [], "cancel": []}

    def rec_post(payload):
        calls["post"].append(payload)
        return {"http": 201, "order_id": "MOCK-1", "error": ""}

    def rec_cancel(order_id):
        calls["cancel"].append(order_id)
        return {"http": 200, "error": ""}

    with patched("schwab_post_order", rec_post), patched("cancel_by_id", rec_cancel):
        yield calls


def posted_symbols(calls: dict) -> list[str]:
    out = []
    for p in calls["post"]:
        for leg in p.get("orderLegCollection") or []:
            out.append((leg.get("instrument") or {}).get("symbol"))
    return out


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
            a for a in actions if a["symbol"] == "ETHA" and a["op"] == "cancel_abandon"
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
        self.assertTrue(any(a["op"] == "place_protect_stop" for a in nvo), nvo)
        self.assertFalse(any(a["op"] == "place_gtc_bracket" for a in nvo), nvo)
        for a in nvo:
            self.assertNotEqual((a.get("params") or {}).get("side"), "BUY")
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
        rules["entries"]["ETHA"]["enabled"] = True
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
            self.assertIs(a.get("mutated"), False)
            self.assertTrue(a.get("dry_run"))

    def test_execute_dry_run_never_sent(self):
        rules = example_rules()
        book = base_book()
        for a in plan_actions(rules, book):
            out = execute_action(a, live=False)
            self.assertIs(out["sent"], False)
            self.assertIs(out["mutated"], False)
            self.assertEqual(out.get("execute"), "dry_run")

    def test_run_cycle_dry_run_never_sent(self):
        rules = example_rules()
        book = base_book()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = run_cycle(
                rules,
                book,
                live=False,
                broker_note="test",
                repo_root=Path(tmpdir),
            )
        for a in out:
            self.assertIs(a.get("sent"), False)
            self.assertFalse(a.get("mutated"))

    def test_live_execute_posts_via_injected_fn(self):
        captured = {}

        def fake_post(payload):
            captured["payload"] = payload
            return {"http": 201, "order_id": "1", "error": ""}

        res = place_gtc_bracket(
            symbol="ETHA", qty=5, limit=18.7, stop=17.7, post=fake_post
        )
        self.assertEqual(res["http"], 201)
        self.assertEqual(captured["payload"]["orderStrategyType"], "TRIGGER")
        self.assertEqual(captured["payload"]["duration"], "GOOD_TILL_CANCEL")

    def test_live_gates_closed_without_live_ok(self):
        """Gate logic, tested against a tmp root.

        The old version asserted on THIS repo, so it passed in a clean checkout
        and would fail on the Studio, where config/LIVE_OK exists on purpose.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "config").mkdir()
            ok, why = live_authorized(root)
            self.assertFalse(ok)
            self.assertIn("LIVE_REFUSED", why)
            # and with the env var set, the file is the thing still missing
            with mock.patch.dict(os.environ, {"TEMPLE_FLOW_LIVE": "1"}):
                ok2, why2 = live_authorized(root)
                self.assertFalse(ok2)
                self.assertIn("LIVE_OK missing", why2)
                # both legs present → open. Proves the gate can also SAY YES,
                # so a green test is not just a gate that never opens.
                (root / "config" / "LIVE_OK").touch()
                ok3, _ = live_authorized(root)
                self.assertTrue(ok3)

    def test_ibit_disabled_without_hold(self):
        rules = example_rules()
        book = base_book()
        actions = plan_actions(rules, book)
        ibit = [a for a in actions if a.get("symbol") == "IBIT"]
        self.assertTrue(ibit)
        self.assertFalse(any(a["op"] == "place_gtc_bracket" for a in ibit))


class TestExampleFile(unittest.TestCase):
    def test_example_schema(self):
        rules = json.loads(EXAMPLE_RULES_PATH.read_text())
        self.assertTrue(rules["arm_required"])
        self.assertEqual(rules["universe"], ["ETHA", "IBIT"])
        self.assertEqual(rules["protect"]["NVO"]["stop"], 42.5)
        self.assertEqual(rules["protect"]["NOK"]["stop"], 9.45)
        self.assertTrue(rules["protect"]["NOK"]["already_working"])
        self.assertEqual(rules["entries"]["ETHA"]["qty"], 5)
        self.assertEqual(rules["entries"]["ETHA"]["limit"], 18.7)
        self.assertEqual(rules["entries"]["ETHA"]["stop"], 17.7)
        self.assertEqual(rules["entries"]["ETHA"]["cap"], 18.9)
        self.assertFalse(rules["entries"]["ETHA"]["enabled"])
        self.assertIsNone(rules["entries"]["IBIT"]["hold_reclaim"])
        self.assertFalse(rules["entries"]["IBIT"]["enabled"])
        # outbox notional ceiling must be declared, not implied
        self.assertEqual(rules["risk"]["max_ticket_notional_pct"], 0.35)


class TestCancelById(unittest.TestCase):
    def test_execute_cancel_abandon_live(self):
        captured = {}

        def mock_cancel(order_id):
            captured["order_id"] = order_id
            return {"http": 200, "error": ""}

        with tempfile.TemporaryDirectory() as tmpdir, patched("cancel_by_id", mock_cancel):
            action = {
                "op": "cancel_abandon",
                "symbol": "ETHA",
                "reason": "through_cap_idea_dead",
                "params": {"order_id": "1007750322357"},
            }
            result = execute_action(
                action, live=True, rth=True, repo_root=Path(tmpdir)
            )
        self.assertEqual(captured["order_id"], "1007750322357")
        self.assertEqual(result["execute"], "canceled")
        # honest semantics: a cancel mutates, it does not "send" an order
        self.assertIs(result["sent"], False)
        self.assertIs(result["mutated"], True)

    def test_execute_cancel_400_after_hours(self):
        with tempfile.TemporaryDirectory() as tmpdir, patched(
            "cancel_by_id",
            lambda oid: {"http": 400, "error": "PENDING_ACTIVATION after hours"},
        ):
            action = {
                "op": "cancel_abandon",
                "symbol": "ETHA",
                "params": {"order_id": "1007750322357"},
            }
            result = execute_action(
                action, live=True, rth=True, repo_root=Path(tmpdir)
            )
            self.assertIs(result["sent"], False)
            self.assertIs(result["mutated"], False)
            self.assertEqual(result["execute"], "cancel_refused_400_after_hours")


class TestCancelGuards(unittest.TestCase):
    """Task 4. Each of these lets the PR fire a DELETE it should not."""

    def test_cancel_plan_skips_symbol_outside_live_universe(self):
        rules = example_rules()
        book = base_book(
            orders=[
                {
                    "id": "999",
                    "symbol": "SOFI",
                    "side": "BUY",
                    "status": "WORKING",
                    "type": "LIMIT",
                    "price": 8.50,
                    "duration": "DAY",  # no_day would cancel it
                    "qty": 10,
                    "remaining": 10,
                }
            ]
        )
        actions = plan_actions(rules, book)
        sofi = [a for a in actions if a.get("symbol") == "SOFI"]
        self.assertTrue(sofi)
        self.assertFalse(
            any(a["op"] == "cancel_abandon" for a in sofi),
            f"daemon must not cancel a human's non-universe order: {sofi}",
        )
        self.assertTrue(
            any(a["reason"] == "cancel_lane_not_in_live_universe" for a in sofi), sofi
        )

    def test_cancel_deferred_outside_rth_never_posts(self):
        """Outside RTH the DELETE is planned but not fired (400 churn)."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            action = {
                "op": "cancel_abandon",
                "symbol": "ETHA",
                "params": {"order_id": "1007750322357"},
            }
            result = execute_action(
                action, live=True, rth=False, repo_root=Path(tmpdir)
            )
        self.assertEqual(result["execute"], "cancel_deferred_outside_rth")
        self.assertIs(result["sent"], False)
        self.assertIs(result["mutated"], False)

    def test_400_persists_and_is_not_retried_same_day(self):
        calls = []

        def mock_cancel(order_id):
            calls.append(order_id)
            return {"http": 400, "error": "PENDING_ACTIVATION"}

        action = {
            "op": "cancel_abandon",
            "symbol": "ETHA",
            "params": {"order_id": "1007750322357"},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "config").mkdir()
            with patched("cancel_by_id", mock_cancel):
                first = execute_action(action, live=True, rth=True, repo_root=root)
                second = execute_action(action, live=True, rth=True, repo_root=root)
            self.assertEqual(first["execute"], "cancel_refused_400_after_hours")
            self.assertEqual(second["execute"], "cancel_skipped_refused_today")
            self.assertEqual(len(calls), 1, "400 must not be retried every tick")
            state = json.loads((root / "config" / "cancel_refusals.json").read_text())
            self.assertIn("1007750322357", state)

    def test_400_retried_on_a_later_day(self):
        calls = []

        def mock_cancel(order_id):
            calls.append(order_id)
            return {"http": 400, "error": "PENDING_ACTIVATION"}

        action = {
            "op": "cancel_abandon",
            "symbol": "ETHA",
            "params": {"order_id": "1007750322357"},
        }
        day1 = datetime(2026, 9, 2, 10, 0)
        day2 = datetime(2026, 9, 3, 10, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "config").mkdir()
            with patched("cancel_by_id", mock_cancel):
                execute_action(action, live=True, rth=True, repo_root=root, now=day1)
                execute_action(action, live=True, rth=True, repo_root=root, now=day2)
        self.assertEqual(len(calls), 2, "a new trading day gets one more attempt")


class TestOneSellLaw(unittest.TestCase):
    def test_refuse_protect_if_sell_exists(self):
        rules = example_rules()
        book = base_book(
            orders=[
                {
                    "id": "1007691287449",
                    "symbol": "NVO",
                    "side": "SELL",
                    "status": "WORKING",
                    "type": "LIMIT",
                    "price": 45.00,
                    "duration": "GTC",
                    "qty": 1,
                    "remaining": 1,
                }
            ]
        )
        actions = plan_actions(rules, book)
        nvo = [a for a in actions if a.get("symbol") == "NVO"]
        self.assertTrue(
            any(a["reason"] == "one_sell_law_existing_sell" for a in nvo), nvo
        )
        self.assertFalse(any(a["op"] == "place_protect_stop" for a in nvo), nvo)

    def test_refuse_protect_if_stop_exists(self):
        rules = example_rules()
        book = base_book(
            orders=[
                {
                    "id": "1007691287449",
                    "symbol": "NVO",
                    "side": "SELL",
                    "status": "WORKING",
                    "type": "STOP",
                    "stopPrice": 42.5,
                    "duration": "GTC",
                    "qty": 1,
                    "remaining": 1,
                }
            ]
        )
        actions = plan_actions(rules, book)
        nvo = [a for a in actions if a.get("symbol") == "NVO"]
        self.assertTrue(any(a["reason"] == "protect_already_working" for a in nvo), nvo)
        self.assertFalse(any(a["op"] == "place_protect_stop" for a in nvo), nvo)

    def test_bracket_path_refuses_when_a_sell_is_working(self):
        """The bracket carries a child STOP SELL. Schwab rejects the second SELL.

        The PR enforced the one-sell law only in the PROTECT_ONLY loop.
        """
        rules = example_rules()
        rules["entries"]["ETHA"]["enabled"] = True
        book = base_book(
            orders=[
                {
                    "id": "555",
                    "symbol": "ETHA",
                    "side": "SELL",
                    "status": "PENDING_ACTIVATION",
                    "type": "STOP",
                    "stopPrice": 17.70,
                    "duration": "GOOD_TILL_CANCEL",
                    "qty": 5,
                    "remaining": 5,
                }
            ]
        )
        actions = plan_actions(rules, book)
        etha = [a for a in actions if a.get("symbol") == "ETHA"]
        self.assertFalse(
            any(a["op"] == "place_gtc_bracket" for a in etha),
            f"second SELL would be rejected by Schwab: {etha}",
        )
        self.assertTrue(
            any(a["reason"] == "one_sell_law_existing_sell" for a in etha), etha
        )


class TestOutboxLoader(unittest.TestCase):
    def test_loads_only_approved_and_risk_stamped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True)
            (outbox / "a.json").write_text(json.dumps(ticket(id="TF-A")))
            (outbox / "b.json").write_text(
                json.dumps(ticket(id="TF-B", status="draft"))
            )
            (outbox / "c.json").write_text(
                json.dumps(ticket(id="TF-C", risk_stamped=False))
            )
            loaded = load_outbox_tickets(root)
            self.assertEqual([t["ticket"]["id"] for t in loaded], ["TF-A"])

    def test_unreadable_ticket_is_surfaced_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True)
            (outbox / "bad.json").write_text("{not json")
            loaded = load_outbox_tickets(root)
            self.assertEqual(len(loaded), 1)
            self.assertTrue(loaded[0]["load_error"])
            out = execute_outbox_ticket(
                loaded[0], live=False, rules=example_rules(), book=base_book()
            )
            self.assertEqual(out["reason"], "ticket_unreadable")

    def test_move_ticket_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True)
            src = outbox / "a.json"
            src.write_text("{}")
            # a FILE where the done/ dir must be → mkdir raises
            (outbox / "done").write_text("blocker")
            self.assertFalse(move_ticket(src, "done", root))
            self.assertTrue(src.exists())


class TestOutboxGates(unittest.TestCase):
    """Task 1. On the PR, every one of these POSTs to Schwab."""

    def _gate(self, t, book=None, rules=None):
        return gate_outbox_ticket(t, rules or example_rules(), book or base_book())

    def test_refuses_symbol_outside_live_universe(self):
        # the PR's own AWAY_MODE example ticket was SOFI
        reason, _ = self._gate(ticket(symbol="SOFI", limit=8.50, stop=8.20, qty=10))
        self.assertEqual(reason, "not_in_live_universe")

    def test_refuses_protect_only_symbol(self):
        reason, _ = self._gate(ticket(symbol="NVO", limit=44.0, stop=42.5, qty=1))
        self.assertEqual(reason, "not_in_live_universe")

    def test_refuses_when_not_armed(self):
        reason, _ = self._gate(ticket(), book=base_book(armed=False))
        self.assertEqual(reason, "arm_required")

    def test_refuses_outside_rth(self):
        reason, _ = self._gate(ticket(), book=base_book(in_rth=False))
        self.assertEqual(reason, "outside_rth")

    def test_refuses_when_risk_box_trips(self):
        book = base_book(equity=500.0, sod_equity=596.86, day_pnl=-96.86)
        reason, detail = self._gate(ticket(), book=book)
        self.assertEqual(reason, "new_risk_blocked")
        self.assertTrue(detail["risk_box"])

    def test_refuses_qty_above_risk_clip(self):
        # 2.5% of 596.86 = $14.92; $1.00 risk/share → 14 max
        reason, detail = self._gate(ticket(qty=20))
        self.assertEqual(reason, "ticket_qty_exceeds_risk_clip")
        self.assertEqual(detail["clipped_qty"], 14)

    def test_refuses_over_notional_cap_even_inside_risk_clip(self):
        # qty 14 passes the 2.5% RISK clip but 14 * 18.70 = $261.80 notional,
        # over 35% of $596.86 = $208.90. Two different caps; both must bind.
        reason, detail = self._gate(ticket(qty=14))
        self.assertEqual(reason, "ticket_notional_over_cap")
        self.assertAlmostEqual(detail["notional"], 261.80, places=2)
        self.assertAlmostEqual(detail["max_ticket_notional"], 208.901, places=2)

    def test_notional_cap_helper_prefers_the_tighter_of_two(self):
        rules = example_rules()
        rules["risk"]["max_ticket_notional"] = 100.0
        self.assertAlmostEqual(ticket_notional_cap(rules, 596.86), 100.0)
        self.assertIsNone(ticket_notional_cap({"risk": {}}, None))

    def test_refuses_when_equity_unknown(self):
        reason, _ = self._gate(ticket(), book=base_book(equity=None, sod_equity=None))
        self.assertIn(reason, ("equity_unknown_cannot_size", "qty_clipped_to_zero"))

    def test_refuses_existing_entry_in_book(self):
        book = base_book(
            orders=[
                {
                    "id": "777",
                    "symbol": "ETHA",
                    "side": "BUY",
                    "status": "WORKING",
                    "type": "LIMIT",
                    "price": 18.60,
                    "duration": "GOOD_TILL_CANCEL",
                    "qty": 3,
                    "remaining": 3,
                }
            ]
        )
        reason, _ = self._gate(ticket(), book=book)
        self.assertEqual(reason, "existing_entry_in_book")

    def test_refuses_existing_sell_one_sell_law(self):
        book = base_book(
            orders=[
                {
                    "id": "778",
                    "symbol": "ETHA",
                    "side": "SELL",
                    "status": "PENDING_ACTIVATION",
                    "type": "STOP",
                    "stopPrice": 17.70,
                    "duration": "GOOD_TILL_CANCEL",
                    "qty": 5,
                    "remaining": 5,
                }
            ]
        )
        reason, _ = self._gate(ticket(), book=book)
        self.assertEqual(reason, "one_sell_law_existing_sell")

    def test_refuses_duplicate_working_order(self):
        # a BUY STOP is not an "entry" per order_is_buy_entry, so this slips
        # past existing_entry and must be caught by the dedup check
        book = base_book(
            orders=[
                {
                    "id": "779",
                    "symbol": "ETHA",
                    "side": "BUY",
                    "status": "WORKING",
                    "type": "STOP",
                    "stopPrice": 19.0,
                    "price": 18.70,
                    "duration": "GOOD_TILL_CANCEL",
                    "qty": 11,
                    "remaining": 11,
                }
            ]
        )
        reason, _ = self._gate(ticket(), book=book)
        self.assertEqual(reason, "duplicate_working_order")
        self.assertIsNotNone(
            duplicate_working_order(book, "ETHA", "BUY", 11, 18.699999)
        )

    def test_schema_rejects_null_prices_without_raising(self):
        for bad in (
            ticket(limit=None),
            ticket(stop=None),
            ticket(qty=None),
            ticket(qty="5"),
            ticket(qty=0),
            ticket(qty=True),
            ticket(symbol=None),
            ticket(id=None),
            ticket(limit="18.70"),
            ticket(side="SELL"),
            ticket(stop_side="BUY"),
            ticket(stop=19.0),  # stop above limit on a BUY
            ticket(action="wire_me_money"),
        ):
            reason, detail = self._gate(bad)
            self.assertEqual(reason, "ticket_schema_invalid", bad)
            self.assertTrue(detail["schema_errors"])

    def test_happy_path_clears_every_gate(self):
        reason, detail = self._gate(ticket(qty=11))
        self.assertIsNone(reason, detail)
        self.assertAlmostEqual(detail["notional"], 205.70, places=2)

    def test_cancel_ticket_requires_working_order_in_book(self):
        t = ticket(action="cancel_by_id", order_id="404404")
        reason, _ = self._gate(t)
        self.assertEqual(reason, "cancel_order_id_not_working_in_book")

    def test_cancel_ticket_symbol_must_be_in_live_universe(self):
        book = base_book(
            orders=[
                {
                    "id": 1007691287449,
                    "symbol": "NOK",
                    "side": "SELL",
                    "status": "WORKING",
                    "type": "STOP",
                    "stopPrice": 9.45,
                    "qty": 1,
                    "remaining": 1,
                }
            ]
        )
        t = ticket(action="cancel_by_id", order_id="1007691287449")
        reason, _ = self._gate(t, book=book)
        self.assertEqual(reason, "cancel_symbol_not_in_live_universe")
        # int id in the book, str id in the ticket — must still match
        self.assertIsNotNone(working_order_by_id(book, "1007691287449"))

    def test_cancel_ticket_ok_for_universe_symbol(self):
        book = base_book(
            orders=[
                {
                    "id": 12345,
                    "symbol": "ETHA",
                    "side": "BUY",
                    "status": "WORKING",
                    "type": "LIMIT",
                    "price": 18.75,
                    "qty": 1,
                    "remaining": 1,
                }
            ]
        )
        reason, _ = self._gate(
            ticket(action="cancel_by_id", order_id=12345), book=book
        )
        self.assertIsNone(reason)


class TestOutboxExecution(unittest.TestCase):
    def test_dry_run_never_posts_and_still_reports_the_gate(self):
        with no_network():
            out = execute_outbox_ticket(
                {"ticket": ticket(symbol="SOFI", limit=8.5, stop=8.2, qty=10)},
                live=False,
                rules=example_rules(),
                book=base_book(),
            )
        self.assertIs(out["sent"], False)
        self.assertEqual(out["execute"], "refused")
        self.assertEqual(out["reason"], "not_in_live_universe")

    def test_refused_ticket_never_reaches_the_broker(self):
        with no_network():
            out = execute_outbox_ticket(
                {"ticket": ticket(symbol="SOFI", limit=8.5, stop=8.2, qty=10)},
                live=True,
                rules=example_rules(),
                book=base_book(),
            )
        self.assertIs(out["sent"], False)
        self.assertEqual(out["reason"], "not_in_live_universe")

    def test_skip_already_sent(self):
        with no_network():
            out = execute_outbox_ticket(
                {"ticket": ticket(schwab_order_id="1007762031724")},
                live=True,
                rules=example_rules(),
                book=base_book(),
            )
        self.assertEqual(out["execute"], "skip_already_sent")
        self.assertIs(out["sent"], False)

    def test_missing_rules_or_book_refuses(self):
        with no_network():
            self.assertEqual(
                execute_outbox_ticket(
                    {"ticket": ticket()}, live=True, rules={}, book=base_book()
                )["reason"],
                "rules_missing",
            )
            self.assertEqual(
                execute_outbox_ticket(
                    {"ticket": ticket()}, live=True, rules=example_rules(), book={}
                )["reason"],
                "book_missing",
            )

    def test_live_post_uses_gated_values(self):
        captured = {}

        def mock_place(**kw):
            captured.update(kw)
            return {"http": 201, "order_id": "1007762031724", "error": ""}

        with tempfile.TemporaryDirectory() as tmpdir, patched(
            "place_gtc_bracket", mock_place
        ):
            root = Path(tmpdir)
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True)
            p = outbox / "TF-TEST-01.json"
            p.write_text(json.dumps(ticket(qty=11)))
            out = execute_outbox_ticket(
                {"ticket": ticket(qty=11), "path": p},
                live=True,
                rules=example_rules(),
                book=base_book(),
                repo_root=root,
            )
            self.assertEqual(captured["symbol"], "ETHA")
            self.assertEqual(captured["qty"], 11)
            self.assertEqual(captured["side"], "BUY")
            self.assertEqual(out["execute"], "posted")
            self.assertIs(out["sent"], True)
            self.assertIs(out["mutated"], True)
            # task 3: the id is written back BEFORE any move
            self.assertTrue(out["stamped"])
            self.assertEqual(
                json.loads(p.read_text())["schwab_order_id"], "1007762031724"
            )


class TestOutboxIdempotencyAndExceptions(unittest.TestCase):
    def _repo_with_ticket(self, root: Path, t: dict) -> Path:
        outbox = root / "config" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        p = outbox / f"{t.get('id') or 'TF'}.json"
        p.write_text(json.dumps(t))
        return p

    def test_poison_ticket_does_not_stop_plan_actions(self):
        """Task 2. On the PR this TypeError escapes run_cycle entirely.

        A single malformed ticket then disables the protect lane on EVERY
        later cycle, because the ticket is never moved either.
        """

        def exploding_place(**kw):
            raise TypeError("float() argument must be a string or a real number")

        rules = example_rules()
        book = base_book()
        with tempfile.TemporaryDirectory() as tmpdir, recording_broker(), patched(
            "place_gtc_bracket", exploding_place
        ):
            root = Path(tmpdir)
            p = self._repo_with_ticket(root, ticket(qty=11))
            out = run_cycle(
                rules, book, live=True, broker_note="test", repo_root=root
            )
            ops = [a.get("op") for a in out]
            self.assertIn("place_protect_stop", ops, out)
            tickets = [a for a in out if a.get("op") == "outbox_ticket"]
            self.assertEqual(tickets[0]["execute"], "exception")
            self.assertEqual(tickets[0]["error"], "TypeError")
            self.assertFalse(p.exists())
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    def test_refused_ticket_is_quarantined_not_retried(self):
        rules = example_rules()
        book = base_book()
        with tempfile.TemporaryDirectory() as tmpdir, recording_broker() as calls:
            root = Path(tmpdir)
            p = self._repo_with_ticket(
                root, ticket(id="TF-SOFI", symbol="SOFI", limit=8.5, stop=8.2, qty=10)
            )
            run_cycle(rules, book, live=True, broker_note="test", repo_root=root)
            self.assertNotIn("SOFI", posted_symbols(calls))
            self.assertFalse(p.exists())
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())
            # second cycle finds nothing to do
            out2 = run_cycle(
                rules, book, live=True, broker_note="test", repo_root=root
            )
            self.assertEqual([a for a in out2 if a.get("op") == "outbox_ticket"], [])
            self.assertNotIn("SOFI", posted_symbols(calls))

    def test_posted_ticket_moves_to_done_carrying_the_order_id(self):
        def mock_place(**kw):
            return {"http": 201, "order_id": "1007762031724", "error": ""}

        with tempfile.TemporaryDirectory() as tmpdir, recording_broker(), patched(
            "place_gtc_bracket", mock_place
        ):
            root = Path(tmpdir)
            p = self._repo_with_ticket(root, ticket(qty=11))
            run_cycle(
                example_rules(),
                base_book(),
                live=True,
                broker_note="test",
                repo_root=root,
            )
            done = root / "config" / "outbox" / "done" / p.name
            self.assertTrue(done.exists())
            self.assertEqual(
                json.loads(done.read_text())["schwab_order_id"], "1007762031724"
            )

    def test_stamp_survives_a_failed_move_and_blocks_a_second_post(self):
        """Task 3. The PR never stamps, so a failed move re-POSTs forever."""
        calls = []

        def mock_place(**kw):
            calls.append(kw)
            return {"http": 201, "order_id": "1007762031724", "error": ""}

        with tempfile.TemporaryDirectory() as tmpdir, recording_broker(), patched(
            "place_gtc_bracket", mock_place
        ):
            root = Path(tmpdir)
            p = self._repo_with_ticket(root, ticket(qty=11))
            # block done/ so the move fails after a successful POST
            (root / "config" / "outbox" / "done").write_text("blocker")
            run_cycle(
                example_rules(),
                base_book(),
                live=True,
                broker_note="test",
                repo_root=root,
            )
            self.assertTrue(p.exists(), "move failed, ticket stays put")
            self.assertEqual(
                json.loads(p.read_text())["schwab_order_id"], "1007762031724"
            )
            out2 = run_cycle(
                example_rules(),
                base_book(),
                live=True,
                broker_note="test",
                repo_root=root,
            )
            self.assertEqual(len(calls), 1, "must not double-send after a failed move")
            t2 = [a for a in out2 if a.get("op") == "outbox_ticket"][0]
            self.assertEqual(t2["execute"], "skip_already_sent")

    def test_two_tickets_same_symbol_in_one_cycle_post_once(self):
        """The book is fetched ONCE per cycle. Without in-cycle bookkeeping the
        duplicate guard cannot see an order this same cycle just placed."""
        with tempfile.TemporaryDirectory() as tmpdir, recording_broker() as calls:
            root = Path(tmpdir)
            self._repo_with_ticket(root, ticket(id="TF-A", qty=5))
            self._repo_with_ticket(root, ticket(id="TF-B", qty=5))
            out = run_cycle(
                example_rules(),
                base_book(),
                live=True,
                broker_note="test",
                repo_root=root,
            )
        brackets = [p for p in calls["post"] if p.get("orderStrategyType") == "TRIGGER"]
        self.assertEqual(len(brackets), 1, "two tickets, one symbol, one order")
        results = [a for a in out if a.get("op") == "outbox_ticket"]
        self.assertEqual(results[0]["execute"], "posted")
        self.assertEqual(results[1]["execute"], "refused")
        self.assertIn(
            results[1]["reason"],
            ("existing_entry_in_book", "duplicate_working_order",
             "one_sell_law_existing_sell"),
            results[1],
        )

    def test_in_cycle_order_is_not_immediately_abandoned(self):
        """The injected order must carry GOOD_TILL_CANCEL, or plan_actions'
        no_day branch cancels the bracket the outbox just placed."""
        with tempfile.TemporaryDirectory() as tmpdir, recording_broker() as calls:
            root = Path(tmpdir)
            self._repo_with_ticket(root, ticket(id="TF-A", qty=5))
            out = run_cycle(
                example_rules(),
                base_book(),
                live=True,
                broker_note="test",
                repo_root=root,
            )
        etha = [a for a in out if a.get("symbol") == "ETHA" and a.get("op") != "skip"]
        self.assertTrue(any(a["op"] == "leave" for a in etha), etha)
        self.assertFalse(any(a["op"] == "cancel_abandon" for a in etha), etha)
        self.assertEqual(calls["cancel"], [])

    def test_unreadable_ticket_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmpdir, recording_broker():
            root = Path(tmpdir)
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True)
            p = outbox / "bad.json"
            p.write_text("{not json")
            run_cycle(
                example_rules(),
                base_book(),
                live=True,
                broker_note="test",
                repo_root=root,
            )
            self.assertTrue((outbox / "failed" / "bad.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
