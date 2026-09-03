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

import ast
import contextlib
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
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
    """A book that stands in for a COMPLETE, PROVEN Schwab read.

    source and the *_ok flags are part of the fixture on purpose. Both are
    fail-closed in the wire: only source == "schwab_read" may drive a live
    POST/DELETE, and a book-derived gate refuses unless the leg it depends on
    is proven. A fixture that omitted them would test the refusal path
    everywhere and never the permit path. Pass orders_ok=False / quotes_ok=False
    / source="fallback_hint" to exercise a degraded read.
    """
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
        "quotes": {
            "ETHA": {"last": 18.50},
            "IBIT": {"last": 45.00},
            "NVO": {"last": 45.81},
            "NOK": {"last": 10.20},
        },
        "orders_ok": True,
        "quotes_ok": True,
        "source": "schwab_read",
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
                action, live=True, rth=True, repo_root=Path(tmpdir), book=base_book()
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
                action, live=True, rth=True, repo_root=Path(tmpdir), book=base_book()
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
                action, live=True, rth=False, repo_root=Path(tmpdir), book=base_book()
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
                first = execute_action(
                    action, live=True, rth=True, repo_root=root, book=base_book()
                )
                second = execute_action(
                    action, live=True, rth=True, repo_root=root, book=base_book()
                )
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
                execute_action(
                    action,
                    live=True,
                    rth=True,
                    repo_root=root,
                    now=day1,
                    book=base_book(),
                )
                execute_action(
                    action,
                    live=True,
                    rth=True,
                    repo_root=root,
                    now=day2,
                    book=base_book(),
                )
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
        # equity is held at the fixture value ON PURPOSE. The risk box is a
        # WAIT gate and now runs AFTER the terminal caps, so a fixture that
        # also broke the notional cap (the old equity=500 one did: 11 * 18.70 =
        # $205.70 against 35% of $500 = $175) would report the cap and never
        # reach the box. Day breaker only: -103.14 on a $700 open is past 4.5%.
        book = base_book(equity=596.86, sod_equity=700.0, day_pnl=-103.14)
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
        """The two dispose differently, and that split is the point.

        No rules means the daemon cannot know what it is allowed to do — that
        never gets better by waiting, so it is TERMINAL. No book means the read
        failed — that is transient, so it WAITS.
        """
        with no_network():
            no_rules = execute_outbox_ticket(
                {"ticket": ticket()}, live=True, rules={}, book=base_book()
            )
            no_book = execute_outbox_ticket(
                {"ticket": ticket()}, live=True, rules=example_rules(), book={}
            )
        self.assertEqual(no_rules["reason"], "rules_missing")
        self.assertEqual(no_rules["execute"], "refused")
        self.assertEqual(no_book["reason"], "book_missing")
        self.assertEqual(no_book["execute"], "deferred")
        for out in (no_rules, no_book):
            self.assertIs(out["sent"], False)
            self.assertIs(out["mutated"], False)

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


def studio_shaped_rules() -> dict:
    """The EXAMPLE file bent into the shape of the Studio's live rules.

    Standing rule 1 forbids reading config/standing_rules.json, so the two live
    facts that made B2 fire are reproduced here explicitly: armed_hint true, and
    an enabled IBIT entry. Nothing reads the live file.
    """
    r = example_rules()
    r["armed_hint"] = True
    r["entries"]["IBIT"].update(
        {
            "enabled": True,
            "qty": 2,
            "limit": 43.90,
            "stop": 41.20,
            "cap": 44.50,
            "hold_reclaim": None,
            "require_hold_reclaim": False,
        }
    )
    return r


class TestHintBookAnswersNoGate(unittest.TestCase):
    """B2. fallback_book hardcoded in_rth True and took armed from a config hint.

    resolve_book substitutes that book whenever fetch_book returns None, which a
    transient 500 on the accounts endpoint does with valid tokens and a working
    POST path.
    """

    def setUp(self):
        """No test in this class may consult the real broker.

        PRE-EXISTING HOLE, closed here rather than in the wire: every test
        below calls resolve_book, which calls fetch_book, which is NOT
        short-circuited on a machine where the broker is installed --
        broker_available() is True whenever
        <SPIRAL_BROKER_ROOT>/src/token_manager.py exists, and it does on the
        Studio. fetch_book then os.chdir()s into the broker root (mutating this
        process's cwd for every test after it), loads .env, builds a
        TokenManager and can issue real read-only GETs to Schwab.

        These tests all assert source == "fallback_hint", i.e. they assert the
        read FAILED -- so they passed only because the OAuth refresh happens to
        be dead. That is a passing test resting on a broken credential, not
        isolation. Patching fetch_book makes the fallback path the thing under
        test rather than a symptom, and holds on a machine where the token
        works. The SPIRAL_BROKER_ROOT=/nonexistent pin in the documented test
        command is the belt; this is the braces.
        """
        original = temple_flow_wire.fetch_book
        temple_flow_wire.fetch_book = lambda: (None, "test: broker not consulted")
        self.addCleanup(setattr, temple_flow_wire, "fetch_book", original)

    def test_fallback_book_states_neither_armed_nor_rth(self):
        book = temple_flow_wire.fallback_book(studio_shaped_rules())
        self.assertNotIn("armed", book, "armed_hint must not answer the arm gate")
        self.assertNotIn("in_rth", book, "a config file must not answer the clock")
        # coverage is stated False, not merely absent
        self.assertIs(book["orders_ok"], False)
        self.assertIs(book["quotes_ok"], False)

    def test_resolve_book_stamps_the_real_session_armed(self):
        """The hint book's armed comes from session_armed(), not armed_hint."""
        rules = studio_shaped_rules()
        self.assertTrue(rules["armed_hint"])
        with patched("session_armed", lambda *a, **k: False):
            book, note = temple_flow_wire.resolve_book(rules)
        self.assertEqual(book["source"], "fallback_hint")
        self.assertIs(book["armed"], False, "expired session must win over the hint")
        self.assertNotIn("in_rth", book)

    def test_expired_arm_and_sunday_plan_no_ibit_buy(self):
        """The reviewer's measured B2 case, end to end.

        Before the fix: armed=True (hint), in_rth=True (hardcoded), orders=[] →
        plan_actions plans place_gtc_bracket IBIT qty 2 @ 43.90 and
        execute_action(live=True) returns 'posted'. Outside RTH, on an expired
        arm, duplicating a working order.
        """
        rules = studio_shaped_rules()
        with patched("session_armed", lambda *a, **k: False), patched(
            "in_rth", lambda now=None: False
        ):
            book, _ = temple_flow_wire.resolve_book(rules)
            actions = plan_actions(rules, book)
        ibit = [a for a in actions if a.get("symbol") == "IBIT"]
        self.assertTrue(ibit)
        self.assertFalse(
            any(a["op"] == "place_gtc_bracket" for a in ibit),
            f"live BUY outside RTH on an expired arm: {ibit}",
        )
        blocked = [a for a in ibit if a["reason"] == "new_risk_blocked"]
        self.assertTrue(blocked, ibit)
        reasons = blocked[0]["params"]["blocked"]
        self.assertIn("arm_required", reasons)
        self.assertIn("outside_rth", reasons)
        self.assertIn("orders_unproven", reasons)

    def test_hint_book_never_reaches_the_wire(self):
        """Boundary copy: even a planned action refuses on a non-schwab_read book."""
        rules = studio_shaped_rules()
        with patched("session_armed", lambda *a, **k: False):
            book, _ = temple_flow_wire.resolve_book(rules)
        action = {
            "op": "place_protect_stop",
            "symbol": "NVO",
            "reason": "protect_only_no_adds",
            "params": {"qty": 1, "stop": 42.5, "side": "SELL"},
        }
        with no_network():
            out = execute_action(action, live=True, rth=True, book=book)
        self.assertEqual(out["execute"], "refused")
        self.assertEqual(out["reason"], "book_not_schwab_read")
        self.assertIs(out["sent"], False)
        self.assertIs(out["mutated"], False)

    def test_hint_book_never_reaches_the_wire_for_a_cancel_either(self):
        """The DELETE half of the boundary.

        The five adapted cancel tests all pass a schwab_read book, so they
        exercise only the permit side: if book_is_live_eligible were ever
        inverted they would all still pass. This is the refusal side for a
        cancel, and precedence is asserted because AWAY_MODE.md lists both
        refusals as distinct diagnostics — eligibility is checked first, so it
        wins even on a symbol the universe check would also reject.
        """
        rules = studio_shaped_rules()
        with patched("session_armed", lambda *a, **k: True):
            book, _ = temple_flow_wire.resolve_book(rules)
        with no_network():
            in_universe = execute_action(
                {
                    "op": "cancel_abandon",
                    "symbol": "ETHA",
                    "params": {"order_id": "555"},
                },
                live=True,
                rth=True,
                book=book,
            )
            leftover = execute_action(
                {
                    "op": "cancel_abandon",
                    "symbol": "NOK",
                    "params": {"order_id": "1007691287449"},
                },
                live=True,
                rth=True,
                book=book,
            )
        for out in (in_universe, leftover):
            self.assertEqual(out["execute"], "refused")
            self.assertEqual(out["reason"], "book_not_schwab_read")
            self.assertIs(out["mutated"], False)

    def test_execute_action_refuses_when_no_book_is_supplied(self):
        with no_network():
            out = execute_action(
                {"op": "place_protect_stop", "symbol": "NVO", "params": {}},
                live=True,
                rth=True,
            )
        self.assertEqual(out["reason"], "book_missing")

    def test_outbox_ticket_refuses_on_a_hint_book(self):
        rules = studio_shaped_rules()
        with patched("session_armed", lambda *a, **k: True), patched(
            "in_rth", lambda now=None: True
        ):
            book, _ = temple_flow_wire.resolve_book(rules)
            with no_network():
                out = execute_outbox_ticket(
                    {"ticket": ticket(qty=5)}, live=True, rules=rules, book=book
                )
        # Both of these are WAIT reasons since 2026-09-03: a hint book means
        # the READ failed, which says nothing about the ticket. It defers and
        # is re-gated when the broker answers again. What must never change is
        # that no byte reaches the wire — no_network() above is the proof.
        self.assertEqual(out["execute"], "deferred")
        self.assertIn(out["reason"], ("orders_unproven", "book_not_schwab_read"))
        self.assertIs(out["sent"], False)
        self.assertIs(out["mutated"], False)


class TestPartialBrokerReadFailsClosed(unittest.TestCase):
    """B1. A non-200 on the orders or quotes sub-call left an EMPTY collection
    behind with no flag, and every gate this branch added is book-derived."""

    def test_blind_orders_block_both_protect_stops(self):
        """The reviewer's measured case (b): duplicate protect stops on NVO+NOK.

        That is the second SELL Schwab rejected on 2026-08-30 — the exact
        rejection the one-sell law exists to prevent.
        """
        rules = example_rules()
        book = base_book(orders_ok=False)
        actions = plan_actions(rules, book)
        for sym in ("NVO", "NOK"):
            rows = [a for a in actions if a.get("symbol") == sym]
            self.assertTrue(rows, sym)
            self.assertFalse(
                any(a["op"] == "place_protect_stop" for a in rows),
                f"blind book must not post a protect stop for {sym}: {rows}",
            )
            self.assertTrue(
                any(a["reason"] == "protect_blocked_orders_unproven" for a in rows),
                rows,
            )

    def test_blind_orders_block_a_new_entry(self):
        rules = example_rules()
        rules["entries"]["ETHA"]["enabled"] = True
        actions = plan_actions(rules, base_book(orders_ok=False))
        etha = [a for a in actions if a.get("symbol") == "ETHA"]
        self.assertFalse(any(a["op"] == "place_gtc_bracket" for a in etha), etha)
        blocked = [a for a in etha if a["reason"] == "new_risk_blocked"]
        self.assertIn("orders_unproven", blocked[0]["params"]["blocked"])

    def test_blind_quotes_block_a_new_entry(self):
        """last_above_hold_reclaim and through_cap_idea_dead only fire when last
        is not None, so blind quotes make BOTH skip and the entry proceed."""
        rules = example_rules()
        rules["entries"]["ETHA"]["enabled"] = True
        actions = plan_actions(rules, base_book(quotes_ok=False, quotes={}))
        etha = [a for a in actions if a.get("symbol") == "ETHA"]
        self.assertFalse(any(a["op"] == "place_gtc_bracket" for a in etha), etha)
        blocked = [a for a in etha if a["reason"] == "new_risk_blocked"]
        self.assertIn("quotes_unproven", blocked[0]["params"]["blocked"])

    def test_a_proven_book_still_permits_the_entry(self):
        """The gate must be able to SAY YES.

        Without this, every test above passes on a gate that simply never opens.
        """
        rules = example_rules()
        rules["entries"]["ETHA"]["enabled"] = True
        actions = plan_actions(rules, base_book())
        etha = [a for a in actions if a.get("symbol") == "ETHA"]
        self.assertTrue(
            any(a["op"] == "place_gtc_bracket" for a in etha),
            f"a complete read must still be allowed to trade: {etha}",
        )

    def test_blind_orders_refuse_the_outbox_ticket(self):
        """Measured case (a): with orders=[] the duplicate ticket POSTs."""
        reason, _ = gate_outbox_ticket(
            ticket(qty=11), example_rules(), base_book(orders_ok=False)
        )
        self.assertEqual(reason, "orders_unproven")

    def test_the_same_ticket_is_refused_by_the_true_book(self):
        """Proves the flag is not blanket-blocking: with the orders leg PROVEN
        and the real order in the book, the refusal is the specific one."""
        book = base_book(
            orders=[
                {
                    "id": "1007762031724",
                    "symbol": "ETHA",
                    "side": "BUY",
                    "status": "WORKING",
                    "type": "LIMIT",
                    "price": 18.70,
                    "duration": "GOOD_TILL_CANCEL",
                    "qty": 11,
                    "remaining": 11,
                }
            ]
        )
        reason, _ = gate_outbox_ticket(ticket(qty=11), example_rules(), book)
        self.assertEqual(reason, "existing_entry_in_book")
        # and with an empty-but-proven book the same ticket clears
        self.assertIsNone(gate_outbox_ticket(ticket(qty=11), example_rules(),
                                             base_book())[0])

    def test_blind_cancel_lane_says_so_instead_of_going_quiet(self):
        actions = plan_actions(example_rules(), base_book(orders_ok=False))
        self.assertTrue(
            any(a["reason"] == "cancel_lane_orders_unproven" for a in actions),
            actions,
        )

    def test_degraded_live_cycle_posts_nothing(self):
        """End to end: a partial read drives a whole live cycle and no broker
        helper is reached at all."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            out = run_cycle(
                example_rules(),
                base_book(orders_ok=False, quotes_ok=False),
                live=True,
                broker_note="test",
                repo_root=Path(tmpdir),
            )
        self.assertFalse(any(a.get("sent") for a in out), out)
        self.assertFalse(any(a.get("mutated") for a in out), out)


class TestProtectLaneStaleStop(unittest.TestCase):
    def test_stop_at_or_above_last_is_refused(self):
        """A stop above the bid is not protection, it is a market SELL on the
        next open."""
        rules = example_rules()
        rules["protect"]["NVO"]["stop"] = 46.00  # above last 45.81
        actions = plan_actions(rules, base_book())
        nvo = [a for a in actions if a.get("symbol") == "NVO"]
        self.assertFalse(any(a["op"] == "place_protect_stop" for a in nvo), nvo)
        self.assertTrue(
            any(
                a["reason"] == "protect_stop_at_or_above_last_would_market_sell"
                for a in nvo
            ),
            nvo,
        )

    def test_a_stop_below_last_still_places(self):
        actions = plan_actions(example_rules(), base_book())
        nvo = [a for a in actions if a.get("symbol") == "NVO"]
        self.assertTrue(any(a["op"] == "place_protect_stop" for a in nvo), nvo)

    def test_unproven_quotes_do_not_block_protection(self):
        """Deliberate: the duplicate check is what makes this lane safe, and it
        is satisfied. Only the stale-stop check needs quotes."""
        actions = plan_actions(example_rules(), base_book(quotes_ok=False, quotes={}))
        nvo = [a for a in actions if a.get("symbol") == "NVO"]
        self.assertTrue(any(a["op"] == "place_protect_stop" for a in nvo), nvo)


class TestOutboxCarriesTheNoChaseLaw(unittest.TestCase):
    """Suggestion 2. AWAY_MODE.md: the outbox is not a side door around the
    standing rules, and the rules state the cap as an idea-level threshold."""

    def test_ticket_limit_above_cap_is_refused(self):
        # entries.ETHA.cap is 18.90 in the example file
        reason, detail = gate_outbox_ticket(
            ticket(qty=5, limit=19.50, stop=18.50), example_rules(), base_book()
        )
        self.assertEqual(reason, "ticket_limit_above_cap")
        self.assertEqual(detail["cap"], 18.9)

    def test_last_through_cap_kills_the_ticket(self):
        book = base_book(quotes={"ETHA": {"last": 18.95}})
        reason, _ = gate_outbox_ticket(ticket(qty=5), example_rules(), book)
        self.assertEqual(reason, "through_cap_idea_dead")

    def test_a_ticket_under_the_cap_still_clears(self):
        reason, _ = gate_outbox_ticket(ticket(qty=11), example_rules(), base_book())
        self.assertIsNone(reason)


class TestInCycleCancelVisibility(unittest.TestCase):
    """Suggestion 1. The twin of the bug db02dce closed, on the cancel half."""

    def test_one_cancel_per_order_per_cycle(self):
        book = base_book(
            orders=[
                {
                    "id": "555",
                    "symbol": "ETHA",
                    "side": "BUY",
                    "status": "WORKING",
                    "type": "LIMIT",
                    "price": 18.75,
                    "duration": "DAY",  # no_day makes plan_actions want it gone
                    "qty": 1,
                    "remaining": 1,
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir, recording_broker() as calls:
            root = Path(tmpdir)
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True)
            (outbox / "TF-CANCEL.json").write_text(
                json.dumps(ticket(id="TF-CANCEL", action="cancel_by_id", order_id="555"))
            )
            run_cycle(
                example_rules(), book, live=True, broker_note="test", repo_root=root
            )
        self.assertEqual(
            calls["cancel"],
            ["555"],
            "the planner must see the outbox's cancel, not re-fire it",
        )

    def test_record_marks_the_order_not_working(self):
        book = base_book(
            orders=[{"id": 555, "symbol": "ETHA", "status": "WORKING", "side": "BUY"}]
        )
        temple_flow_wire.record_in_cycle_cancel(book, "555")
        self.assertIsNone(working_order_by_id(book, "555"))


class TestExecuteBoundaryDefenses(unittest.TestCase):
    def test_execute_refuses_a_cancel_outside_the_universe(self):
        """Suggestion 6. The universe restriction lived only in the planner."""
        with no_network():
            out = execute_action(
                {
                    "op": "cancel_abandon",
                    "symbol": "NOK",
                    "params": {"order_id": "1007691287449"},
                },
                live=True,
                rth=True,
                book=base_book(),
            )
        self.assertEqual(out["execute"], "refused")
        self.assertEqual(out["reason"], "cancel_symbol_not_in_live_universe")

    def test_planner_exception_is_quarantined_not_fatal(self):
        """Suggestion 5. Neither schwab_post_order nor cancel_by_id wraps
        requests, so a network error used to abort the rest of the cycle."""

        def exploding_stop(**kw):
            raise ConnectionError("connection reset by peer")

        with tempfile.TemporaryDirectory() as tmpdir, recording_broker(), patched(
            "place_protect_stop", exploding_stop
        ):
            out = run_cycle(
                example_rules(),
                base_book(),
                live=True,
                broker_note="test",
                repo_root=Path(tmpdir),
            )
        stops = [a for a in out if a.get("op") == "place_protect_stop"]
        self.assertEqual(len(stops), 2, out)
        for s in stops:
            self.assertEqual(s["execute"], "exception")
            self.assertEqual(s["error"], "ConnectionError")
            self.assertIs(s["sent"], False)
            self.assertIs(s["mutated"], False)
        # the cycle still finished: the entry lane ran behind the failure
        self.assertTrue(
            any(a.get("reason") == "entry_disabled" for a in out),
            "actions behind the exception must still be executed",
        )


class TestRefusalClassificationIsComplete(unittest.TestCase):
    """No refusal reason may exist without a disposition.

    An unclassified reason is not a neutral gap. refusal_is_wait() fails closed,
    so an unclassified reason quarantines — which for a timing refusal is the
    exact bug Anthony ordered fixed, silently reintroduced by whoever adds the
    next gate. This test is the tripwire: add a reason, classify it or fail.
    """

    #: Every function that may name a refusal reason. The guard test below
    #: proves this list is not silently outgrown.
    SCANNED = (
        "gate_outbox_ticket",
        "ticket_wait_bounds_refusal",
        "book_is_live_eligible",
        "execute_outbox_ticket",
    )
    #: Strings that reach out["reason"] without being refusals.
    NOT_REFUSALS = frozenset({"gates_passed_would_post"})

    @staticmethod
    def _module_tree() -> ast.Module:
        return ast.parse(Path(temple_flow_wire.__file__).read_text())

    @classmethod
    def _func(cls, tree: ast.Module, name: str) -> ast.FunctionDef:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"{name} not found in temple_flow_wire")

    #: The wire's single refusal exit inside execute_outbox_ticket. Reserved:
    #: any function defining or calling something by this name is scanned for
    #: its literal first argument.
    REFUSE_CALL = "_refuse"

    @staticmethod
    def _refuse_literal(node: ast.AST) -> str | None:
        """The literal first argument of a `_refuse("<reason>")` call, if any."""
        if not isinstance(node, ast.Call):
            return None
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == TestRefusalClassificationIsComplete.REFUSE_CALL):
            return None
        if not node.args:
            return None
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value:
            return first.value
        return None

    @classmethod
    def _reasons_in(cls, tree: ast.Module, name: str) -> set:
        """String literals this function can hand back as a refusal reason.

        THREE shapes, because the wire uses three:

          1. `return "<reason>", detail` — gate_outbox_ticket,
             ticket_wait_bounds_refusal (and book_is_live_eligible's
             `return False, "<reason>"`).
          2. `out["reason"] = "<reason>"` — the dry-run / outcome assignments.
          3. `return _refuse("<reason>")` — EVERY refusal in
             execute_outbox_ticket since the wait/die split landed.

        Shape 3 was missing for one commit, and the cost was exact: the four
        reasons execute_outbox_ticket names went unscanned, so the completeness
        assertion below was complete BY HAND rather than by test, while the
        docstring claimed otherwise. test_the_refuse_shape_is_not_invisible is
        the standing positive control that it stays visible.

        Reads the file rather than the imported object so indentation and
        decorators cannot skew it.
        """
        found = set()
        for node in ast.walk(cls._func(tree, name)):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        if elt.value:
                            found.add(elt.value)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if not isinstance(node.value.value, str):
                    continue
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value == "reason"
                    ):
                        found.add(node.value.value)
            literal = cls._refuse_literal(node)
            if literal is not None:
                found.add(literal)
        return found

    def test_every_reason_is_in_exactly_one_set(self):
        tree = self._module_tree()
        reasons = set()
        for name in self.SCANNED:
            reasons |= self._reasons_in(tree, name)
        reasons -= self.NOT_REFUSALS
        self.assertTrue(reasons, "the scan found nothing; the extractor is broken")
        for reason in sorted(reasons):
            in_wait = reason in temple_flow_wire.WAIT_REFUSALS
            in_terminal = reason in temple_flow_wire.TERMINAL_REFUSALS
            self.assertTrue(
                in_wait or in_terminal,
                f"refusal reason {reason!r} is in neither WAIT_REFUSALS nor "
                f"TERMINAL_REFUSALS. Classify it: does a later cycle stand any "
                f"chance of finding it changed?",
            )
            self.assertFalse(
                in_wait and in_terminal,
                f"refusal reason {reason!r} is in BOTH sets",
            )

    def test_the_refuse_shape_is_not_invisible(self):
        """Positive control on the extractor, not on the wire.

        The whole completeness assertion above is worthless if the extractor
        cannot see the shape the wire actually uses. It could not, for one
        commit: execute_outbox_ticket routes EVERY refusal through
        `_refuse("<literal>")`, an ast.Call, and the extractor inspected only
        Return-of-Tuple and `out["reason"] = ...`. It therefore contributed a
        single string — `gates_passed_would_post` — which NOT_REFUSALS removed,
        leaving it contributing ZERO reasons while the docstring advertised
        full coverage. Injecting an unclassified reason left this class green.

        This test is what makes the injection go red and stay red.
        """
        tree = self._module_tree()
        found = self._reasons_in(tree, "execute_outbox_ticket")
        for known in ("ticket_unreadable", "rules_missing", "book_missing"):
            self.assertIn(
                known,
                found,
                f"the extractor no longer sees {known!r}, which the wire "
                f"refuses via _refuse(). Every reason reached only through "
                f"_refuse is unclassified and quarantines silently.",
            )
        self.assertGreaterEqual(
            len(found - self.NOT_REFUSALS),
            3,
            "execute_outbox_ticket must contribute its own reasons to the "
            "completeness scan, not ride on the other three functions",
        )

    def test_the_two_sets_are_disjoint_and_the_helper_fails_closed(self):
        self.assertEqual(
            temple_flow_wire.WAIT_REFUSALS & temple_flow_wire.TERMINAL_REFUSALS,
            frozenset(),
        )
        for reason in temple_flow_wire.WAIT_REFUSALS:
            self.assertTrue(temple_flow_wire.refusal_is_wait(reason))
        for reason in temple_flow_wire.TERMINAL_REFUSALS:
            self.assertFalse(temple_flow_wire.refusal_is_wait(reason))
        # an unclassified reason quarantines — the pre-2026-09-03 behaviour
        self.assertFalse(temple_flow_wire.refusal_is_wait("a_reason_invented_later"))
        self.assertFalse(temple_flow_wire.refusal_is_wait(None))

    def test_no_unscanned_function_hands_back_a_reason(self):
        """Guard on SCANNED itself.

        A new helper that returns ("some_reason", detail) and is called from
        gate_outbox_ticket would be invisible to the scan above — the reason
        would ship unclassified and the completeness test would still pass.

        Both reason-producing shapes are guarded, for the identical reason:
        a tuple-returning helper, and any function that calls `_refuse` with a
        literal. `_refuse` is a RESERVED NAME in this wire — if a second one is
        ever defined elsewhere, its host function belongs in SCANNED.
        """
        tree = self._module_tree()
        returners = set()
        refusers = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Return)
                    and isinstance(sub.value, ast.Tuple)
                    and sub.value.elts
                    and isinstance(sub.value.elts[0], ast.Constant)
                    and isinstance(sub.value.elts[0].value, str)
                    and sub.value.elts[0].value
                ):
                    returners.add(node.name)
                if self._refuse_literal(sub) is not None:
                    refusers.add(node.name)
        self.assertLessEqual(
            returners,
            set(self.SCANNED),
            "a function outside SCANNED now returns a reason literal; add it "
            "to SCANNED so its reasons are classified",
        )
        # The nested def _refuse itself is walked as its own FunctionDef when
        # it contains a _refuse call; it does not, so only its hosts appear.
        self.assertLessEqual(
            refusers,
            set(self.SCANNED),
            "a function outside SCANNED now names a reason through _refuse(); "
            "add it to SCANNED so its reasons are classified",
        )


class TestWaitNotDie(unittest.TestCase):
    """Anthony, 2026-09-03 07:49 EDT: 'They should wait not die. Execution
    should start back up when the markets open.'

    Before this, a ticket refused for `outside_rth` or `arm_required` was
    quarantined to failed/ exactly like a malformed one, so a ticket approved
    the night before was dead by morning for the offence of having been written
    while the market was shut.
    """

    ET = temple_flow_wire.ET

    def at(self, hour: int, minute: int = 0, day: int = 3) -> datetime:
        """A wall clock in ET. 2026-09-03 is a Thursday, so RTH applies."""
        return datetime(2026, 9, day, hour, minute, tzinfo=self.ET)

    def _write(self, root: Path, t: dict) -> Path:
        outbox = root / "config" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        p = outbox / f"{t.get('id') or 'TF'}.json"
        p.write_text(json.dumps(t))
        return p

    @staticmethod
    def _ticket_lines(out: list) -> list:
        return [a for a in out if a.get("op") == "outbox_ticket"]

    # --- terminal refusals still die immediately, even at 3 am -------------

    def test_terminal_refusal_quarantines_at_three_am(self):
        """FAILS ON 7d2d5c2 on the REASON, not on the move.

        Pre-change every refusal quarantined, so the file lands in failed/
        either way. What pre-change gets wrong is WHICH gate answered: with
        arm and RTH ahead of the caps, an oversized ticket at 03:00 reports
        `arm_required` — a WAIT reason under the new rule — and would have sat
        in the outbox all night for a ticket that can never pass. The reorder
        is what makes it report the size law it actually broke.
        """
        night = base_book(in_rth=False, armed=False)
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(root, ticket(id="TF-FAT", qty=20))
            out = run_cycle(
                example_rules(),
                night,
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["reason"], "ticket_qty_exceeds_risk_clip")
            self.assertEqual(line["execute"], "refused")
            self.assertFalse(p.exists())
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    def test_wrong_symbol_at_three_am_still_dies(self):
        """Regression guard, and honest about it: this passes on 7d2d5c2 too.

        The universe check already ran ahead of arm/RTH, so SOFI quarantined at
        03:00 before the change. It is here because the reorder moved code
        around it and a silent inversion would be catastrophic: a ticket for a
        symbol the daemon may not trade must never be parked to be retried.
        """
        night = base_book(in_rth=False, armed=False)
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(
                root, ticket(id="TF-SOFI", symbol="SOFI", limit=8.5, stop=8.2, qty=10)
            )
            out = run_cycle(
                example_rules(),
                night,
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["reason"], "not_in_live_universe")
            self.assertEqual(line["execute"], "refused")
            self.assertFalse(p.exists())
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    def test_a_blind_read_defers_even_a_symbol_that_can_never_trade(self):
        """The one place a WAIT legitimately precedes a terminal check.

        `orders_unproven` runs ahead of the universe check, so during a Schwab
        outage a SOFI ticket defers instead of dying, and dies on the next
        healthy read. Pinned because it looks like a bug until you see why: no
        book-derived gate may run on a book that has not proven itself, and
        holding that rule absolute is worth one delayed death.
        """
        blind = base_book(in_rth=False, armed=False, orders_ok=False)
        sofi = ticket(id="TF-SOFI", symbol="SOFI", limit=8.5, stop=8.2, qty=10)
        self.assertEqual(
            gate_outbox_ticket(sofi, example_rules(), blind, now=self.at(3))[0],
            "orders_unproven",
        )
        self.assertEqual(
            gate_outbox_ticket(
                sofi, example_rules(), base_book(in_rth=False, armed=False),
                now=self.at(3),
            )[0],
            "not_in_live_universe",
        )

    # --- wait refusals keep the file --------------------------------------

    def test_wait_refusal_keeps_the_file_and_stamps_first_seen_once(self):
        """FAILS ON 7d2d5c2 at the first assertion: p.exists().

        Pre-change `arm_required` quarantines to failed/, so the file is gone
        after cycle one and there is no first_seen_at anywhere.
        """
        night = base_book(in_rth=False, armed=False)
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11))
            out1 = run_cycle(
                example_rules(),
                night,
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            line1 = self._ticket_lines(out1)[0]
            self.assertEqual(line1["execute"], "deferred")
            self.assertEqual(line1["reason"], "arm_required")
            self.assertIs(line1["sent"], False)
            self.assertIs(line1["mutated"], False)
            self.assertEqual(line1["deferrals"], 1)
            self.assertTrue(line1["stamped_first_seen"])
            self.assertTrue(p.exists(), "a waiting ticket must stay in the outbox")
            self.assertFalse((root / "config" / "outbox" / "failed").exists())

            stamped_once = json.loads(p.read_text())["first_seen_at"]
            self.assertTrue(stamped_once)

            # a second deferral, an hour later: the stamp is NOT refreshed, or
            # max_wait_days could never fire
            out2 = run_cycle(
                example_rules(),
                night,
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(4),
            )
            line2 = self._ticket_lines(out2)[0]
            self.assertEqual(line2["execute"], "deferred")
            self.assertNotIn("stamped_first_seen", line2)
            self.assertEqual(line2["deferrals"], 2)
            self.assertEqual(json.loads(p.read_text())["first_seen_at"], stamped_once)

    def test_dry_run_defers_without_touching_the_ticket(self):
        """A hand-run dry cycle must not start the max_wait clock."""
        night = base_book(in_rth=False, armed=False)
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11))
            before = p.read_text()
            out = run_cycle(
                example_rules(),
                night,
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "arm_required")
            self.assertNotIn("stamped_first_seen", line)
            self.assertTrue(p.exists())
            self.assertEqual(p.read_text(), before)

    def test_cancel_outside_rth_waits(self):
        """FAILS ON 7d2d5c2 at p.exists(): the cancel ticket was quarantined.

        The DELETE is held outside RTH because Schwab 400s it after hours. That
        is a clock refusal like any other, so the ticket waits for the open.
        """
        book = base_book(
            in_rth=False,
            armed=False,
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
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(
                root, ticket(id="TF-CANCEL", action="cancel_by_id", order_id=12345)
            )
            out = run_cycle(
                example_rules(),
                book,
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "outside_rth")
            self.assertIs(line["mutated"], False)
            self.assertTrue(p.exists())

    def test_a_cancel_that_can_never_work_still_dies_at_three_am(self):
        """The terminal half of the cancel lane, at the same hour."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(
                root, ticket(id="TF-GHOST", action="cancel_by_id", order_id="404404")
            )
            out = run_cycle(
                example_rules(),
                base_book(in_rth=False, armed=False),
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["reason"], "cancel_order_id_not_working_in_book")
            self.assertEqual(line["execute"], "refused")
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    # --- bounded waiting ---------------------------------------------------

    def test_expires_at_is_terminal(self):
        """FAILS ON 7d2d5c2: expires_at is not read at all there, so the ticket
        reports arm_required instead of ticket_expired."""
        night = base_book(in_rth=False, armed=False)
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(
                root, ticket(id="TF-EXP", qty=11, expires_at="2026-09-02T16:00:00")
            )
            out = run_cycle(
                example_rules(),
                night,
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["reason"], "ticket_expired")
            self.assertEqual(line["execute"], "refused")
            self.assertFalse(p.exists())
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    def test_expires_at_in_the_future_does_not_bite(self):
        reason, detail = gate_outbox_ticket(
            ticket(qty=11, expires_at="2026-09-30T16:00:00"),
            example_rules(),
            base_book(),
            now=self.at(10),
        )
        self.assertIsNone(reason, detail)

    def test_expires_at_honours_an_offset(self):
        # 2026-09-03T08:00:00+00:00 is 04:00 ET, so a 10:00 ET clock is past it
        reason, _ = gate_outbox_ticket(
            ticket(qty=11, expires_at="2026-09-03T08:00:00+00:00"),
            example_rules(),
            base_book(),
            now=self.at(10),
        )
        self.assertEqual(reason, "ticket_expired")

    def test_unparseable_expires_at_is_a_schema_error_not_a_free_pass(self):
        reason, detail = gate_outbox_ticket(
            ticket(qty=11, expires_at="tomorrow-ish"),
            example_rules(),
            base_book(),
            now=self.at(10),
        )
        self.assertEqual(reason, "ticket_schema_invalid")
        self.assertIn("expires_at_not_iso", detail["schema_errors"])

    def test_max_wait_days_is_terminal(self):
        """FAILS ON 7d2d5c2: no outbox.max_wait_days rule exists there."""
        rules = example_rules()
        rules["outbox"] = {"max_wait_days": 2}
        night = base_book(in_rth=False, armed=False)
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(
                root,
                ticket(
                    id="TF-OLD",
                    qty=11,
                    first_seen_at="2026-08-29T03:00:00",
                    deferrals=97,
                ),
            )
            out = run_cycle(
                rules,
                night,
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["reason"], "ticket_wait_exceeded")
            self.assertEqual(line["execute"], "refused")
            self.assertFalse(p.exists())
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    def test_max_wait_days_absent_means_no_limit(self):
        """Anthony's default. A ticket stamped a year ago still only waits."""
        reason, _ = gate_outbox_ticket(
            ticket(qty=11, first_seen_at="2025-09-03T03:00:00"),
            example_rules(),
            base_book(in_rth=False, armed=False),
            now=self.at(3),
        )
        self.assertEqual(reason, "arm_required")

    def test_max_wait_days_inside_the_window_still_waits(self):
        rules = example_rules()
        rules["outbox"] = {"max_wait_days": 7}
        reason, _ = gate_outbox_ticket(
            ticket(qty=11, first_seen_at="2026-09-02T22:00:00"),
            rules,
            base_book(in_rth=False, armed=False),
            now=self.at(3),
        )
        self.assertEqual(reason, "arm_required")

    def test_a_garbled_max_wait_days_does_not_kill_tickets(self):
        rules = example_rules()
        rules["outbox"] = {"max_wait_days": "soon"}
        days, problem = temple_flow_wire.outbox_max_wait_days(rules)
        self.assertIsNone(days)
        self.assertTrue(problem)
        reason, detail = gate_outbox_ticket(
            ticket(qty=11, first_seen_at="2025-01-01T03:00:00"),
            rules,
            base_book(in_rth=False, armed=False),
            now=self.at(3),
        )
        self.assertEqual(reason, "arm_required")
        self.assertIn("max_wait_days_problem", detail)

    def test_max_opens_is_not_a_daily_box_and_the_wait_is_indefinite(self):
        """Locks the WAIT_REFUSALS docstring to a measurement.

        That docstring called the risk box "a daily box that resets". Only the
        day breaker is day-scoped. count_opens counts DISTINCT SYMBOLS holding
        a position with qty>0 or a working BUY entry, and the standing NVO/NOK
        protect-only positions occupy 2 of them permanently.

        MEASURED HERE, including the bound that makes it narrower than it
        sounds: with a two-symbol live universe a ticket that reaches the risk
        box caps opens at 3, so the DEFAULT max_opens 4 passes. Saturation
        needs a fourth distinct symbol or a tighter cap. Both persist across
        days -- which is the point: `new_risk_blocked` is a WAIT, so the ticket
        parks indefinitely, bounded only by expires_at / outbox.max_wait_days.
        """
        self.assertIn("new_risk_blocked", temple_flow_wire.WAIT_REFUSALS)
        base = base_book()
        self.assertEqual(
            temple_flow_wire.count_opens(base),
            2,
            "NVO + NOK occupy two open slots with no order working",
        )

        # The default cap does NOT block: opens tops out at 3 for a reachable
        # ticket. Stated so nobody cites this hazard as firing today.
        three = base_book()
        three["positions"].append({"symbol": "IBIT", "qty": 2})
        self.assertEqual(temple_flow_wire.count_opens(three), 3)
        self.assertIsNone(
            gate_outbox_ticket(ticket(qty=11), example_rules(), three, now=self.at(10))[0]
        )

        # A fourth distinct symbol in the account saturates the default cap.
        four = base_book()
        four["positions"] += [{"symbol": "IBIT", "qty": 2}, {"symbol": "AAPL", "qty": 5}]
        self.assertEqual(temple_flow_wire.count_opens(four), 4)
        reason, detail = gate_outbox_ticket(
            ticket(qty=11), example_rules(), four, now=self.at(10)
        )
        self.assertEqual(reason, "new_risk_blocked")
        self.assertEqual(detail["opens"], 4)

        # Same book, a different day: still blocked. Nothing resets it.
        later, _ = gate_outbox_ticket(
            ticket(qty=11), example_rules(), four, now=self.at(10, day=10)
        )
        self.assertEqual(later, "new_risk_blocked", "max_opens is not day-scoped")

    def test_a_huge_max_wait_days_waits_instead_of_raising(self):
        """A config meaning "never expire" must not kill every waiting ticket.

        MEASURED before the fix: `max_wait_days: 1e12` parsed clean, then
        `first_seen + timedelta(days=1e12)` raised OverflowError, run_cycle
        caught it into execute="exception", and the ticket was quarantined to
        failed/. `999999999` got past timedelta and overflowed the datetime
        ADD instead — so bounding the value alone would not have fixed it.
        The wire measures elapsed time now, which is total over every finite
        value. Both sentinels below must WAIT, which is what the docstring on
        outbox_max_wait_days has always promised.
        """
        for sentinel in (1e12, 999999999, 999999999999):
            with self.subTest(sentinel=sentinel):
                rules = example_rules()
                rules["outbox"] = {"max_wait_days": sentinel}
                days, problem = temple_flow_wire.outbox_max_wait_days(rules)
                self.assertIsNone(problem)
                self.assertEqual(days, float(sentinel))
                reason, detail = gate_outbox_ticket(
                    ticket(qty=11, first_seen_at="2025-01-01T03:00:00"),
                    rules,
                    base_book(in_rth=False, armed=False),
                    now=self.at(3),
                )
                self.assertEqual(reason, "arm_required", detail)
                self.assertGreater(detail["waited_days"], 600)

    def test_max_wait_days_true_is_not_a_one_day_limit(self):
        """`float(True)` is 1.0. A rules value reading as "enabled" must not
        silently become the tightest possible deadline and start killing
        tickets after 24 hours."""
        rules = example_rules()
        rules["outbox"] = {"max_wait_days": True}
        days, problem = temple_flow_wire.outbox_max_wait_days(rules)
        self.assertIsNone(days)
        self.assertEqual(problem, "max_wait_days_unparseable:bool")
        reason, detail = gate_outbox_ticket(
            ticket(qty=11, first_seen_at="2025-01-01T03:00:00"),
            rules,
            base_book(in_rth=False, armed=False),
            now=self.at(3),
        )
        self.assertEqual(reason, "arm_required")
        self.assertIn("max_wait_days_problem", detail)

    def test_the_boundary_of_max_wait_days_is_unchanged_by_the_rewrite(self):
        """Elapsed-vs-deadline must keep the same strict comparison.

        first_seen 2026-09-01T03:00, max_wait_days 2: at exactly 2 days the
        ticket still waits; one minute past, it dies.
        """
        rules = example_rules()
        rules["outbox"] = {"max_wait_days": 2}
        t = ticket(qty=11, first_seen_at="2026-09-01T03:00:00")
        night = base_book(in_rth=False, armed=False)
        exact, _ = gate_outbox_ticket(t, rules, night, now=self.at(3))
        self.assertEqual(exact, "arm_required", "exactly at the bound waits")
        past, _ = gate_outbox_ticket(t, rules, night, now=self.at(3, 1))
        self.assertEqual(past, "ticket_wait_exceeded", "one minute past dies")

    def test_the_rewrite_is_equivalent_at_every_boundary_including_fractions(self):
        """The rewrite swapped exact timedelta arithmetic for a float division,
        so it owes a proof that it did not move the boundary. This is the one
        place the overflow fix could have changed a live disposition in a
        direction nobody asked for -- a fractional max_wait_days flipping to
        terminal on a rounding artifact would kill tickets silently.

        Compares the pre-rewrite form against the shipped one across whole,
        fractional and near-zero day values at the exact bound and one second
        either side. Zero mismatches is the assertion.
        """
        first_seen = datetime(2026, 9, 3, 3, 0, tzinfo=self.ET)
        mismatches = []
        for days in (0.0, 1e-9, 0.25, 1 / 3, 0.5, 2, 3.7, 7):
            for offset in (-60, -1, 0, 1, 60):
                t_now = first_seen + timedelta(days=days, seconds=offset)
                before = (first_seen + timedelta(days=days)) < t_now
                after = ((t_now - first_seen).total_seconds() / 86400.0) > days
                if before != after:
                    mismatches.append((days, offset, before, after))
        self.assertEqual(mismatches, [], "the rewrite moved the deadline")

        # And end to end on the fractional case, through the real helper.
        rules = example_rules()
        rules["outbox"] = {"max_wait_days": 0.5}
        t = ticket(qty=11, first_seen_at="2026-09-03T03:00:00")
        at_bound, _ = temple_flow_wire.ticket_wait_bounds_refusal(
            t, rules, now=first_seen + timedelta(hours=12)
        )
        self.assertIsNone(at_bound, "exactly half a day still waits")
        past_bound, _ = temple_flow_wire.ticket_wait_bounds_refusal(
            t, rules, now=first_seen + timedelta(hours=12, seconds=1)
        )
        self.assertEqual(past_bound, "ticket_wait_exceeded")

    def test_an_expired_ticket_dies_even_when_the_book_is_missing(self):
        """The deadline is read before the book check, not only inside the gate.

        MEASURED before the fix: execute_outbox_ticket returned
        _refuse("book_missing") — a WAIT — above the gate that evaluates
        expires_at, so a ticket that expired in 2020 deferred forever on an
        empty book. Reachability is honest: resolve_book always substitutes a
        fallback book, so book={} is a direct-call hole, not a daemon one.
        """
        with no_network():
            out = execute_outbox_ticket(
                {"ticket": ticket(qty=11, expires_at="2020-01-01T00:00:00")},
                live=True,
                rules=example_rules(),
                book={},
            )
        self.assertEqual(out["reason"], "ticket_expired")
        self.assertEqual(out["execute"], "refused")
        self.assertIs(out["sent"], False)
        self.assertIs(out["mutated"], False)

    def test_a_live_ticket_still_waits_on_a_missing_book(self):
        """The other half: reordering must not turn book_missing terminal."""
        with no_network():
            out = execute_outbox_ticket(
                {"ticket": ticket(qty=11)},
                live=True,
                rules=example_rules(),
                book={},
            )
        self.assertEqual(out["reason"], "book_missing")
        self.assertEqual(out["execute"], "deferred")

    def test_an_already_sent_ticket_is_done_not_expired(self):
        """schwab_order_id wins over every bound. A ticket that was SENT must
        never be filed as failed/ because a deadline later passed."""
        with no_network():
            out = execute_outbox_ticket(
                {
                    "ticket": ticket(
                        qty=11,
                        schwab_order_id="123456",
                        expires_at="2020-01-01T00:00:00",
                    )
                },
                live=True,
                rules=example_rules(),
                book=base_book(),
            )
        self.assertEqual(out["execute"], "skip_already_sent")
        self.assertIn(out["execute"], temple_flow_wire._TICKET_DONE)

    def test_a_corrupt_first_seen_at_does_not_restart_the_clock(self):
        rules = example_rules()
        rules["outbox"] = {"max_wait_days": 1}
        reason, detail = gate_outbox_ticket(
            ticket(qty=11, first_seen_at="not-a-date"),
            rules,
            base_book(),
            now=self.at(10),
        )
        self.assertEqual(reason, "ticket_schema_invalid")
        self.assertIn("first_seen_at_not_iso", detail["schema_errors"])

    # --- the whole point: it comes back at the open ------------------------

    def test_three_cycles_deferred_deferred_then_posted_at_the_open(self):
        """FAILS ON 7d2d5c2 at the first p.exists(): the 03:00 cycle moves the
        ticket to failed/, and there is nothing left for 09:00 or 10:00 to run.

        No resume path is written anywhere. The ticket simply survives, and the
        10:00 cycle gates it from scratch like any other.
        """
        posted = []

        def mock_place(**kw):
            posted.append(kw)
            return {"http": 201, "order_id": "1007762031724", "error": ""}

        rules = example_rules()
        with tempfile.TemporaryDirectory() as tmpdir, recording_broker(), patched(
            "place_gtc_bracket", mock_place
        ):
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11))

            # 03:00 — closed, not armed
            out = run_cycle(
                rules,
                base_book(in_rth=False, armed=False),
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            self.assertEqual(self._ticket_lines(out)[0]["execute"], "deferred")
            self.assertTrue(p.exists())
            self.assertEqual(posted, [])
            first_seen = json.loads(p.read_text())["first_seen_at"]

            # 09:00 — still pre-open (RTH starts at 09:00 by the wire's clock,
            # but the session is not armed yet)
            out = run_cycle(
                rules,
                base_book(in_rth=False, armed=False),
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(9),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "arm_required")
            self.assertTrue(p.exists())
            self.assertEqual(posted, [])
            self.assertEqual(json.loads(p.read_text())["first_seen_at"], first_seen)

            # 10:00 — open and armed. Same gate list, no special resume path.
            out = run_cycle(
                rules,
                base_book(in_rth=True, armed=True),
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(10),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "posted")
            self.assertIs(line["sent"], True)
            self.assertEqual(len(posted), 1)
            self.assertEqual(posted[0]["symbol"], "ETHA")
            self.assertEqual(posted[0]["qty"], 11)

            # and only now does the file move
            self.assertFalse(p.exists())
            done = root / "config" / "outbox" / "done" / p.name
            self.assertTrue(done.exists())
            landed = json.loads(done.read_text())
            self.assertEqual(landed["schwab_order_id"], "1007762031724")
            self.assertEqual(landed["first_seen_at"], first_seen)
            self.assertFalse((root / "config" / "outbox" / "failed").exists())

    def test_a_waiting_ticket_is_re_gated_not_waved_through(self):
        """Waiting carries no permission forward.

        The ticket defers at 03:00, and by the open the book has grown a
        working entry on the symbol. It must be refused on that, not posted
        because it 'was already approved last night'.
        """
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11))
            run_cycle(
                example_rules(),
                base_book(in_rth=False, armed=False),
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(3),
            )
            self.assertTrue(p.exists())
            busy = base_book(
                in_rth=True,
                armed=True,
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
                ],
            )
            out = run_cycle(
                example_rules(),
                busy,
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(10),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["reason"], "existing_entry_in_book")
            self.assertEqual(line["execute"], "refused")
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
