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

# THE OFFLINE PIN, AND IT IS EXECUTABLE RATHER THAN PROSE ON PURPOSE.
# temple_flow_wire computes BROKER_ROOT from this variable AT IMPORT
# (temple_flow_wire.py:46-48), and broker_available() is the only thing standing
# between an unpatched read helper and a real Schwab OAuth refresh + GET. Until
# 2026-09-04 the pin lived ONLY in comments and in the command an operator was
# trusted to type; run plainly on the Studio — where ~/spiral-broker exists —
# fetch_daily_history would have reached the live account, in flat violation of
# rule 2 at the top of this file.
#
# FORCE-SET, not setdefault: the launchd plist exports
# SPIRAL_BROKER_ROOT=/Users/tony_studio/spiral-broker, so any shell that
# inherited the daemon's environment would defeat a setdefault. No test in this
# file needs a real broker root, so there is nothing to preserve.
# test_no_broker_on_the_machine_means_history_unproven is the positive control:
# it asserts broker_available() is False, so if this line is ever removed the
# suite says so instead of quietly going online.
os.environ["SPIRAL_BROKER_ROOT"] = "/nonexistent"

sys.path.insert(0, str(HERE))

import temple_flow_strategy  # noqa: E402
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


#: "the caller said nothing", distinct from "the caller said None". Needed
#: because None is a MEANINGFUL value for a quote stamp — it is the absent-stamp
#: case the freshness gate now refuses on.
_UNSET = object()


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


# =============================================================================
# Off-hours planning, the approval path, and re-evaluation with fresh data.
#
# Anthony, 2026-09-03 07:49 EDT:
#   "on market off hours, there should be more strategy being defined and
#    planning on the trends"
# Anthony, 2026-09-03 11:47 EDT:
#   "if the trade doesn't go through when it was supposed to go through or when
#    it was planned, it should be reevaluate with updated data time sensitive
#    data"
#
# TWO STANDING NOTES FOR THIS BLOCK, both about what keeps it off the network:
#
#   1. `no_network()` patches the two ORDER helpers. It does NOT patch
#      fetch_daily_history, which is a READ. What keeps an unpatched read off
#      the wire is the INVOCATION: the suite runs with
#      SPIRAL_BROKER_ROOT=/nonexistent, so broker_available() is False and
#      _broker_auth() returns before `import requests` is even reached. That is
#      a real structural guard (fetch_book has the identical one) but it lives
#      in the test command, not in the code —
#      test_no_broker_on_the_machine_means_history_unproven is the positive
#      control that it holds.
#   2. Every test that needs candles INJECTS them through
#      patched("fetch_daily_history", ...). A planning or re-evaluation test
#      that reached the real function would be testing the network, not the
#      wire.
# =============================================================================


def synth_history(
    symbol: str = "ETHA",
    bars: int = 120,
    end: float = 18.30,
    step: float = 0.038,
    history_ok: bool = True,
    as_of: str = "2026-09-03T20:00:00-04:00",
    note: str = "fixture",
) -> dict:
    """Daily candles walking to `end` at `step` per session. step<0 = downtrend.

    Ranges are constant (high +0.12 / low -0.14 around the close), which makes
    the 14-period ATR exactly 0.26 for any |step| <= 0.14 — a fixture whose ATR
    a reader can verify by hand instead of trusting.
    """
    candles = []
    for i in range(bars):
        close = round(end - step * (bars - 1 - i), 4)
        candles.append(
            {
                "datetime": 1_700_000_000_000 + i * 86_400_000,
                "open": round(close - 0.05, 4),
                "high": round(close + 0.12, 4),
                "low": round(close - 0.14, 4),
                "close": close,
                "volume": 1000 + i,
            }
        )
    return {
        "symbol": symbol,
        "candles": candles,
        "history_ok": history_ok,
        "as_of": as_of if history_ok else None,
        "bars": len(candles),
        "note": note,
    }


def history_source(**by_symbol):
    """A fetch_daily_history stand-in. Records every symbol it was asked for.

    Records the TIMEOUT too. The re-evaluation refetch runs ahead of the
    protect lane inside RTH, so which budget it passes is a safety property,
    not a detail — and a fixture with a narrow signature would have made the
    suite go red for the wrong reason when the parameter landed. `**kw` on a
    stand-in for a real signature is the fail-open direction elsewhere; here
    the assertion is on `timeouts`, so nothing is swallowed unexamined.
    """
    seen: list = []
    timeouts: list = []
    default = by_symbol.pop("default", None)

    def fake(symbol, days=None, timeout=None):
        seen.append(str(symbol).upper())
        timeouts.append(timeout)
        h = by_symbol.get(str(symbol).upper())
        if h is None:
            h = default if default is not None else synth_history(symbol)
        out = deepcopy(h)
        out["symbol"] = str(symbol).upper()
        return out

    fake.seen = seen
    fake.timeouts = timeouts
    return fake


def never_called_history(symbol, days=None, timeout=None):
    raise AssertionError("daily history was fetched when it must not have been")


def plans_in(root: Path) -> list:
    d = root / "config" / "plans"
    return sorted(d.glob("*.json")) if d.exists() else []


class TestOffHoursPlanning(unittest.TestCase):
    """The planner proposes; it never places and never approves.

    EVERY TEST HERE FAILS ON 8bd850d IN THE SAME PLACE FIRST: that tip has no
    `fetch_daily_history` attribute at all, so `patched("fetch_daily_history",
    ...)` raises AttributeError before the body runs. The per-test note names
    the assertion that fails once the attribute exists.
    """

    ET = temple_flow_wire.ET

    def at(self, hour: int, minute: int = 0, day: int = 3) -> datetime:
        return datetime(2026, 9, day, hour, minute, tzinfo=self.ET)

    def night_book(self, **kw) -> dict:
        book = base_book(in_rth=False, armed=False, quotes_as_of="2026-09-03T20:00:00-04:00")
        book.update(kw)
        return book

    def test_planning_outside_rth_writes_a_plan_with_a_candidate(self):
        """FAILS ON 8bd850d: no config/plans/*.json is ever written."""
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            out = run_cycle(
                example_rules(),
                self.night_book(),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            files = plans_in(root)
            self.assertEqual(len(files), 1, files)
            self.assertEqual(files[0].name, "2026-09-03_2000.json")
            plan = json.loads(files[0].read_text())

            self.assertEqual(plan["candidates"], ["TF-PLAN-20260903-2000-ETHA"])
            etha = plan["symbols"]["ETHA"]
            self.assertEqual(etha["decision"], "candidate")
            self.assertTrue(all(etha["checks"].values()), etha["checks"])

            # the legible feature set, by hand: 120 closes ending 18.30 at
            # +0.038/session, quote last 18.50, constant 0.26 range.
            f = etha["features"]
            self.assertAlmostEqual(f["sma20"], 18.30 - 0.038 * 9.5, places=6)
            self.assertAlmostEqual(f["sma50"], 18.30 - 0.038 * 24.5, places=6)
            self.assertAlmostEqual(f["sma20_slope"], 0.038, places=6)
            self.assertAlmostEqual(f["sma50_slope"], 0.038, places=6)
            self.assertAlmostEqual(f["atr14"], 0.26, places=6)
            self.assertAlmostEqual(f["ret5d"], (18.30 - (18.30 - 0.038 * 5)) / (18.30 - 0.038 * 5), places=9)
            self.assertAlmostEqual(f["last_vs_cap"], 18.50 - 18.90, places=6)
            self.assertEqual(f["bars"], 120)

            # the ticket, in the exact outbox dialect, INERT
            t = etha["ticket"]
            self.assertEqual(t["status"], "proposed")
            self.assertIs(t["risk_stamped"], False)
            self.assertEqual(t["action"], "place_gtc_bracket")
            self.assertEqual(t["side"], "BUY")
            self.assertEqual(t["symbol"], "ETHA")
            self.assertEqual(t["limit"], 18.50)
            self.assertEqual(t["stop"], 17.98)  # max(rules 17.70, 18.50 - 2*0.26)
            self.assertEqual(t["qty"], 11)  # notional cap 208.90 / 18.50
            self.assertLessEqual(t["limit"], 18.90)

            v = t["validity"]
            self.assertEqual(v["planned_last"], 18.50)
            self.assertAlmostEqual(v["planned_atr"], 0.26, places=6)
            self.assertIs(v["min_sma20_over_sma50"], True)
            self.assertEqual(v["max_data_age_minutes"], 60.0)
            self.assertEqual(v["max_last"], 18.68)  # floor(18.50 * 1.01), under the cap
            self.assertIn("sma20", v["rationale"])

            # and the log said so, once per symbol
            plan_lines = [a for a in out if a.get("op") == "plan"]
            self.assertEqual([a["symbol"] for a in plan_lines], ["ETHA", "IBIT"])
            for line in plan_lines:
                self.assertIs(line["sent"], False)
                self.assertIs(line["mutated"], False)

    def test_planning_declines_when_the_trend_is_down(self):
        """FAILS ON 8bd850d: no plan file, so there is no decision to read."""
        fake = history_source(default=synth_history(end=18.30, step=-0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            run_cycle(
                example_rules(),
                self.night_book(),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            plan = json.loads(plans_in(root)[0].read_text())
            self.assertEqual(plan["candidates"], [])
            etha = plan["symbols"]["ETHA"]
            self.assertEqual(etha["decision"], "none")
            self.assertEqual(etha["reason"], "strategy_declined")
            self.assertIsNone(etha["ticket"])
            self.assertIn("trend_stack_fast_over_slow", etha["failed_checks"])
            self.assertIn("fast_sma_rising", etha["failed_checks"])
            self.assertIn("slow_sma_rising", etha["failed_checks"])

    def test_planning_never_runs_inside_rth(self):
        """FAILS ON 8bd850d only via the patched() AttributeError.

        The behaviour asserted (no plan inside RTH) is trivially true there —
        which is why the tripwire fetcher matters: this test proves the lane is
        gated on the clock, not that the lane is absent.
        """
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", never_called_history
        ):
            root = Path(tmpdir)
            out = run_cycle(
                example_rules(),
                base_book(in_rth=True, armed=True),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(11),
            )
            self.assertEqual(plans_in(root), [])
            self.assertFalse((root / "config" / "plans").exists())
            self.assertEqual([a for a in out if a.get("op") == "plan"], [])

    def test_planning_never_writes_into_the_outbox(self):
        """FAILS ON 8bd850d: the plan file it must not duplicate is absent."""
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            run_cycle(
                example_rules(),
                self.night_book(),
                live=True,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            self.assertEqual(sorted(outbox.glob("*.json")), [])
            self.assertEqual(len(plans_in(root)), 1)
            # and the proposed ticket, if a human dropped it into the outbox
            # unchanged, is still inert: the loader wants approved + stamped.
            plan = json.loads(plans_in(root)[0].read_text())
            t = plan["symbols"]["ETHA"]["ticket"]
            (outbox / (t["id"] + ".json")).write_text(json.dumps(t))
            self.assertEqual(load_outbox_tickets(root), [])

    def test_history_unproven_proposes_nothing(self):
        """FAILS ON 8bd850d: no plan file records coverage at all."""
        fake = history_source(default=synth_history(history_ok=False, note="pricehistory_http=500"))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            run_cycle(
                example_rules(),
                self.night_book(),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            plan = json.loads(plans_in(root)[0].read_text())
            self.assertEqual(plan["candidates"], [])
            self.assertEqual(plan["symbols"]["ETHA"]["reason"], "history_unproven")
            self.assertIsNone(plan["symbols"]["ETHA"]["ticket"])
            self.assertIs(plan["coverage"]["history_ok"]["ETHA"], False)

    def test_no_broker_on_the_machine_means_history_unproven(self):
        """POSITIVE CONTROL on the guard that keeps this suite off the network.

        fetch_daily_history is NOT patched here. SPIRAL_BROKER_ROOT points at a
        directory that does not exist, so _broker_auth() returns at
        broker_available() and `import requests` is never reached. If this test
        ever hangs or reports an HTTP note, the suite is talking to Schwab.

        FAILS ON 8bd850d: AttributeError, temple_flow_wire has no
        fetch_daily_history to call.
        """
        self.assertFalse(temple_flow_wire.broker_available())
        h = temple_flow_wire.fetch_daily_history("ETHA")
        self.assertIs(h["history_ok"], False)
        self.assertEqual(h["candles"], [])
        self.assertEqual(h["note"], "broker not on this machine")
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            run_cycle(
                example_rules(),
                self.night_book(),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            plan = json.loads(plans_in(root)[0].read_text())
            self.assertEqual(plan["candidates"], [])
            self.assertEqual(plan["symbols"]["ETHA"]["reason"], "history_unproven")

    def test_quotes_unproven_proposes_nothing_and_fetches_no_history(self):
        """FAILS ON 8bd850d: no plan file exists to carry the reason."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", never_called_history
        ):
            root = Path(tmpdir)
            run_cycle(
                example_rules(),
                self.night_book(quotes_ok=False),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            plan = json.loads(plans_in(root)[0].read_text())
            self.assertEqual(plan["candidates"], [])
            for sym in ("ETHA", "IBIT"):
                self.assertEqual(plan["symbols"][sym]["reason"], "quotes_unproven")
            self.assertIs(plan["coverage"]["quotes_ok"], False)

    def test_insufficient_history_is_not_the_same_fact_as_unproven(self):
        """A read that SUCCEEDED and cannot answer must not read as a failure.

        FAILS ON 8bd850d: no plan file, no distinction to make.
        """
        fake = history_source(default=synth_history(bars=30))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            run_cycle(
                example_rules(),
                self.night_book(),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            plan = json.loads(plans_in(root)[0].read_text())
            etha = plan["symbols"]["ETHA"]
            self.assertEqual(etha["reason"], "insufficient_history")
            self.assertIs(plan["coverage"]["history_ok"]["ETHA"], True)
            self.assertEqual(etha["features"]["bars"], 30)
            self.assertEqual(etha["bars_needed"], temple_flow_wire.MIN_HISTORY_BARS)

    def test_plan_write_leaves_no_temp_file(self):
        """FAILS ON 8bd850d: nothing is written, atomically or otherwise."""
        fake = history_source(default=synth_history())
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            run_cycle(
                example_rules(),
                self.night_book(),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            leftovers = sorted((root / "config" / "plans").glob("*.tmp"))
            self.assertEqual(leftovers, [])


class TestApprovePlanCli(unittest.TestCase):
    """--approve-plan is the ONLY path from a plan to the outbox.

    Offline by construction: no test here patches a broker helper because none
    is reachable. `no_network()` is still armed as the proof of that.
    """

    ET = temple_flow_wire.ET

    def at(self, hour: int, minute: int = 0, day: int = 3) -> datetime:
        return datetime(2026, 9, day, hour, minute, tzinfo=self.ET)

    def _plan(self, root: Path, now: datetime) -> Path:
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with patched("fetch_daily_history", fake):
            plan = temple_flow_wire.build_plan(
                example_rules(),
                base_book(in_rth=False, armed=False, quotes_as_of="2026-09-03T20:00:00-04:00"),
                repo_root=root,
                now=now,
            )
        path = temple_flow_wire.write_plan_file(plan, repo_root=root, now=now)
        return path

    def test_approve_copies_exactly_one_candidate_with_the_right_stamps(self):
        """FAILS ON 8bd850d: cmd_approve_plan does not exist (AttributeError)."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            plan_path = self._plan(root, self.at(20))
            rc = temple_flow_wire.cmd_approve_plan(
                str(plan_path),
                "TF-PLAN-20260903-2000-ETHA",
                repo_root=root,
                now=self.at(21),
            )
            self.assertEqual(rc, 0)
            written = sorted((root / "config" / "outbox").glob("*.json"))
            self.assertEqual(len(written), 1, written)
            self.assertEqual(written[0].name, "TF-PLAN-20260903-2000-ETHA.json")
            t = json.loads(written[0].read_text())
            self.assertEqual(t["status"], "approved")
            self.assertIs(t["risk_stamped"], True)
            self.assertEqual(t["human_approved_at"], self.at(21).isoformat())
            self.assertEqual(t["approved_from_plan"], str(plan_path))
            # the trade itself is copied verbatim, validity included
            self.assertEqual(t["symbol"], "ETHA")
            self.assertEqual(t["qty"], 11)
            self.assertEqual(t["limit"], 18.50)
            self.assertEqual(t["stop"], 17.98)
            self.assertEqual(t["validity"]["max_last"], 18.68)
            # and the loader now sees exactly this one ticket
            loaded = load_outbox_tickets(root)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["ticket"]["id"], "TF-PLAN-20260903-2000-ETHA")

    def test_approve_refuses_a_stale_plan(self):
        """A stale plan is REGENERATED, not approved.

        The window is MAX_PLAN_AGE_HOURS (24h), a parameter of its own. It
        used to be derived as max_data_age_minutes x 24, which meant tightening
        the QUOTE freshness bound silently shrank the plan-approval window.
        FAILS ON 8bd850d: cmd_approve_plan does not exist.
        """
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            plan_path = self._plan(root, self.at(20))
            rc = temple_flow_wire.cmd_approve_plan(
                str(plan_path),
                "TF-PLAN-20260903-2000-ETHA",
                repo_root=root,
                now=self.at(21, day=5),  # ~49h later
            )
            self.assertEqual(rc, 2)
            self.assertEqual(sorted((root / "config" / "outbox").glob("*.json")), [])
            # one hour inside the window still approves
            rc_ok = temple_flow_wire.cmd_approve_plan(
                str(plan_path),
                "TF-PLAN-20260903-2000-ETHA",
                repo_root=root,
                now=self.at(19, day=4),
            )
            self.assertEqual(rc_ok, 0)

    def test_approve_refuses_an_id_that_is_not_a_candidate(self):
        """FAILS ON 8bd850d: cmd_approve_plan does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            plan_path = self._plan(root, self.at(20))
            for bad in ("TF-PLAN-20260903-2000-IBIT", "TF-NOPE"):
                rc = temple_flow_wire.cmd_approve_plan(
                    str(plan_path), bad, repo_root=root, now=self.at(21)
                )
                self.assertEqual(rc, 2, bad)
            self.assertEqual(sorted((root / "config" / "outbox").glob("*.json")), [])

    def test_approve_never_clobbers_an_existing_outbox_ticket(self):
        """FAILS ON 8bd850d: cmd_approve_plan does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            plan_path = self._plan(root, self.at(20))
            tid = "TF-PLAN-20260903-2000-ETHA"
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / (tid + ".json")).write_text(json.dumps({"id": tid, "first_seen_at": "keep me"}))
            rc = temple_flow_wire.cmd_approve_plan(
                str(plan_path), tid, repo_root=root, now=self.at(21)
            )
            self.assertEqual(rc, 2)
            self.assertEqual(
                json.loads((outbox / (tid + ".json")).read_text())["first_seen_at"],
                "keep me",
            )

    def test_approve_refuses_when_validity_states_no_freshness_window(self):
        """No window is INVENTED on a money path. FAILS ON 8bd850d (no CLI)."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            plan_path = self._plan(root, self.at(20))
            plan = json.loads(plan_path.read_text())
            plan["symbols"]["ETHA"]["ticket"]["validity"].pop("max_data_age_minutes")
            plan_path.write_text(json.dumps(plan))
            rc = temple_flow_wire.cmd_approve_plan(
                str(plan_path),
                "TF-PLAN-20260903-2000-ETHA",
                repo_root=root,
                now=self.at(21),
            )
            self.assertEqual(rc, 2)
            self.assertEqual(sorted((root / "config" / "outbox").glob("*.json")), [])

    def test_approve_refuses_an_unreadable_plan(self):
        """FAILS ON 8bd850d: cmd_approve_plan does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir, no_network():
            root = Path(tmpdir)
            bad = root / "not-a-plan.json"
            bad.write_text("{ this is not json")
            self.assertEqual(
                temple_flow_wire.cmd_approve_plan(str(bad), "TF-X", repo_root=root),
                2,
            )

    def test_main_routes_the_flag_before_resolving_any_book(self):
        """The CLI must be safe from any Terminal: no book, no LIVE_OK.

        FAILS ON 8bd850d: `--approve-plan` is an unrecognised argument, so
        argparse exits 2 via SystemExit before main() returns anything.
        """
        seen: list = []

        def rec(plan_file, ticket_id, repo_root=None, now=None):
            seen.append((plan_file, ticket_id))
            return 0

        def boom_book(rules):
            raise AssertionError("--approve-plan must not resolve a book")

        with no_network(), patched("cmd_approve_plan", rec), patched(
            "resolve_book", boom_book
        ):
            rc = temple_flow_wire.main(["--approve-plan", "p.json", "TF-1"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [("p.json", "TF-1")])


class TestReevaluationWithFreshData(unittest.TestCase):
    """Anthony, 2026-09-03 11:47 EDT: a plan that did not go through when it
    was planned gets re-evaluated with fresh, time-sensitive data.

    A ticket carrying `validity` is an IDEA with a falsifier attached. The gate
    re-reads the world at execution: too-old data WAITS, a broken idea DIES.
    """

    ET = temple_flow_wire.ET

    def at(self, hour: int, minute: int = 0, day: int = 3) -> datetime:
        return datetime(2026, 9, day, hour, minute, tzinfo=self.ET)

    def validity(self, **kw) -> dict:
        v = {
            "max_last": 18.69,
            "min_sma20_over_sma50": True,
            "max_data_age_minutes": 60.0,
            "planned_last": 18.50,
            "planned_atr": 0.26,
            "rationale": "planned overnight",
        }
        v.update(kw)
        return v

    def live_book(
        self,
        last=18.50,
        read_minutes_ago=2,
        quote_minutes_ago=1,
        quote_time=_UNSET,
        **kw,
    ) -> dict:
        """A proven read at 10:00, with both freshness stamps under control.

        THE DEFAULT CARRIES A REAL SCHWAB STAMP, and that is the fix to a hole
        this fixture used to open. Its old default was quote_time=None, so the
        one green permit path in this class — test_validity_holds_and_the_
        ticket_posts — ran in the ONE configuration where the freshness gate
        could not fire: no per-symbol stamp, only the ~0-minute read clock
        answering. The Schwab stamp was exercised in the refusal direction
        only. A suite whose pass case is the gate's blind spot certifies
        nothing about the gate.

        `quote_minutes_ago` moves Schwab's clock; `quote_time=<epoch ms or ISO>`
        overrides it outright; `quote_time=None` writes an explicitly ABSENT
        stamp, which is now a refusal in its own right.
        """
        stamp = (self.at(10) - timedelta(minutes=read_minutes_ago)).isoformat()
        if quote_time is _UNSET:
            quote_time = int(
                (self.at(10) - timedelta(minutes=quote_minutes_ago)).timestamp() * 1000
            )
        book = base_book(
            in_rth=True,
            armed=True,
            quotes_as_of=stamp,
            quotes={
                "ETHA": {"last": last, "quote_time": quote_time},
                "IBIT": {"last": 45.00},
                "NVO": {"last": 45.81},
                "NOK": {"last": 10.20},
            },
        )
        book.update(kw)
        return book

    def _write(self, root: Path, t: dict) -> Path:
        outbox = root / "config" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        p = outbox / ((t.get("id") or "TF") + ".json")
        p.write_text(json.dumps(t))
        return p

    @staticmethod
    def _ticket_lines(out: list) -> list:
        return [a for a in out if a.get("op") == "outbox_ticket"]

    def _cycle(self, root, book, history, now, place=None):
        calls: list = []

        def mock_place(**kw):
            calls.append(kw)
            return {"http": 201, "order_id": "1007790000001", "error": ""}

        with recording_broker(), patched("place_gtc_bracket", place or mock_place), patched(
            "fetch_daily_history", history
        ):
            out = run_cycle(
                example_rules(),
                book,
                live=True,
                broker_note="test",
                repo_root=root,
                now=now,
            )
        return out, calls

    def test_validity_holds_and_the_ticket_posts(self):
        """FAILS ON 8bd850d: patched("fetch_daily_history") is AttributeError.

        Once that exists, pre-change the ticket would post WITHOUT ever
        re-reading the trend — this test is the permit path that proves the new
        block does not simply refuse everything.
        """
        up = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(root, self.live_book(), up, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "posted")
            self.assertIs(line["sent"], True)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["qty"], 11)
            self.assertEqual(
                line["gate"]["reevaluation"]["verdict"], "validity_holds"
            )
            self.assertEqual(up.seen, ["ETHA"])
            self.assertFalse(p.exists())

    def test_a_ticket_without_validity_behaves_exactly_as_before(self):
        """No validity key, no history fetch, no new refusal.

        FAILS ON 8bd850d: patched("fetch_daily_history") is AttributeError. The
        BEHAVIOUR asserted is the pre-change behaviour — that is the point.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write(root, ticket(qty=11))
            out, calls = self._cycle(
                root, self.live_book(), never_called_history, self.at(10)
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "posted")
            self.assertNotIn("reevaluation", line["gate"])
            self.assertEqual(len(calls), 1)

    def test_a_schwab_quote_stamp_hours_old_defers_even_on_a_fresh_read(self):
        """THE GATE CAN FIRE IN PRODUCTION, which is the whole point of it.

        The book was READ two minutes ago, so a freshness gate built on the
        read stamp alone would be inert on every daemon cycle. Schwab's own
        quote_time is three hours old — a halted symbol or a frozen feed — and
        that is what must defer.

        FAILS ON 8bd850d: patched("fetch_daily_history") is AttributeError, and
        the gate has no data-freshness check to fail.
        """
        stale_ms = int(self.at(7).timestamp() * 1000)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(
                root,
                self.live_book(read_minutes_ago=2, quote_time=stale_ms),
                never_called_history,
                self.at(10),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "data_stale_refetch_next_cycle")
            check = line["gate"]["reevaluation"]
            self.assertEqual(check["failed"], ["quote_age"])
            self.assertGreater(check["quote_age_minutes"], 60)
            self.assertEqual(calls, [])
            self.assertTrue(p.exists(), "a stale read parks the ticket, never kills it")

    def test_an_old_read_stamp_defers_too(self):
        """FAILS ON 8bd850d: no freshness check exists at all."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(
                root,
                self.live_book(read_minutes_ago=95),
                never_called_history,
                self.at(10),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "data_stale_refetch_next_cycle")
            self.assertAlmostEqual(
                line["gate"]["reevaluation"]["quote_age_minutes"], 95.0, places=1
            )
            self.assertEqual(calls, [])
            self.assertTrue(p.exists())

    def test_a_missing_schwab_stamp_defers_even_when_the_read_is_seconds_old(self):
        """THE FAIL-OPEN THIS CLASS USED TO CERTIFY AS A PASS.

        The read clock is 2 minutes old and perfectly valid. Schwab's own
        per-symbol stamp is ABSENT — the field missing from the payload, a key
        renamed, a symbol returned without quoteTime or tradeTime. Before
        2026-09-04 quote_age_minutes returned max([~2]) = ~2, the gate compared
        2 < 60, called it FRESH, and the overnight ticket posted on data whose
        age had never been measured. The inert clock was the only thing that
        answered and nothing in the log said so.

        The permit test above now runs WITH a Schwab stamp, so this is the
        configuration that used to be the only green path. It must refuse.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(
                root,
                self.live_book(read_minutes_ago=2, quote_time=None),
                never_called_history,
                self.at(10),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "data_stale_refetch_next_cycle")
            check = line["gate"]["reevaluation"]
            self.assertEqual(check["failed"], ["quote_time_unmeasured"])
            # the log says WHICH clock answered, which is the whole fix
            self.assertIs(check["quote_time_seen"], False)
            self.assertIs(check["read_stamp_seen"], True)
            self.assertLess(check["quote_age_minutes"], 60)
            self.assertEqual(calls, [], "nothing may post on unmeasured data")
            self.assertTrue(p.exists(), "unproven freshness WAITS, never dies")

    def test_an_unparseable_schwab_stamp_counts_as_unmeasured_not_as_fresh(self):
        """`quote_time_seen` is set from a PARSED age, never from key presence.

        A stamp that is present and garbage measured nothing. Reading the flag
        off `"quote_time" in q` would rebuild the same fail-open one layer in,
        so this fixture ships junk in the field and demands the same refusal as
        an absent one.
        """
        for junk in ("not-a-timestamp", 0, -5, "", 10**18):
            with self.subTest(quote_time=junk):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    self._write(root, ticket(qty=11, validity=self.validity()))
                    out, calls = self._cycle(
                        root,
                        self.live_book(quote_time=junk),
                        never_called_history,
                        self.at(10),
                    )
                    line = self._ticket_lines(out)[0]
                    self.assertEqual(line["reason"], "data_stale_refetch_next_cycle")
                    self.assertEqual(
                        line["gate"]["reevaluation"]["failed"],
                        ["quote_time_unmeasured"],
                    )
                    self.assertEqual(calls, [])

    def test_quote_freshness_reports_both_clocks_separately(self):
        """The unit under the gate, in isolation: which stamp answered."""
        book = self.live_book(read_minutes_ago=2, quote_minutes_ago=40)
        f = temple_flow_wire.quote_freshness(book, "ETHA", self.at(10))
        self.assertIs(f["read_stamp_seen"], True)
        self.assertIs(f["quote_time_seen"], True)
        self.assertAlmostEqual(f["read_stamp_age"], 2.0, places=1)
        self.assertAlmostEqual(f["quote_time_age"], 40.0, places=1)
        # the OLDER clock wins
        self.assertAlmostEqual(f["age_minutes"], 40.0, places=1)
        # a future stamp is skew, clamped to 0, not folded through abs()
        ahead = self.live_book(read_minutes_ago=-30, quote_minutes_ago=-30)
        self.assertEqual(
            temple_flow_wire.quote_freshness(ahead, "ETHA", self.at(10))["age_minutes"],
            0.0,
        )
        # nothing readable at all is None, on both legs
        blind = {"quotes": {"ETHA": {"last": 18.5}}}
        f_blind = temple_flow_wire.quote_freshness(blind, "ETHA", self.at(10))
        self.assertIsNone(f_blind["age_minutes"])
        self.assertIs(f_blind["quote_time_seen"], False)
        self.assertIs(f_blind["read_stamp_seen"], False)

    def test_a_book_that_never_says_when_defers(self):
        """Absence of a freshness stamp is not permission.

        FAILS ON 8bd850d: no freshness check exists at all.
        """
        book = self.live_book()
        book.pop("quotes_as_of")
        book["quotes"]["ETHA"].pop("quote_time")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(root, book, never_called_history, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["reason"], "data_stale_refetch_next_cycle")
            check = line["gate"]["reevaluation"]
            self.assertIsNone(check["quote_age_minutes"])
            # BOTH clocks silent, and the label says the Schwab one is the
            # missing measurement — the read clock being absent too is not
            # what makes this a refusal.
            self.assertEqual(check["failed"], ["quote_time_unmeasured"])
            self.assertIs(check["quote_time_seen"], False)
            self.assertIs(check["read_stamp_seen"], False)
            self.assertEqual(calls, [])
            self.assertTrue(p.exists())

    def test_last_above_max_last_is_terminal_and_carries_both_numbers(self):
        """The market ran past the trade a human approved. Terminal, with
        planned-vs-now in the gate detail and the log line.

        FAILS ON 8bd850d: patched("fetch_daily_history") is AttributeError; the
        pre-change gate would POST at 18.80 because 18.80 is still under the
        18.90 cap — the idea, not the cap, is what moved.
        """
        up = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(root, self.live_book(last=18.80), up, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "refused")
            self.assertEqual(line["reason"], "idea_stale_reevaluated")
            check = line["gate"]["reevaluation"]
            self.assertEqual(check["failed"], ["last_above_max_last"])
            self.assertEqual(check["planned_last"], 18.50)
            self.assertEqual(check["last_now"], 18.80)
            self.assertEqual(check["max_last"], 18.69)
            self.assertEqual(calls, [])
            self.assertFalse(p.exists())
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    def test_a_gap_down_through_the_planned_stop_never_posts(self):
        """THE ONE-SIDED BAND, AND THE WORST OUTCOME THIS WIRE CAN PRODUCE.

        Shipped example numbers: plan last 18.50, stop 17.98 (= last - 2*ATR
        0.26), max_last 18.68. ETHA opens at 17.60 — a ~2.9% overnight gap,
        which is ORDINARY for a crypto ETF, not a tail. Before 2026-09-04 that
        price passed every check in this block: under max_last, under the
        18.90 cap, and one session barely disturbs a 20/50 SMA stack. The
        bracket POSTed with its child stop already through the market, and
        BOTH of Schwab's possible answers are bad:

          accepted -> the parent LIMIT BUY 18.50 is marketable at 17.60, fills
            at once, and the child STOP SELL 17.98 triggers immediately: a
            position opened and closed in a shape no human approved;
          rejected -> the parent still fills and the account is long 11 ETHA
            with NO protective stop, which is the outcome the whole wire
            exists to prevent.

        The trend fixture here is a healthy uptrend on purpose: this must
        refuse on price alone, not be rescued by the SMA check downstream.
        """
        up = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, stop=17.98, validity=self.validity()))
            out, calls = self._cycle(root, self.live_book(last=17.60), up, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "refused")
            self.assertEqual(line["reason"], "idea_stale_reevaluated")
            check = line["gate"]["reevaluation"]
            self.assertEqual(check["failed"], ["last_at_or_below_stop"])
            self.assertEqual(check["last_now"], 17.60)
            self.assertEqual(check["stop"], 17.98)
            self.assertEqual(calls, [], "no bracket may be posted through its own stop")
            self.assertFalse(p.exists())
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())
            # and it refused on PRICE, before spending a history refetch
            self.assertEqual(up.seen, [])

    def test_last_exactly_at_the_stop_refuses_too(self):
        """The boundary is <=, not <. A fill at the stop is a stop-out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write(root, ticket(qty=11, stop=17.98, validity=self.validity()))
            out, calls = self._cycle(
                root, self.live_book(last=17.98), never_called_history, self.at(10)
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["reason"], "idea_stale_reevaluated")
            self.assertEqual(
                line["gate"]["reevaluation"]["failed"], ["last_at_or_below_stop"]
            )
            self.assertEqual(calls, [])

    def test_min_last_is_the_symmetric_floor_of_the_drift_band(self):
        """A gap down that clears the stop but guts the plan's risk shape.

        18.20 is above the 17.98 stop, so the hard refusal above does not fire
        — but the bracket would fill ~0.22 from its stop where it was sized for
        0.52, i.e. a stop ordinary noise takes out. `min_last` is the mirror of
        `max_last`, derived from the SAME max_drift_pct, so the band is one
        number in the rules file rather than two.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(
                root,
                ticket(
                    qty=11,
                    stop=17.98,
                    validity=self.validity(min_last=18.32),
                ),
            )
            out, calls = self._cycle(
                root, self.live_book(last=18.20), never_called_history, self.at(10)
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "refused")
            self.assertEqual(line["reason"], "idea_stale_reevaluated")
            check = line["gate"]["reevaluation"]
            self.assertEqual(check["failed"], ["last_below_min_last"])
            self.assertEqual(check["min_last"], 18.32)
            self.assertEqual(calls, [])
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    def test_a_ticket_with_no_min_last_keeps_only_the_stop_floor(self):
        """`min_last` is OPTIONAL. A hand-written ticket without one still
        posts at a price the band would have excluded — the compatibility
        contract in AWAY_MODE.md — while the stop floor still holds."""
        up = history_source(default=synth_history(end=18.30, step=0.038))
        v = self.validity()
        v.pop("min_last", None)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write(root, ticket(qty=11, stop=17.98, validity=v))
            out, calls = self._cycle(root, self.live_book(last=18.20), up, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "posted")
            self.assertIsNone(line["gate"]["reevaluation"]["min_last"])
            self.assertEqual(len(calls), 1)

    def test_the_planner_stamps_min_last_symmetrically_with_max_last(self):
        """THE VALVE IS CONNECTED. A `min_last` the gate honours and the
        planner never writes would be a config that assumes a merge — the
        exact shape this repo keeps finding. Both halves ship together.
        """
        up = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", up
        ):
            root = Path(tmpdir)
            night = base_book(
                in_rth=False, armed=False, quotes_as_of="2026-09-03T20:00:00-04:00"
            )
            run_cycle(
                example_rules(),
                night,
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20, day=2),
            )
            plan = json.loads(plans_in(root)[0].read_text())
            v = plan["symbols"]["ETHA"]["ticket"]["validity"]
            drift = float(plan["strategy_params"]["max_drift_pct"])
            last = float(plan["symbols"]["ETHA"]["features"]["last"])
            self.assertEqual(
                v["max_last"],
                min(temple_flow_strategy.floor_to_tick(last * (1 + drift)), 18.90),
            )
            self.assertEqual(
                v["min_last"], temple_flow_strategy.ceil_to_tick(last * (1 - drift))
            )
            # floored max, CEILED min: rounding never widens the band
            self.assertLess(v["min_last"], last)
            self.assertGreater(v["max_last"], last)
            self.assertGreater(v["min_last"], plan["symbols"]["ETHA"]["ticket"]["stop"])

    def test_a_trend_that_flipped_overnight_is_terminal(self):
        """FAILS ON 8bd850d: the gate never refetches history, so a flipped
        trend posts the overnight idea unchanged."""
        down = history_source(default=synth_history(end=18.30, step=-0.038))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(root, self.live_book(), down, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "refused")
            self.assertEqual(line["reason"], "idea_stale_reevaluated")
            check = line["gate"]["reevaluation"]
            self.assertEqual(check["failed"], ["trend_flipped_sma20_under_sma50"])
            self.assertGreater(check["sma50_now"], check["sma20_now"])
            self.assertEqual(calls, [])
            self.assertTrue((root / "config" / "outbox" / "failed" / p.name).exists())

    def test_a_failed_history_refetch_defers_rather_than_deciding_blind(self):
        """FAILS ON 8bd850d: patched("fetch_daily_history") is AttributeError."""
        broken = history_source(default=synth_history(history_ok=False, note="pricehistory_http=503"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(root, self.live_book(), broken, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "history_unproven_refetch_next_cycle")
            self.assertEqual(
                line["gate"]["reevaluation"]["failed"], ["history_refetch_failed"]
            )
            self.assertEqual(calls, [])
            self.assertTrue(p.exists())

    def test_too_few_bars_to_recompute_the_trend_also_defers(self):
        """A read that succeeded and cannot answer is the same class as a read
        that failed: WAIT, never decide blind.

        FAILS ON 8bd850d: patched("fetch_daily_history") is AttributeError.
        """
        thin = history_source(default=synth_history(bars=10))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(root, self.live_book(), thin, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "history_unproven_refetch_next_cycle")
            self.assertEqual(
                line["gate"]["reevaluation"]["failed"],
                ["insufficient_history_for_trend"],
            )
            self.assertEqual(calls, [])
            self.assertTrue(p.exists())

    def test_an_unproven_quotes_leg_defers_a_validity_ticket(self):
        """FAILS ON 8bd850d: the gate has no validity path, so a blind quotes
        leg lets a validity ticket through on its overnight numbers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p = self._write(root, ticket(qty=11, validity=self.validity()))
            out, calls = self._cycle(
                root,
                self.live_book(quotes_ok=False),
                never_called_history,
                self.at(10),
            )
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "deferred")
            self.assertEqual(line["reason"], "quotes_unproven")
            self.assertEqual(calls, [])
            self.assertTrue(p.exists())

    def test_the_plan_to_outbox_to_execution_loop_end_to_end(self):
        """plan -> approve -> re-evaluate -> post, with no hand-written ticket.

        FAILS ON 8bd850d at the first step: there is no planner to produce a
        plan file, and no --approve-plan to consume it.
        """
        up = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            night = base_book(
                in_rth=False, armed=False, quotes_as_of="2026-09-03T20:00:00-04:00"
            )
            with no_network(), patched("fetch_daily_history", up):
                run_cycle(
                    example_rules(),
                    night,
                    live=True,
                    broker_note="test",
                    repo_root=root,
                    now=self.at(20, day=2),
                )
            plan_path = plans_in(root)[0]
            tid = json.loads(plan_path.read_text())["candidates"][0]
            self.assertEqual(
                temple_flow_wire.cmd_approve_plan(
                    str(plan_path), tid, repo_root=root, now=self.at(8)
                ),
                0,
            )
            out, calls = self._cycle(root, self.live_book(), up, self.at(10))
            line = self._ticket_lines(out)[0]
            self.assertEqual(line["execute"], "posted")
            self.assertEqual(line["ticket_id"], tid)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["symbol"], "ETHA")
            self.assertEqual(calls[0]["limit"], 18.50)
            self.assertEqual(calls[0]["stop"], 17.98)
            done = root / "config" / "outbox" / "done" / (tid + ".json")
            self.assertTrue(done.exists())
            self.assertEqual(
                json.loads(done.read_text())["schwab_order_id"], "1007790000001"
            )


class TestNewRefusalsAreClassified(unittest.TestCase):
    """Redundant with the AST tripwire ON PURPOSE.

    The tripwire proves nothing is unclassified; this names the four reasons
    added on 2026-09-04 and pins WHICH side each landed on, so a later edit
    that flips one has to change a test that says why.
    """

    def test_the_four_new_reasons_have_the_dispositions_they_were_given(self):
        for wait in (
            "quotes_unproven",
            "data_stale_refetch_next_cycle",
            "history_unproven_refetch_next_cycle",
        ):
            self.assertIn(wait, temple_flow_wire.WAIT_REFUSALS, wait)
            self.assertTrue(temple_flow_wire.refusal_is_wait(wait), wait)
        self.assertIn("idea_stale_reevaluated", temple_flow_wire.TERMINAL_REFUSALS)
        self.assertFalse(temple_flow_wire.refusal_is_wait("idea_stale_reevaluated"))


class TestFeatureMathOnNonLinearData(unittest.TestCase):
    """The feature math, checked against numbers computed BY HAND.

    WHY THIS CLASS EXISTS, and it is the point: `synth_history` is a perfectly
    linear ramp, on which the SMA slope equals the per-session step exactly —
    so `assertAlmostEqual(sma20_slope, 0.038)` passes whether the lookback
    window is right or off by a bar. A linear fixture CANNOT distinguish a
    correct slope from an off-by-one one, and `fast_sma_rising` /
    `slow_sma_rising` gate which trades get proposed at all.

    The series below rises for 100 sessions and then goes FLAT for 5. On it the
    two slopes differ from each other (0.085 vs 0.094) and from the underlying
    step (0.10), so an off-by-one window changes the number and this test says
    so. Worked by hand, and the arithmetic is in the comments so a reader can
    redo it without running anything.

    FAILS ON 8bd850d: temple_flow_wire has no sma / sma_slope / atr /
    window_return — AttributeError on the first call.
    """

    #: 100 rising sessions (10.00 + 0.10 * i), then 5 flat at 19.90.
    RAMP_THEN_FLAT = [round(10.0 + 0.10 * i, 10) for i in range(100)] + [19.9] * 5

    def test_sma_is_the_mean_of_the_last_n(self):
        # closes[85:105] = 15 rising values 18.50..19.90 (sum 288.00) + 5 x 19.90
        #                = 387.50 / 20 = 19.375
        self.assertAlmostEqual(
            temple_flow_wire.sma(self.RAMP_THEN_FLAT, 20), 19.375, places=9
        )
        # closes[55:105] = 45 rising values 15.50..19.90 (sum 796.50) + 5 x 19.90
        #                = 896.00 / 50 = 17.92
        self.assertAlmostEqual(
            temple_flow_wire.sma(self.RAMP_THEN_FLAT, 50), 17.92, places=9
        )

    def test_slope_on_a_non_linear_series_matches_hand_computation(self):
        """THE DISCRIMINATING TEST. A ramp cannot catch an off-by-one; this can.

        sma20 five sessions ago = mean(closes[80:100]) = mean(18.00..19.90)
                                = 18.95, so slope20 = (19.375 - 18.95) / 5
                                = 0.085
        sma50 five sessions ago = mean(closes[50:100]) = mean(15.00..19.90)
                                = 17.45, so slope50 = (17.92 - 17.45) / 5
                                = 0.094

        Both positive (the trend is still up), both DIFFERENT from each other
        and from the 0.10 step. An off-by-one on the lookback window would read
        0.066 for the fast slope, which this assertion rejects.
        """
        self.assertAlmostEqual(
            temple_flow_wire.sma_slope(self.RAMP_THEN_FLAT, 20, 5), 0.085, places=9
        )
        self.assertAlmostEqual(
            temple_flow_wire.sma_slope(self.RAMP_THEN_FLAT, 50, 5), 0.094, places=9
        )
        # and the flat tail does not make the slow SMA look flat: a 50-day
        # average is still climbing five sessions after price stopped.
        self.assertGreater(
            temple_flow_wire.sma_slope(self.RAMP_THEN_FLAT, 50, 5),
            temple_flow_wire.sma_slope(self.RAMP_THEN_FLAT, 20, 5),
        )

    def test_a_rolled_over_series_reads_as_falling(self):
        """Positive control on sign: the same shape, rolled over, goes negative."""
        rolled = self.RAMP_THEN_FLAT[:100] + [19.9 - 0.20 * i for i in range(1, 21)]
        self.assertLess(temple_flow_wire.sma_slope(rolled, 20, 5), 0)

    def test_short_windows_return_none_rather_than_a_number(self):
        """Fail closed: an unknown feature must never look like a passing one."""
        self.assertIsNone(temple_flow_wire.sma([1.0] * 19, 20))
        self.assertIsNone(temple_flow_wire.sma_slope([1.0] * 24, 20, 5))
        self.assertIsNone(temple_flow_wire.atr([{"high": 1, "low": 1, "close": 1}] * 14, 14))
        self.assertIsNone(temple_flow_wire.window_return([1.0] * 5, 5))

    def test_atr_is_the_simple_mean_of_true_range(self):
        """Hand-computed on a widening range. Candle i: close 10.00, low 10.00,
        high 10.00 + (i+1)/100. Every TR is therefore (i+1)/100, and the last
        14 (i = 1..14) sum to 1.19, so ATR14 = 1.19 / 14 = 0.085.
        """
        candles = [
            {"open": 10.0, "high": round(10.0 + (i + 1) / 100.0, 4), "low": 10.0, "close": 10.0}
            for i in range(15)
        ]
        self.assertAlmostEqual(temple_flow_wire.atr(candles, 14), 0.085, places=9)

    def test_atr_refuses_a_partial_bar_rather_than_averaging_around_it(self):
        candles = [
            {"open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0} for _ in range(15)
        ]
        candles[-2] = {"open": 10.0, "high": None, "low": 9.9, "close": 10.0}
        self.assertIsNone(temple_flow_wire.atr(candles, 14))

    def test_window_return_reads_closes_not_the_live_quote(self):
        self.assertAlmostEqual(
            temple_flow_wire.window_return([10.0, 11.0, 12.0, 13.0, 14.0, 15.0], 5),
            0.5,
            places=9,
        )

    def test_the_planner_sees_the_same_numbers(self):
        """End to end: the same series through fetch_daily_history -> features."""
        candles = [
            {
                "datetime": 1_700_000_000_000 + i * 86_400_000,
                "open": c,
                "high": c + 0.12,
                "low": c - 0.14,
                "close": c,
                "volume": 1000,
            }
            for i, c in enumerate(self.RAMP_THEN_FLAT)
        ]
        history = {
            "symbol": "ETHA",
            "candles": candles,
            "history_ok": True,
            "as_of": "2026-09-03T20:00:00-04:00",
            "bars": len(candles),
            "note": "hand-computed",
        }
        book = base_book(
            in_rth=False,
            armed=False,
            quotes_as_of="2026-09-03T20:00:00-04:00",
            quotes={"ETHA": {"last": 19.90}, "IBIT": {"last": 45.0}},
        )
        f = temple_flow_wire.compute_features("ETHA", book, history, example_rules())
        self.assertAlmostEqual(f["sma20"], 19.375, places=9)
        self.assertAlmostEqual(f["sma50"], 17.92, places=9)
        self.assertAlmostEqual(f["sma20_slope"], 0.085, places=9)
        self.assertAlmostEqual(f["sma50_slope"], 0.094, places=9)
        self.assertEqual(f["bars"], 105)
        # 19.90 against an 18.90 cap: through the cap, so no candidate even
        # though every trend condition holds.
        checks = temple_flow_strategy.check_conditions("ETHA", f, example_rules())
        self.assertTrue(checks["trend_stack_fast_over_slow"])
        self.assertTrue(checks["fast_sma_rising"])
        self.assertTrue(checks["slow_sma_rising"])
        self.assertFalse(checks["last_at_or_under_cap"])
        self.assertIsNone(temple_flow_strategy.evaluate("ETHA", f, example_rules()))


class TestTheSuiteCannotReachTheBroker(unittest.TestCase):
    """THE OFFLINE PIN, ASSERTED RATHER THAN TRUSTED TO AN OPERATOR.

    Rule 2 at the top of this file says no code path may reach `requests`. Until
    2026-09-04 that rule was enforced by (a) `no_network()`, which patches the
    two ORDER helpers only, and (b) a `SPIRAL_BROKER_ROOT=/nonexistent` pin that
    existed in three PROSE comments and in nothing executable — no Makefile, no
    CI, no conftest. On the Studio, where ~/spiral-broker exists, running this
    file plainly would have let the unpatched read path in
    test_no_broker_on_the_machine_means_history_unproven do a real OAuth
    refresh and a real /marketdata/v1/pricehistory GET against the live
    account.

    The module now force-sets the variable before importing the wire. This
    class is the alarm on that line: delete it and these tests say so.
    """

    def test_broker_root_is_pinned_away_from_any_real_broker(self):
        self.assertEqual(os.environ.get("SPIRAL_BROKER_ROOT"), "/nonexistent")
        self.assertEqual(str(temple_flow_wire.BROKER_ROOT), "/nonexistent")
        self.assertFalse(temple_flow_wire.BROKER_ROOT.exists())

    def test_broker_available_is_false_so_every_read_helper_short_circuits(self):
        """_broker_auth returns at this guard, before `import requests`."""
        self.assertFalse(temple_flow_wire.broker_available())
        auth = temple_flow_wire._broker_auth()
        self.assertIs(auth["ok"], False)
        self.assertEqual(auth["note"], "broker not on this machine")

    def test_the_pin_survives_a_hostile_environment(self):
        """setdefault would NOT have been enough, and this is the receipt.

        The launchd plist exports SPIRAL_BROKER_ROOT=/Users/tony_studio/
        spiral-broker; any shell that inherited the daemon's environment would
        have defeated `os.environ.setdefault`. The module force-sets, so the
        value that reaches BROKER_ROOT is the pin no matter what was exported.
        """
        self.assertNotIn("spiral-broker", str(temple_flow_wire.BROKER_ROOT))


class TestReviewFixes20260904(unittest.TestCase):
    """The suggestion-tier fixes from the 2026-09-04 review, each pinned."""

    ET = temple_flow_wire.ET

    def at(self, hour: int, minute: int = 0, day: int = 3) -> datetime:
        return datetime(2026, 9, day, hour, minute, tzinfo=self.ET)

    def night_book(self, **kw) -> dict:
        book = base_book(
            in_rth=False, armed=False, quotes_as_of="2026-09-03T20:00:00-04:00"
        )
        book.update(kw)
        return book

    # --- suggestion 1: the planner's own fail-open -------------------------

    def test_an_unproven_orders_leg_proposes_nothing(self):
        """THE `no_open_exposure` FAIL-OPEN, one lane over from blocker 1.

        With orders_ok False, compute_features sets has_working_entry=False
        (existing_entry is only consulted when the leg is proven), so
        check_conditions computed no_open_exposure=True — the plan file
        asserting "nothing is open on this symbol" on a cycle where the daemon
        could not look. No wrong order could post through it; the cost was a
        false statement in the document a human approves ON.
        """
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            run_cycle(
                example_rules(),
                self.night_book(orders_ok=False),
                live=False,
                broker_note="test",
                repo_root=root,
                now=self.at(20),
            )
            plan = json.loads(plans_in(root)[0].read_text())
            self.assertEqual(plan["candidates"], [])
            self.assertEqual(plan["symbols"]["ETHA"]["reason"], "orders_unproven")
            self.assertIsNone(plan["symbols"]["ETHA"]["ticket"])
            self.assertIs(plan["coverage"]["orders_ok"], False)
            # and it refused BEFORE spending a history call on a blind book
            self.assertEqual(fake.seen, [])

    # --- suggestion 7: a saturated risk box proposes nothing ---------------

    def test_a_blocked_risk_box_proposes_nothing(self):
        """max_opens is not day-scoped, so a saturated box is not a state that
        tomorrow clears. A candidate that cannot execute today or tomorrow does
        not belong in front of the human."""
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        rules = example_rules()
        rules.setdefault("risk", {})["max_opens"] = 1
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            plan = temple_flow_wire.build_plan(
                rules, self.night_book(), repo_root=root, now=self.at(20)
            )
            self.assertEqual(plan["candidates"], [])
            self.assertEqual(plan["symbols"]["ETHA"]["reason"], "risk_box_blocked")
            self.assertIs(plan["risk_box"]["ok"], False)
            self.assertTrue(plan["symbols"]["ETHA"]["risk_box"])
            self.assertEqual(fake.seen, [])

    # --- suggestion 2: the re-evaluation refetch does not hold the lane ----

    def test_the_reevaluation_refetch_uses_the_short_timeout(self):
        """That refetch runs inside RTH and BEFORE plan_actions in run_cycle,
        so a hung Schwab read there delays a PROTECT stop. It gets a
        single-digit budget; the planner keeps the long one."""
        self.assertLess(temple_flow_wire.HISTORY_TIMEOUT_REEVAL_S, 10)
        self.assertGreater(temple_flow_wire.HISTORY_TIMEOUT_S, 10)
        up = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outbox = root / "config" / "outbox"
            outbox.mkdir(parents=True)
            t = ticket(
                qty=11,
                stop=17.98,
                validity={
                    "max_last": 18.69,
                    "min_sma20_over_sma50": True,
                    "max_data_age_minutes": 60.0,
                },
            )
            (outbox / (t["id"] + ".json")).write_text(json.dumps(t))
            book = base_book(
                in_rth=True,
                armed=True,
                quotes_as_of=(self.at(10) - timedelta(minutes=2)).isoformat(),
                quotes={
                    "ETHA": {
                        "last": 18.50,
                        "quote_time": int(self.at(10).timestamp() * 1000),
                    },
                    "IBIT": {"last": 45.0},
                    "NVO": {"last": 45.81},
                    "NOK": {"last": 10.20},
                },
            )
            with recording_broker(), patched(
                "place_gtc_bracket",
                lambda **kw: {"http": 201, "order_id": "X", "error": ""},
            ), patched("fetch_daily_history", up):
                run_cycle(
                    example_rules(),
                    book,
                    live=True,
                    broker_note="test",
                    repo_root=root,
                    now=self.at(10),
                )
            self.assertEqual(
                up.timeouts, [temple_flow_wire.HISTORY_TIMEOUT_REEVAL_S]
            )

    def test_the_planner_keeps_the_long_timeout(self):
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            temple_flow_wire.build_plan(
                example_rules(), self.night_book(), repo_root=root, now=self.at(20)
            )
            # one call per non-protect universe symbol, each taking the
            # default (the planner passes no timeout, so it gets the long one)
            self.assertEqual(fake.seen, ["ETHA", "IBIT"])
            self.assertEqual(fake.timeouts, [None, None])

    # --- suggestion 3: the two windows are decoupled -----------------------

    def test_tightening_the_quote_bound_does_not_shrink_the_plan_window(self):
        """The coupling ran BACKWARDS: max_data_age_minutes x 24 meant that
        tightening quote freshness from 60 to 15 minutes — a safety tightening
        — silently cut the approval window from 24h to 6h, so a 20:00 plan
        could not be approved at 07:00."""
        self.assertFalse(hasattr(temple_flow_wire, "PLAN_STALE_MULTIPLIER"))
        self.assertEqual(temple_flow_wire.MAX_PLAN_AGE_HOURS, 24.0)
        rules = example_rules()
        rules.setdefault("strategy", {})["max_data_age_minutes"] = 15.0
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            plan = temple_flow_wire.build_plan(
                rules, self.night_book(), repo_root=root, now=self.at(20, day=2)
            )
            path = temple_flow_wire.write_plan_file(
                plan, repo_root=root, now=self.at(20, day=2)
            )
            tid = plan["candidates"][0]
            self.assertEqual(
                plan["symbols"]["ETHA"]["ticket"]["validity"][
                    "max_data_age_minutes"
                ],
                15.0,
            )
            # 11 hours later: inside the 24h plan window, far outside 15min x 24
            rc = temple_flow_wire.cmd_approve_plan(
                str(path), tid, repo_root=root, now=self.at(7, day=3)
            )
            self.assertEqual(rc, 0, "a tighter QUOTE bound must not bar approval")

    # --- suggestion 4: an approved ticket has a shelf life -----------------

    def test_approval_stamps_an_expires_at_at_the_next_session_close(self):
        """Before this, an approved ticket was bounded by PRICE and TREND only,
        so an idea approved Monday could post Thursday if the market happened
        back into the band. expires_at is already enforced terminally as
        `ticket_expired`, so this is stamping, not new machinery."""
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            plan = temple_flow_wire.build_plan(
                example_rules(), self.night_book(), repo_root=root, now=self.at(20)
            )
            path = temple_flow_wire.write_plan_file(
                plan, repo_root=root, now=self.at(20)
            )
            tid = plan["candidates"][0]
            # approved Thursday 21:00 -> Friday's 16:00 close
            self.assertEqual(
                temple_flow_wire.cmd_approve_plan(
                    str(path), tid, repo_root=root, now=self.at(21)
                ),
                0,
            )
            t = json.loads((root / "config" / "outbox" / (tid + ".json")).read_text())
            self.assertEqual(t["expires_at"], self.at(16, day=4).isoformat())
            # and the wire already treats that as terminal
            reason, _ = temple_flow_wire.ticket_wait_bounds_refusal(
                t, example_rules(), self.at(17, day=4)
            )
            self.assertEqual(reason, "ticket_expired")
            self.assertNotIn("ticket_expired", temple_flow_wire.WAIT_REFUSALS)

    def test_a_hand_set_expires_at_is_not_overwritten(self):
        """A deadline a human already wrote is the human's call."""
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            plan = temple_flow_wire.build_plan(
                example_rules(), self.night_book(), repo_root=root, now=self.at(20)
            )
            tid = plan["candidates"][0]
            plan["symbols"]["ETHA"]["ticket"]["expires_at"] = "2026-09-30T16:00:00"
            path = temple_flow_wire.write_plan_file(
                plan, repo_root=root, now=self.at(20)
            )
            temple_flow_wire.cmd_approve_plan(
                str(path), tid, repo_root=root, now=self.at(21)
            )
            t = json.loads((root / "config" / "outbox" / (tid + ".json")).read_text())
            self.assertEqual(t["expires_at"], "2026-09-30T16:00:00")

    def test_session_close_after_skips_the_weekend(self):
        cases = {
            # Thu 08:00 -> today's close; Thu 16:30 -> Friday
            self.at(8, day=3): self.at(16, day=3),
            self.at(16, 30, day=3): self.at(16, day=4),
            # Fri after the close, Sat and Sun all land on Monday
            self.at(16, 30, day=4): self.at(16, day=7),
            self.at(10, day=5): self.at(16, day=7),
            self.at(21, day=6): self.at(16, day=7),
        }
        for when, want in cases.items():
            with self.subTest(when=when.isoformat()):
                self.assertEqual(temple_flow_wire.session_close_after(when, 1), want)
        # never in the past, whatever the input
        for when in cases:
            self.assertGreater(temple_flow_wire.session_close_after(when, 1), when)

    # --- suggestion 8: an argv id must not become a path -------------------

    def test_a_ticket_id_carrying_a_path_separator_is_refused(self):
        """The id is interpolated into config/outbox/<id>.json. Generated ids
        cannot carry a separator; a hand-edited plan can."""
        fake = history_source(default=synth_history(end=18.30, step=0.038))
        with tempfile.TemporaryDirectory() as tmpdir, no_network(), patched(
            "fetch_daily_history", fake
        ):
            root = Path(tmpdir)
            plan = temple_flow_wire.build_plan(
                example_rules(), self.night_book(), repo_root=root, now=self.at(20)
            )
            escape = "../../../../tmp/tf-escape"
            plan["symbols"]["ETHA"]["ticket"]["id"] = escape
            plan["candidates"] = [escape]
            path = temple_flow_wire.write_plan_file(
                plan, repo_root=root, now=self.at(20)
            )
            rc = temple_flow_wire.cmd_approve_plan(
                str(path), escape, repo_root=root, now=self.at(21)
            )
            self.assertEqual(rc, 2)
            self.assertFalse(Path("/tmp/tf-escape.json").exists())
            self.assertEqual(sorted((root / "config" / "outbox").glob("*.json")), [])

    def test_the_generated_id_shape_still_approves(self):
        """The charset check must not exclude anything the planner writes."""
        self.assertTrue(
            temple_flow_wire._SAFE_TICKET_ID.match("TF-PLAN-20260903-2000-ETHA")
        )
        for bad in ("../x", "a/b", "", ".", "..", "/abs", "x\x00y"):
            self.assertIsNone(temple_flow_wire._SAFE_TICKET_ID.match(bad), bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
