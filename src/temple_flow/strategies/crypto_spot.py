"""Kraken spot pullback — EXPERIMENTAL_UNPROVEN. Not a profitability claim."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from temple_flow.money import dstr, round_trip_net


def _sma(closes: list[Decimal], n: int) -> Decimal | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:], Decimal("0")) / Decimal(n)


def _atr(bars: list[list], n: int = 14) -> Decimal | None:
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(-n, 0):
        high = Decimal(str(bars[i][2]))
        low = Decimal(str(bars[i][3]))
        prev = Decimal(str(bars[i - 1][4]))
        trs.append(max(high - low, abs(high - prev), abs(low - prev)))
    return sum(trs, Decimal("0")) / Decimal(n)


def evaluate_pullback(
    pair: str,
    bars: list[list],
    last: Decimal,
    taker: str,
    maker: str,
    cash: str,
    ordermin: str,
) -> dict[str, Any]:
    """Daily SMA pullback. Decline if history or net edge is missing."""
    closes = [Decimal(str(b[4])) for b in bars]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    atr = _atr(bars, 14)
    if sma20 is None or sma50 is None or atr is None:
        return {"result": "DECLINE", "reason": "HISTORY_UNPROVEN", "pair": pair}
    if not (sma20 > sma50 and last < sma20 and last > sma50):
        return {
            "result": "DECLINE",
            "reason": "NO_SETUP",
            "pair": pair,
            "sma20": dstr(sma20),
            "sma50": dstr(sma50),
            "last": dstr(last),
        }
    stop = last - (Decimal("2") * atr)
    if stop <= 0 or stop >= last:
        return {"result": "DECLINE", "reason": "STOP_INVALID", "pair": pair}
    limit = last
    # size later via allocator; here a 1-unit probe of economics at $1 notional is wrong.
    # Use cash-capped 1 increment of last for edge sign: qty = ordermin or 0
    qty = Decimal(ordermin) if Decimal(ordermin) > 0 else Decimal("0.0001")
    net = round_trip_net(dstr(qty), dstr(limit), dstr(sma20), taker, taker)
    if net <= 0:
        return {
            "result": "DECLINE",
            "reason": "NO_NET_EDGE",
            "pair": pair,
            "net": dstr(net),
            "last": dstr(last),
            "stop": dstr(stop),
        }
    return {
        "result": "PASS",
        "reason": "PULLBACK_NET_EDGE",
        "pair": pair,
        "quantity_hint": dstr(qty),
        "limit": dstr(limit),
        "stop": dstr(stop),
        "modeled_exit": dstr(sma20),
        "net": dstr(net),
        "economic_evidence": "EXPERIMENTAL_UNPROVEN",
        "weight": "1",
        "entry_fee_fraction": taker,
        "exit_fee_fraction": taker,
        "increment": ordermin if Decimal(ordermin) > 0 else "0.0001",
        "worst_entry": dstr(limit),
    }


def evaluate_trend_continuation(
    pair: str,
    bars: list[list],
    last: Decimal,
    taker: str,
    maker: str,
    cash: str,
    ordermin: str,
) -> dict[str, Any]:
    """POC uptrend entry when price is already above SMA20. EXPERIMENTAL_UNPROVEN.

    Gate: SMA20 > SMA50 and last > SMA20. Stop = max(SMA20, last - 2*ATR).
    Modeled exit = last + 1*ATR (fee-aware net must still be positive at ordermin probe).
    """
    closes = [Decimal(str(b[4])) for b in bars]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    atr = _atr(bars, 14)
    if sma20 is None or sma50 is None or atr is None:
        return {"result": "DECLINE", "reason": "HISTORY_UNPROVEN", "pair": pair}
    if not (sma20 > sma50 and last > sma20):
        return {
            "result": "DECLINE",
            "reason": "NO_TREND_SETUP",
            "pair": pair,
            "sma20": dstr(sma20),
            "sma50": dstr(sma50),
            "last": dstr(last),
        }
    stop = max(sma20, last - (Decimal("2") * atr))
    if stop <= 0 or stop >= last:
        return {"result": "DECLINE", "reason": "STOP_INVALID", "pair": pair}
    limit = last
    target = last + atr
    qty = Decimal(ordermin) if Decimal(ordermin) > 0 else Decimal("0.0001")
    net = round_trip_net(dstr(qty), dstr(limit), dstr(target), taker, taker)
    if net <= 0:
        return {
            "result": "DECLINE",
            "reason": "NO_NET_EDGE",
            "pair": pair,
            "net": dstr(net),
            "last": dstr(last),
            "stop": dstr(stop),
        }
    return {
        "result": "PASS",
        "reason": "TREND_CONTINUATION_POC",
        "pair": pair,
        "quantity_hint": dstr(qty),
        "limit": dstr(limit),
        "stop": dstr(stop),
        "modeled_exit": dstr(target),
        "net": dstr(net),
        "economic_evidence": "EXPERIMENTAL_UNPROVEN",
        "weight": "1",
        "entry_fee_fraction": taker,
        "exit_fee_fraction": taker,
        "increment": ordermin if Decimal(ordermin) > 0 else "0.0001",
        "worst_entry": dstr(limit),
        "sma20": dstr(sma20),
        "sma50": dstr(sma50),
    }
