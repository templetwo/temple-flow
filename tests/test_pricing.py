"""Tests for pricing module."""
import unittest
from temple_flow.pricing import (
    calculate_atr,
    suggest_fillable_limit,
    check_order_staleness,
    calculate_idle_cash_allocation,
)


class TestATRCalculation(unittest.TestCase):
    def test_calculate_atr_basic(self):
        """ATR should calculate correctly for basic case."""
        bars = [
            {"high": 100, "low": 98, "close": 99},
            {"high": 101, "low": 97, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {"high": 103, "low": 100, "close": 102},
            {"high": 102, "low": 99, "close": 100},
            {"high": 101, "low": 98, "close": 99},
            {"high": 100, "low": 97, "close": 98},
            {"high": 99, "low": 96, "close": 97},
            {"high": 98, "low": 95, "close": 96},
            {"high": 99, "low": 96, "close": 98},
            {"high": 100, "low": 97, "close": 99},
            {"high": 101, "low": 98, "close": 100},
            {"high": 102, "low": 99, "close": 101},
            {"high": 101, "low": 98, "close": 99},
            {"high": 100, "low": 97, "close": 98},
        ]
        atr = calculate_atr(bars, period=14)
        self.assertIsNotNone(atr)
        self.assertGreater(atr, 0)
    
    def test_calculate_atr_insufficient_data(self):
        """ATR should return None with insufficient data."""
        bars = [{"high": 100, "low": 98, "close": 99}]
        atr = calculate_atr(bars, period=14)
        self.assertIsNone(atr)


class TestFillableLimitSuggestion(unittest.TestCase):
    def test_suggest_limit_within_cap(self):
        """Should suggest limit within cap."""
        result = suggest_fillable_limit(
            symbol="ETHA",
            last=20.0,
            atr_14=1.0,
            cap=19.5,
            atr_multiplier=1.0,
        )
        self.assertEqual(result["symbol"], "ETHA")
        self.assertEqual(result["suggested_limit"], 19.0)  # 20 - 1.0 ATR
        self.assertTrue(result["fillable"])
    
    def test_suggest_limit_above_cap(self):
        """Should cap suggestion at Risk cap."""
        result = suggest_fillable_limit(
            symbol="ETHA",
            last=20.0,
            atr_14=0.2,  # Small ATR
            cap=19.5,
            atr_multiplier=1.0,
        )
        self.assertEqual(result["suggested_limit"], 19.5)  # Capped
        self.assertFalse(result["fillable"])
        self.assertIn("cap", result["reason"])


class TestOrderStaleness(unittest.TestCase):
    def test_order_not_stale_recent(self):
        """Recent orders should not be flagged as stale."""
        result = check_order_staleness(
            symbol="ETHA",
            order_id="123",
            working_px=18.0,
            last=20.0,
            atr_14=1.0,
            cap=19.5,
            sessions_since_placement=1,
        )
        self.assertEqual(result["action"], "ok")
        self.assertIn("sessions old", result["reason"])
    
    def test_order_stale_far_below_market(self):
        """Orders far below market for many sessions should be stale."""
        result = check_order_staleness(
            symbol="ETHA",
            order_id="123",
            working_px=18.0,
            last=22.5,  # 4.5 away = 2.25 ATR (> 2.0 threshold)
            atr_14=2.0,
            cap=25.0,  # Cap above last, so not resting pullback
            sessions_since_placement=5,
            staleness_atr_threshold=2.0,
        )
        self.assertEqual(result["action"], "remint")
        self.assertIn("stale", result["reason"])
    
    def test_order_resting_pullback_ok(self):
        """Resting pullback below cap should be OK even if far from last."""
        result = check_order_staleness(
            symbol="ETHA",
            order_id="123",
            working_px=18.0,
            last=21.0,  # Above cap
            atr_14=1.0,
            cap=19.5,
            sessions_since_placement=5,
        )
        self.assertEqual(result["action"], "ok")
        self.assertIn("resting pullback", result["reason"])


class TestIdleCashAllocation(unittest.TestCase):
    def test_no_excess_cash(self):
        """Should return no deployment when cash is at target."""
        result = calculate_idle_cash_allocation(
            equity=600.0,
            cash=150.0,  # 25%
            target_cash_pct=0.25,
            open_positions=[],
            universe=["ETHA", "IBIT"],
        )
        self.assertEqual(result["excess_cash"], 0)
        self.assertEqual(result["deploy_amount"], 0)
        self.assertIn("<=", result["reason"])
    
    def test_excess_cash_deployment(self):
        """Should suggest deployment when cash exceeds target."""
        result = calculate_idle_cash_allocation(
            equity=600.0,
            cash=300.0,  # 50%
            target_cash_pct=0.25,
            open_positions=[],
            universe=["ETHA", "IBIT"],
        )
        self.assertGreater(result["excess_cash"], 0)
        self.assertGreater(result["deploy_amount"], 0)
        self.assertEqual(len(result["suggested_allocations"]), 2)
    
    def test_skip_symbols_at_max_position(self):
        """Should not suggest symbols already at max position."""
        result = calculate_idle_cash_allocation(
            equity=600.0,
            cash=300.0,
            target_cash_pct=0.25,
            open_positions=[
                {"symbol": "ETHA", "market_value": 108.0}  # 18% of 600
            ],
            universe=["ETHA", "IBIT"],
            max_position_pct=0.18,
        )
        self.assertGreater(result["excess_cash"], 0)
        # Should only suggest IBIT
        self.assertEqual(len(result["suggested_allocations"]), 1)
        self.assertEqual(result["suggested_allocations"][0]["symbol"], "IBIT")


if __name__ == "__main__":
    unittest.main()
