"""Normalized broker protocol. No unrestricted HTTP to agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

SubmitResult = Literal["ACCEPTED", "REJECTED", "UNKNOWN"]
CapabilityStatus = Literal[
    "UNAVAILABLE",
    "DOCUMENTED_ONLY",
    "FIXTURE_TESTED",
    "ACCOUNT_VERIFIED",
    "UNSUPPORTED",
    "UNKNOWN",
]


class VenueUnavailable(Exception):
    """Credentials, auth, or venue read failed. Do not substitute a paper book."""


@dataclass
class CapabilitySnapshot:
    venue: str
    account_alias: str
    features: dict[str, str]
    as_of: str
    status: str


@dataclass
class Position:
    symbol: str
    qty: Decimal
    avg: Decimal | None = None
    market_value: Decimal | None = None
    day_pl: Decimal | None = None


@dataclass
class WorkingOrder:
    broker_order_id: str
    symbol: str | None
    side: str
    status: str
    order_type: str | None
    price: Decimal | None = None
    stop_price: Decimal | None = None
    qty: Decimal | None = None
    filled_qty: Decimal | None = None
    remaining: Decimal | None = None
    duration: str | None = None
    parent_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountSnapshot:
    venue: str
    account_alias: str
    source: str
    as_of: str
    version: int
    cash_available: Decimal | None
    equity: Decimal | None
    sod_equity: Decimal | None
    positions: list[Position]
    working_orders: list[WorkingOrder]
    quotes: dict[str, dict[str, Any]]
    orders_ok: bool
    quotes_ok: bool
    note: str = ""
    raw_safe: dict[str, Any] = field(default_factory=dict)

    @property
    def cash(self) -> Decimal:
        if self.cash_available is None:
            raise VenueUnavailable(f"{self.venue} cash unproven")
        return self.cash_available


@dataclass
class SubmitAck:
    result: SubmitResult
    broker_order_id: str | None
    detail: str


class VenueAdapter(Protocol):
    venue: str
    account_alias: str

    def capabilities(self) -> CapabilitySnapshot: ...

    def snapshot(self) -> AccountSnapshot: ...

    def submit(self, intent: dict[str, Any], writer_permit: str) -> SubmitAck: ...

    def cancel(self, broker_order_id: str, writer_permit: str) -> SubmitAck: ...


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))
