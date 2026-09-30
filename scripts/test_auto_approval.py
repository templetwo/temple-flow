#!/usr/bin/env python3
"""Tests for auto-approval logic in temple_flow_wire.py"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Import from same directory
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from temple_flow_wire import (
    can_auto_approve_ticket,
    auto_approve_ticket_in_place,
    check_remint_auto_approve,
    load_outbox_tickets,
    load_standing_grants,
)


def example_rules():
    return {
        "universe": ["ETHA", "IBIT"],
        "protect": {"NOK": {}, "NVO": {}},
        "entries": {
            "ETHA": {"cap": 18.9},
            "IBIT": {"cap": 43.9},
        },
    }


class TestAutoApproval(unittest.TestCase):
    def test_can_auto_approve_grant_disabled(self):
        """Should not auto-approve when grant is disabled."""
        grants = {"desk_may_approve_risk_pass": False}
        ticket = {"risk_verdict": "PASS", "symbol": "ETHA"}
        rules = example_rules()
        
        can, reason = can_auto_approve_ticket(ticket, grants, rules)
        self.assertFalse(can)
        self.assertIn("grant", reason)
    
    def test_can_auto_approve_risk_veto(self):
        """Should not auto-approve when risk_verdict is VETO."""
        grants = {"desk_may_approve_risk_pass": True}
        ticket = {"risk_verdict": "VETO", "symbol": "ETHA"}
        rules = example_rules()
        
        can, reason = can_auto_approve_ticket(ticket, grants, rules)
        self.assertFalse(can)
        self.assertIn("veto", reason.lower())
    
    def test_can_auto_approve_no_verdict(self):
        """Should not auto-approve when no risk_verdict and risk_stamped=False."""
        grants = {"desk_may_approve_risk_pass": True}
        ticket = {"symbol": "ETHA", "risk_stamped": False}
        rules = example_rules()
        
        can, reason = can_auto_approve_ticket(ticket, grants, rules)
        self.assertFalse(can)
        self.assertIn("not_pass", reason)
    
    def test_can_auto_approve_backward_compat_risk_stamped(self):
        """Should auto-approve when risk_stamped=True (backward compat)."""
        grants = {"desk_may_approve_risk_pass": True}
        ticket = {"symbol": "ETHA", "risk_stamped": True, "limit": 18.5}
        rules = example_rules()
        
        can, reason = can_auto_approve_ticket(ticket, grants, rules)
        self.assertTrue(can)
        self.assertIn("auto_approve", reason)
    
    def test_can_auto_approve_new_universe_name(self):
        """Should not auto-approve new universe symbols."""
        grants = {"desk_may_approve_risk_pass": True}
        ticket = {"risk_verdict": "PASS", "symbol": "SOFI", "limit": 10.0}
        rules = example_rules()
        
        can, reason = can_auto_approve_ticket(ticket, grants, rules)
        self.assertFalse(can)
        self.assertIn("new_universe", reason)
    
    def test_can_auto_approve_through_cap_chase(self):
        """Should not auto-approve through-cap chase."""
        grants = {"desk_may_approve_risk_pass": True}
        ticket = {"risk_verdict": "PASS", "symbol": "ETHA", "limit": 19.5}  # > cap 18.9
        rules = example_rules()
        
        can, reason = can_auto_approve_ticket(ticket, grants, rules)
        self.assertFalse(can)
        self.assertIn("through_cap", reason)
    
    def test_can_auto_approve_breaker_active(self):
        """Should not auto-approve when breaker is active."""
        grants = {"desk_may_approve_risk_pass": True}
        ticket = {
            "risk_verdict": "PASS",
            "symbol": "ETHA",
            "limit": 18.5,
            "breaker_active": True,
        }
        rules = example_rules()
        
        can, reason = can_auto_approve_ticket(ticket, grants, rules)
        self.assertFalse(can)
        self.assertIn("breaker", reason)
    
    def test_can_auto_approve_risk_pass_within_cap(self):
        """Should auto-approve Risk-PASS within cap."""
        grants = {"desk_may_approve_risk_pass": True}
        ticket = {"risk_verdict": "PASS", "symbol": "ETHA", "limit": 18.5}  # < cap 18.9
        rules = example_rules()
        
        can, reason = can_auto_approve_ticket(ticket, grants, rules)
        self.assertTrue(can)
        self.assertIn("auto_approve", reason)
    
    def test_auto_approve_ticket_in_place(self):
        """Should auto-approve ticket and add metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            ticket = {
                "id": "TF-20260930-01",
                "status": "proposed",
                "risk_verdict": "PASS",
                "symbol": "ETHA",
            }
            
            ticket_path = repo / "test_ticket.json"
            ticket_path.write_text(json.dumps(ticket))
            
            now = datetime(2026, 9, 30, 13, 0, 0, tzinfo=timezone.utc)
            success = auto_approve_ticket_in_place(
                ticket_path, "test_reason", repo, now
            )
            
            self.assertTrue(success)
            
            approved = json.loads(ticket_path.read_text())
            self.assertEqual(approved["status"], "approved")
            self.assertTrue(approved["risk_stamped"])
            self.assertIn("auto_approved_at", approved)
            self.assertEqual(approved["auto_approve_reason"], "test_reason")
            self.assertIn("expires_at", approved)
    
    def test_check_remint_auto_approve_disabled(self):
        """Should not auto-approve remint when disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            grants = {"auto_approve_remint": {"enabled": False}}
            ticket = {"id": "TF-20260930-01"}
            ticket_path = repo / "ticket.json"
            
            result = check_remint_auto_approve(ticket, ticket_path, grants, repo)
            self.assertFalse(result)
    
    def test_check_remint_auto_approve_no_previous(self):
        """Should not auto-approve remint when no previous approval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            grants = {"auto_approve_remint": {"enabled": True}}
            ticket = {
                "id": "TF-20260930-01",
                "status": "proposed",
                "action": "place_gtc_bracket",
                "side": "BUY",
                "symbol": "ETHA",
                "limit": 18.5,
            }
            ticket_path = repo / "ticket.json"
            ticket_path.write_text(json.dumps(ticket))
            
            result = check_remint_auto_approve(ticket, ticket_path, grants, repo)
            self.assertFalse(result)
    
    def test_check_remint_auto_approve_worse_price(self):
        """Should not auto-approve remint at worse price."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            config = repo / "config"
            outbox = config / "outbox"
            done = outbox / "done"
            done.mkdir(parents=True)
            
            # Previous approval at 18.5
            prev = {
                "id": "TF-20260930-01",
                "status": "approved",
                "action": "place_gtc_bracket",
                "side": "BUY",
                "symbol": "ETHA",
                "limit": 18.5,
                "stop": 17.5,
            }
            prev_path = done / "TF-20260930-01.json"
            prev_path.write_text(json.dumps(prev))
            
            # Create rules file
            rules = example_rules()
            rules_path = config / "standing_rules.json"
            rules_path.write_text(json.dumps(rules))
            
            # New remint at worse price (higher limit)
            grants = {"auto_approve_remint": {"enabled": True}}
            ticket = {
                "id": "TF-20260930-01",
                "status": "proposed",
                "action": "place_gtc_bracket",
                "side": "BUY",
                "symbol": "ETHA",
                "limit": 18.7,  # Higher = worse
                "stop": 17.5,
            }
            ticket_path = outbox / "TF-20260930-01.json"
            ticket_path.write_text(json.dumps(ticket))
            
            result = check_remint_auto_approve(ticket, ticket_path, grants, repo)
            self.assertFalse(result)
    
    def test_check_remint_auto_approve_same_or_better(self):
        """Should auto-approve remint at same or better price within cap."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            config = repo / "config"
            outbox = config / "outbox"
            done = outbox / "done"
            done.mkdir(parents=True)
            
            # Previous approval at 18.5
            prev = {
                "id": "TF-20260930-01",
                "status": "approved",
                "action": "place_gtc_bracket",
                "side": "BUY",
                "symbol": "ETHA",
                "limit": 18.5,
                "stop": 17.5,
            }
            prev_path = done / "TF-20260930-01.json"
            prev_path.write_text(json.dumps(prev))
            
            # Create rules file
            rules = example_rules()
            rules_path = config / "standing_rules.json"
            rules_path.write_text(json.dumps(rules))
            
            # New remint at better price (lower limit, within cap)
            grants = {"auto_approve_remint": {"enabled": True}}
            ticket = {
                "id": "TF-20260930-01",
                "status": "proposed",
                "action": "place_gtc_bracket",
                "side": "BUY",
                "symbol": "ETHA",
                "limit": 18.3,  # Lower = better
                "stop": 17.5,
            }
            ticket_path = outbox / "TF-20260930-01.json"
            ticket_path.write_text(json.dumps(ticket))
            
            result = check_remint_auto_approve(ticket, ticket_path, grants, repo)
            self.assertTrue(result)
            
            # Verify ticket was approved
            approved = json.loads(ticket_path.read_text())
            self.assertEqual(approved["status"], "approved")
            self.assertTrue(approved["risk_stamped"])
    
    def test_load_outbox_tickets_auto_approves_risk_pass(self):
        """load_outbox_tickets should auto-approve Risk-PASS tickets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            config = repo / "config"
            outbox = config / "outbox"
            outbox.mkdir(parents=True)
            
            # Create grants
            grants = {
                "desk_may_approve_risk_pass": True,
                "auto_approve_remint": {"enabled": False},
            }
            grants_path = config / "standing_grants.json"
            grants_path.write_text(json.dumps(grants))
            
            # Create rules
            rules = example_rules()
            rules_path = config / "standing_rules.json"
            rules_path.write_text(json.dumps(rules))
            
            # Create Risk-PASS ticket
            ticket = {
                "id": "TF-20260930-01",
                "status": "proposed",
                "risk_verdict": "PASS",
                "symbol": "ETHA",
                "action": "place_gtc_bracket",
                "side": "BUY",
                "limit": 18.5,
            }
            ticket_path = outbox / "TF-20260930-01.json"
            ticket_path.write_text(json.dumps(ticket))
            
            # Load tickets - should auto-approve
            tickets = load_outbox_tickets(repo)
            
            self.assertEqual(len(tickets), 1)
            self.assertEqual(tickets[0]["ticket"]["status"], "approved")
            self.assertTrue(tickets[0]["ticket"]["risk_stamped"])
            self.assertIn("auto_approved_at", tickets[0]["ticket"])


if __name__ == "__main__":
    unittest.main()
