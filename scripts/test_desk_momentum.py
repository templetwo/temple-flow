#!/usr/bin/env python3
"""Refusal directions for the desk momentum module.

Every test that ends in an approval, an arm, or a fillable price has a twin
that must refuse. A green run of only the happy path is how the last pack
shipped flags nothing called.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import desk_momentum as dm

ET = ZoneInfo("America/New_York")


def at(hour: int, minute: int, day: int = 29) -> datetime:
    # 2026-09-29 is a Tuesday.
    return datetime(2026, 9, day, hour, minute, tzinfo=ET)


def book(**over) -> dict:
    base = {
        "source": "schwab_read",
        "quotes_ok": True,
        "orders_ok": True,
        "equity": 606.0,
        "cash": 443.0,
        "sod_equity": 605.0,
        "day_pnl": 1.0,
        "peak_equity": 612.0,
        "positions": [],
        "orders": [],
    }
    base.update(over)
    return base


def grants_file(root: Path, **over) -> None:
    body = {
        "desk_may_approve_risk_pass": True,
        "auto_arm_mv_session": True,
        "auto_disarm_mv_session": True,
        "carry_reprice": True,
    }
    body.update(over)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "standing_grants.json").write_text(json.dumps(body))


def ticket(**over) -> dict:
    base = {
        "id": "TF-20260929-01",
        "action": "place_gtc_bracket",
        "symbol": "ETHA",
        "side": "BUY",
        "stop_side": "SELL",
        "qty": 1,
        "limit": 19.70,
        "stop": 18.40,
        "risk_verdict": "PASS",
        "status": "proposed",
        "risk_stamped": False,
    }
    base.update(over)
    return base


class GrantsClosedByDefault(unittest.TestCase):
    def test_missing_file_is_revoked(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = dm.load_grants(Path(tmp))
        self.assertTrue(g["revoked"])
        self.assertFalse(g["desk_may_approve_risk_pass"])
        self.assertEqual(g["reason"], "grants_file_missing")

    def test_revoke_phrase_closes_approval_and_keeps_disarm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grants_file(root, revoke="desk may not approve")
            g = dm.load_grants(root)
        self.assertTrue(g["revoked"])
        self.assertTrue(g["auto_disarm_mv_session"])
        self.assertFalse(g["auto_arm_mv_session"])

    def test_unreadable_file_is_revoked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "standing_grants.json").write_text("{")
            g = dm.load_grants(root)
        self.assertTrue(g["revoked"])
        self.assertIn("grants_unreadable", g["reason"])


class ApprovalTaps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        grants_file(self.root)
        self.grants = dm.load_grants(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pass_approves_itself(self):
        out = dm.approve_ticket(ticket(), self.grants, at(9, 30))
        self.assertTrue(out["acted"])
        self.assertEqual(out["ticket"]["approved_by"], "desk_lead")
        self.assertTrue(out["ticket"]["risk_stamped"])
        self.assertEqual(out["ticket"]["status"], "approved")

    def test_veto_never_approves(self):
        out = dm.approve_ticket(ticket(risk_verdict="VETO"), self.grants, at(9, 30))
        self.assertFalse(out["acted"])
        self.assertEqual(out["reason"], "risk_veto")
        self.assertNotEqual(out["ticket"].get("status"), "approved")

    def test_missing_verdict_does_not_approve(self):
        raw = ticket()
        raw.pop("risk_verdict")
        out = dm.approve_ticket(raw, self.grants, at(9, 30))
        self.assertFalse(out["acted"])

    def test_revoked_grant_blocks_a_pass(self):
        grants_file(self.root, revoke="desk may not approve")
        g = dm.load_grants(self.root)
        out = dm.approve_ticket(ticket(), g, at(9, 30))
        self.assertFalse(out["acted"])
        self.assertEqual(out["reason"], "grants_revoked")

    def test_reprice_down_keeps_approval(self):
        raw = ticket(
            risk_verdict=None,
            limit=19.40,
            carries_approval={"limit": 19.70, "stop": 18.40, "qty": 1, "symbol": "ETHA", "ticket_id": "TF-OLD"},
        )
        raw.pop("risk_verdict")
        out = dm.approve_ticket(raw, self.grants, at(9, 30))
        self.assertTrue(out["acted"])
        self.assertEqual(out["ticket"]["approval_carried_from"], "TF-OLD")

    def test_reprice_up_loses_approval_even_with_a_pass(self):
        raw = ticket(
            limit=20.10,
            carries_approval={"limit": 19.70, "stop": 18.40, "qty": 1, "symbol": "ETHA"},
        )
        out = dm.approve_ticket(raw, self.grants, at(9, 30))
        self.assertFalse(out["acted"])
        self.assertEqual(out["reason"], "reprice_limit_raised")

    def test_wider_stop_loses_approval(self):
        raw = ticket(
            stop=18.90,
            carries_approval={"limit": 19.70, "stop": 18.40, "qty": 1, "symbol": "ETHA"},
        )
        out = dm.approve_ticket(raw, self.grants, at(9, 30))
        self.assertFalse(out["acted"])
        self.assertEqual(out["reason"], "reprice_stop_widened")

    def test_new_symbol_does_not_inherit(self):
        raw = ticket(
            symbol="SOFI",
            risk_verdict=None,
            carries_approval={"limit": 19.70, "stop": 18.40, "qty": 1, "symbol": "ETHA"},
        )
        raw.pop("risk_verdict")
        keeps, why = dm.reprice_keeps_approval(raw)
        self.assertFalse(keeps)
        self.assertEqual(why, "no_prior_approval")


class SessionClock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        grants_file(self.root)
        self.grants = dm.load_grants(self.root)
        self.rules = {"risk": {"day_breaker_pct": 0.045, "peak_dd_pct": 0.18}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_arms_at_0925_when_cash_over_20(self):
        d = dm.arm_decision(book(), self.rules, self.grants, {"held": False}, at(9, 25))
        self.assertTrue(d["arm"])

    def test_refuses_before_the_window(self):
        d = dm.arm_decision(book(), self.rules, self.grants, {"held": False}, at(8, 30))
        self.assertFalse(d["arm"])
        self.assertEqual(d["reason"], "outside_arm_window")

    def test_refuses_a_restart_at_1400(self):
        d = dm.arm_decision(book(), self.rules, self.grants, {"held": False}, at(14, 0))
        self.assertFalse(d["arm"])
        self.assertEqual(d["reason"], "outside_arm_window")

    def test_refuses_cash_at_20_percent(self):
        d = dm.arm_decision(
            book(cash=121.2, equity=606.0), self.rules, self.grants, {"held": False}, at(9, 25)
        )
        self.assertFalse(d["arm"])
        self.assertEqual(d["reason"], "cash_at_or_under_20")

    def test_refuses_a_hard_hold(self):
        hold = {"held": True, "reason": "FOMC"}
        d = dm.arm_decision(book(), self.rules, self.grants, hold, at(9, 25))
        self.assertFalse(d["arm"])
        self.assertTrue(d["reason"].startswith("hard_hold"))

    def test_refuses_a_day_breaker(self):
        d = dm.arm_decision(
            book(day_pnl=-40.0), self.rules, self.grants, {"held": False}, at(9, 25)
        )
        self.assertFalse(d["arm"])
        self.assertEqual(d["reason"], "day_breaker")

    def test_refuses_an_unproven_book(self):
        d = dm.arm_decision(
            book(source="fallback_hint"), self.rules, self.grants, {"held": False}, at(9, 25)
        )
        self.assertFalse(d["arm"])
        self.assertEqual(d["reason"], "book_not_schwab_read")

    def test_refuses_when_the_grant_is_off(self):
        grants_file(self.root, auto_arm_mv_session=False)
        g = dm.load_grants(self.root)
        d = dm.arm_decision(book(), self.rules, g, {"held": False}, at(9, 25))
        self.assertFalse(d["arm"])
        self.assertEqual(d["reason"], "auto_arm_disabled")

    def test_disarm_writes_the_file_past_1600(self):
        path = self.root / "config" / "mv_session.json"
        path.write_text(json.dumps({"armed": True, "until": "2026-09-29T16:00:00-04:00"}))
        wrote = dm.apply_session_clock(self.root, book(), self.rules, at(16, 1))
        self.assertEqual(wrote["wrote"], "disarm")
        saved = json.loads(path.read_text())
        self.assertFalse(saved["armed"])
        self.assertIn("16:00", saved["disarm_reason"])

    def test_disarm_does_not_wait_for_the_until_field(self):
        # The bug in PR #7: a session with `until` in the future, or a session
        # whose until-parser returns first, never reached the 16:00 write.
        path = self.root / "config" / "mv_session.json"
        path.write_text(json.dumps({"armed": True, "until": "2026-09-30T16:00:00-04:00"}))
        wrote = dm.apply_session_clock(self.root, book(), self.rules, at(16, 5))
        self.assertEqual(wrote["wrote"], "disarm")

    def test_weekend_does_not_arm(self):
        # 2026-09-26 is a Saturday.
        d = dm.arm_decision(book(), self.rules, self.grants, {"held": False}, at(9, 25, day=26))
        self.assertFalse(d["arm"])


class Pricing(unittest.TestCase):
    def test_pullback_is_one_atr_under_last_and_under_the_cap(self):
        got = dm.suggest_pullback(last=20.30, atr=0.40, cap=19.90, prior_limit=None)
        self.assertEqual(got["limit"], 19.90)
        self.assertTrue(got["fillable"])

    def test_pullback_never_raises_a_working_limit(self):
        got = dm.suggest_pullback(last=20.30, atr=0.10, cap=21.00, prior_limit=19.70)
        self.assertLessEqual(got["limit"], 19.70)

    def test_stale_flag_does_not_say_cancel(self):
        got = dm.staleness(working_px=19.70, last=20.80, atr=0.40, sessions=4, cap=19.90)
        self.assertEqual(got["action"], "flag")
        self.assertNotIn("cancel", got["action"])

    def test_young_order_is_not_stale(self):
        got = dm.staleness(working_px=19.70, last=20.80, atr=0.40, sessions=1, cap=19.90)
        self.assertEqual(got["action"], "ok")

    def test_idle_cash_offers_only_a_free_live_name(self):
        got = dm.idle_cash(
            book(positions=[{"symbol": "IBIT", "qty": 3}], orders=[]),
            {"universe": ["ETHA", "IBIT", "NOK", "NVO"]},
        )
        self.assertEqual(got["names"], ["ETHA"])
        self.assertGreater(got["excess"], 0)

    def test_idle_cash_skips_a_name_with_a_working_buy(self):
        got = dm.idle_cash(
            book(orders=[{"symbol": "ETHA", "side": "BUY", "status": "WORKING", "price": 19.7}]),
            {"universe": ["ETHA", "IBIT"]},
        )
        self.assertNotIn("ETHA", got["names"])

    def test_yahoo_stamp_is_loud_and_not_a_send(self):
        got = dm.yahoo_fallback_stamp(False)
        self.assertEqual(got["source"], "yahoo_fallback")
        self.assertIn("cannot authorize a POST", got["fallback"])
        self.assertFalse(got["sent"])

    def test_kraken_stamp_is_unverified_without_a_time(self):
        got = dm.kraken_stamp()
        self.assertEqual(got["status"], "UNVERIFIED")
        self.assertIsNone(got["confirmed_at"])


if __name__ == "__main__":
    unittest.main()
