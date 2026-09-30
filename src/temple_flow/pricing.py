"""ATR-based fillable pullback pricing and staleness detection.

Provides realistic fill probability for GTC buy limits by pricing them within
a multiple of ATR from the current market, and flags stale orders that have
been too far from the market for too long.
"""
from __future__ import annotations

from typing import TypedDict


class AtrStats(TypedDict, total=False):
    """ATR statistics for a symbol."""
    atr_14: float  # 14-period ATR
    atr_60_avg: float  # 60-period average ATR
    atr_ratio: float  # current / 60-day average
    last: float  # current price


class PullbackPricing(TypedDict, total=False):
    """Suggested pullback pricing."""
    symbol: str
    suggested_limit: float
    atr_14: float
    distance_from_last_atr: float
    fillable: bool
    reason: str


class StalenessCheck(TypedDict, total=False):
    """Order staleness analysis."""
    symbol: str
    order_id: str
    working_px: float
    last: float
    distance_atr: float
    sessions_stale: int
    action: str  # "remint" | "ok" | "through_cap"
    reason: str


def calculate_atr(bars: list[dict], period: int = 14) -> float | None:
    """Calculate Average True Range over period bars.
    
    Args:
        bars: List of dicts with high, low, close (newest first or last)
        period: Number of periods for ATR
    
    Returns:
        ATR value or None if insufficient data
    """
    if len(bars) < period + 1:
        return None
    
    # Reverse if newest first (common in API responses)
    if len(bars) >= 2 and bars[0].get("time", "") > bars[1].get("time", ""):
        bars = list(reversed(bars))
    
    true_ranges = []
    for i in range(1, len(bars)):
        high = bars[i].get("high") or bars[i].get("h") or 0
        low = bars[i].get("low") or bars[i].get("l") or 0
        prev_close = bars[i - 1].get("close") or bars[i - 1].get("c") or 0
        
        if not (high and low and prev_close):
            continue
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return None
    
    # Simple moving average of true ranges
    return sum(true_ranges[-period:]) / period


def suggest_fillable_limit(
    symbol: str,
    last: float,
    atr_14: float,
    cap: float | None = None,
    atr_multiplier: float = 1.0,
    tick_size: float = 0.01,
) -> PullbackPricing:
    """Suggest a fillable buy limit price within ATR distance of last.
    
    Args:
        symbol: Symbol name
        last: Current market price
        atr_14: 14-period ATR
        cap: Maximum price (Risk cap)
        atr_multiplier: How many ATRs below last (default 1.0 = 1 ATR)
        tick_size: Price tick size for rounding
    
    Returns:
        PullbackPricing dict with suggested limit and fillability
    """
    distance_dollars = atr_14 * atr_multiplier
    suggested = last - distance_dollars
    
    # Round to tick size
    suggested = round(suggested / tick_size) * tick_size
    
    result: PullbackPricing = {
        "symbol": symbol,
        "suggested_limit": suggested,
        "atr_14": atr_14,
        "distance_from_last_atr": atr_multiplier,
        "fillable": True,
        "reason": f"priced {atr_multiplier:.1f} ATR below last",
    }
    
    # Check against cap
    if cap is not None and suggested > cap:
        result["fillable"] = False
        result["reason"] = f"suggested {suggested:.2f} > cap {cap:.2f}"
        result["suggested_limit"] = cap
    
    return result


def check_order_staleness(
    symbol: str,
    order_id: str,
    working_px: float,
    last: float,
    atr_14: float,
    cap: float | None,
    sessions_since_placement: int,
    staleness_atr_threshold: float = 2.0,
    staleness_session_threshold: int = 3,
) -> StalenessCheck:
    """Check if a working buy limit is stale and should be reminted.
    
    Args:
        symbol: Symbol name
        order_id: Order ID
        working_px: Current working limit price
        last: Current market price
        atr_14: 14-period ATR
        cap: Maximum price (Risk cap)
        sessions_since_placement: Number of sessions order has been open
        staleness_atr_threshold: How many ATRs below last triggers stale (default 2.0)
        staleness_session_threshold: Min sessions before considering stale (default 3)
    
    Returns:
        StalenessCheck dict with action and reason
    """
    distance = last - working_px
    distance_atr = distance / atr_14 if atr_14 > 0 else 0
    
    result: StalenessCheck = {
        "symbol": symbol,
        "order_id": order_id,
        "working_px": working_px,
        "last": last,
        "distance_atr": round(distance_atr, 2),
        "sessions_stale": sessions_since_placement,
        "action": "ok",
        "reason": "within fillable range",
    }
    
    # Not stale if recently placed
    if sessions_since_placement < staleness_session_threshold:
        result["reason"] = f"only {sessions_since_placement} sessions old"
        return result
    
    # Check if through cap
    if cap is not None and last > cap and working_px <= cap:
        # Resting pullback - this is expected behavior
        result["action"] = "ok"
        result["reason"] = "resting pullback (do_not_chase)"
        return result
    
    # Check if too far below market
    if distance_atr > staleness_atr_threshold:
        result["action"] = "remint"
        result["reason"] = (
            f"stale: {distance_atr:.1f} ATR below last for {sessions_since_placement} sessions"
        )
        return result
    
    return result


def calculate_idle_cash_allocation(
    equity: float,
    cash: float,
    target_cash_pct: float,
    open_positions: list[dict],
    universe: list[str],
    risk_pct: float = 0.025,
    max_position_pct: float = 0.18,
    atr_filter_ratio: float = 1.8,
) -> dict:
    """Calculate how much idle cash should be deployed.
    
    Args:
        equity: Current equity
        cash: Current cash
        target_cash_pct: Target cash percentage (e.g. 0.25 for 25%)
        open_positions: List of current positions
        universe: List of symbols to consider
        risk_pct: Max risk per trade (e.g. 0.025 for 2.5%)
        max_position_pct: Max position size (e.g. 0.18 for 18%)
        atr_filter_ratio: ATR ratio threshold for size reduction
    
    Returns:
        Dict with excess_cash, deploy_amount, suggested_allocations
    """
    cash_pct = cash / equity if equity > 0 else 0
    excess_cash = 0
    
    if cash_pct > target_cash_pct:
        excess_cash = cash - (equity * target_cash_pct)
    
    result = {
        "equity": equity,
        "cash": cash,
        "cash_pct": round(cash_pct, 4),
        "target_cash_pct": target_cash_pct,
        "excess_cash": round(excess_cash, 2),
        "deploy_amount": round(min(excess_cash, cash * 0.8), 2),  # Cap at 80% of cash
        "suggested_allocations": [],
        "reason": None,
    }
    
    if excess_cash <= 0:
        result["reason"] = f"cash {cash_pct:.1%} <= target {target_cash_pct:.1%}"
        return result
    
    # Find symbols not at max position
    position_map = {p["symbol"]: p for p in open_positions}
    available_symbols = []
    
    for sym in universe:
        pos = position_map.get(sym)
        if pos:
            pos_value = pos.get("market_value") or pos.get("mv") or 0
            pos_pct = pos_value / equity if equity > 0 else 0
            if pos_pct >= max_position_pct:
                continue  # Already at max
        available_symbols.append(sym)
    
    if not available_symbols:
        result["reason"] = "no available symbols below max position size"
        return result
    
    # Suggest equal allocation to available symbols
    deploy_per_symbol = result["deploy_amount"] / len(available_symbols)
    
    for sym in available_symbols:
        result["suggested_allocations"].append({
            "symbol": sym,
            "notional": round(deploy_per_symbol, 2),
            "note": "size from Risk Manager with Risk-PASS and idle cash priority",
        })
    
    result["reason"] = f"excess cash {excess_cash:.2f} ({cash_pct:.1%} > {target_cash_pct:.1%})"
    return result
