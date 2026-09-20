"""Canonical decimal money. No float SQLite SUM. No NaN/Infinity."""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_FLOOR, localcontext
from typing import Any

DECIMAL_RE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
NONNEG_RE = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")


class MoneyError(ValueError):
    """A value is not a canonical decimal string."""


def amount(value: Any, *, allow_negative: bool = False) -> Decimal:
    pattern = DECIMAL_RE if allow_negative else NONNEG_RE
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise MoneyError("Expected a canonical decimal string, not a float or NaN")
    return Decimal(value)


def dstr(value: Decimal) -> str:
    """Normalize Decimal to a canonical non-scientific string."""
    if not isinstance(value, Decimal):
        raise MoneyError("dstr requires Decimal")
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in {"", "-"}:
        s = "0"
    return s


def funded_quantity(cash: str, price: str, entry_fee_fraction: str, increment: str) -> Decimal:
    """All-eligible-cash ceiling including entry fee. Not a strategy recommendation."""
    c, p, fee, step = map(amount, [cash, price, entry_fee_fraction, increment])
    if p <= 0 or step <= 0 or fee >= 1:
        raise MoneyError("Invalid price, increment or fee")
    with localcontext() as ctx:
        ctx.prec = 50
        raw = c / (p * (1 + fee))
        q = (raw / step).to_integral_value(rounding=ROUND_FLOOR) * step
        if q * p * (1 + fee) > c:
            raise MoneyError("Rounded reservation exceeds funds")
        return q


def round_trip_net(qty: str, buy: str, sell: str, entry_fee: str, exit_fee: str) -> Decimal:
    q, a, b, fi, fo = (
        amount(qty),
        amount(buy),
        amount(sell),
        amount(entry_fee),
        amount(exit_fee),
    )
    if fi >= 1 or fo >= 1:
        raise MoneyError("Fee fraction invalid")
    with localcontext() as ctx:
        ctx.prec = 50
        return q * b * (1 - fo) - q * a * (1 + fi)


def flow_adjusted_pnl(start: str, end: str, contributions: str, distributions: str) -> Decimal:
    s, e, c, d = (
        amount(start),
        amount(end),
        amount(contributions),
        amount(distributions),
    )
    return e - s - c + d


def entry_debit(qty: Decimal, price: Decimal, fee_fraction: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        return qty * price * (1 + fee_fraction)
