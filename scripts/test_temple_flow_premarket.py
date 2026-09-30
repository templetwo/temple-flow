#!/usr/bin/env python3
"""Tests for temple_flow_premarket.py"""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys
import tempfile

# Import from same directory
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from temple_flow_premarket import (
    check_git_status,
    check_market_data_key,
    check_kraken_keys,
    check_mv_session_auto_arm,
    check_mv_session_auto_disarm,
    load_standing_grants,
    load_mv_session,
    save_mv_session,
    now_et,
)


class TestPremarketChecks(unittest.TestCase):
    def test_git_status_check_runs(self):
        """Git status check should return a dict with expected keys."""
        result = check_git_status(HERE.parent)
        self.assertIn("check", result)
        self.assertEqual(result["check"], "git_status")
        self.assertIn("branch", result)
        self.assertIn("warnings", result)
    
    def test_market_data_key_check(self):
        """Market data key check should return a dict."""
        result = check_market_data_key()
        self.assertIn("check", result)
        self.assertEqual(result["check"], "market_data_key")
        self.assertIn("ok", result)
        self.assertIn("warnings", result)
    
    def test_kraken_keys_check(self):
        """Kraken keys check should return a dict."""
        result = check_kraken_keys()
        self.assertIn("check", result)
        self.assertEqual(result["check"], "kraken_keys")
        self.assertIn("ok", result)
    
    def test_load_standing_grants_defaults(self):
        """Standing grants should load with safe defaults when file missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "config").mkdir()
            grants = load_standing_grants(repo)
            
            self.assertIn("desk_may_approve_risk_pass", grants)
            self.assertIn("auto_arm_mv_session", grants)
            self.assertIn("auto_disarm_mv_session", grants)
            self.assertFalse(grants["desk_may_approve_risk_pass"])
            self.assertFalse(grants["auto_arm_mv_session"]["enabled"])
    
    def test_load_standing_grants_from_file(self):
        """Standing grants should load from file when present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            config = repo / "config"
            config.mkdir()
            grants_file = config / "standing_grants.json"
            grants_file.write_text(json.dumps({
                "desk_may_approve_risk_pass": True,
                "auto_arm_mv_session": {"enabled": True},
            }))
            
            grants = load_standing_grants(repo)
            self.assertTrue(grants["desk_may_approve_risk_pass"])
            self.assertTrue(grants["auto_arm_mv_session"]["enabled"])
    
    def test_mv_session_save_and_load(self):
        """MV session should round-trip save/load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            config = repo / "config"
            config.mkdir()
            
            session = {
                "armed": True,
                "armed_at": "2026-09-30T09:25:00-04:00",
                "until": "2026-09-30T16:00:00-04:00",
                "source": "test",
            }
            
            self.assertTrue(save_mv_session(session, repo))
            loaded = load_mv_session(repo)
            self.assertEqual(loaded["armed"], True)
            self.assertEqual(loaded["source"], "test")
    
    def test_mv_auto_disarm_before_time(self):
        """MV auto-disarm should not disarm before 16:00."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            config = repo / "config"
            config.mkdir()
            
            # Create grants with auto_disarm enabled
            grants_file = config / "standing_grants.json"
            grants_file.write_text(json.dumps({
                "auto_disarm_mv_session": {"enabled": True, "time_et": "16:00"}
            }))
            
            # Create armed session
            save_mv_session({
                "armed": True,
                "armed_at": "2026-09-30T09:00:00-04:00",
            }, repo)
            
            # Check at 15:30
            now = datetime(2026, 9, 30, 19, 30, 0, tzinfo=timezone.utc)  # 15:30 ET
            result = check_mv_session_auto_disarm(repo, now)
            
            self.assertFalse(result["disarmed"])
            self.assertIn("before_disarm_time", result["reason"])
    
    def test_mv_auto_disarm_at_time(self):
        """MV auto-disarm should disarm at/after 16:00."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            config = repo / "config"
            config.mkdir()
            
            # Create grants
            grants_file = config / "standing_grants.json"
            grants_file.write_text(json.dumps({
                "auto_disarm_mv_session": {"enabled": True, "time_et": "16:00"}
            }))
            
            # Create armed session
            save_mv_session({
                "armed": True,
                "armed_at": "2026-09-30T09:00:00-04:00",
            }, repo)
            
            # Check at 16:05
            now = datetime(2026, 9, 30, 20, 5, 0, tzinfo=timezone.utc)  # 16:05 ET
            result = check_mv_session_auto_disarm(repo, now)
            
            self.assertTrue(result["disarmed"])
            self.assertIn("auto_disarmed", result["reason"])
            
            # Verify session is actually disarmed
            session = load_mv_session(repo)
            self.assertFalse(session["armed"])
            self.assertIn("disarmed_at", session)


if __name__ == "__main__":
    unittest.main()
