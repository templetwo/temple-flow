"""Normalized broker protocol. No unrestricted HTTP to agents."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

SubmitResult = Literal["ACCEPTED", "REJECTED", "UNKNOWN"]


@dataclass
class CapabilitySnapshot:
    venue: str
    account_alias: str
    features: dict[str, str]
    as_of: str
    status: str


@dataclass
class AccountSnapshot:
    venue: str
    account_alias: str
    cash_available: Decimal
    positions: dict[str, Decimal]
    working_orders: list[dict[str, Any]]
    version: int
    as_of: str


@dataclass
class SubmitAck:
    result: SubmitResult
    broker_order_id: str | None
    detail: str
