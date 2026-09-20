"""Deterministic fake venue. No credentials. No network."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from temple_flow.adapters.protocol import AccountSnapshot, CapabilitySnapshot, Position, SubmitAck
from temple_flow.money import dstr, entry_debit


class PaperBroker:
    def __init__(
        self,
        venue: str,
        account_alias: str,
        cash: Decimal,
        taker_fee: Decimal,
        maker_fee: Decimal,
    ):
        self.venue = venue
        self.account_alias = account_alias
        self.cash = cash
        self.reserved = Decimal("0")
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee
        self.orders: dict[str, dict[str, Any]] = {}
        self.fills: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, Decimal] = {}
        self.protection: dict[str, dict[str, Any]] = {}
        self.version = 1
        self._seq = 0
        self.next_submit_result = "ACCEPTED"
        self.unknown_pending: dict[str, dict[str, Any]] = {}

    def capabilities(self) -> CapabilitySnapshot:
        return CapabilitySnapshot(
            venue=self.venue,
            account_alias=self.account_alias,
            features={
                "limit_buy": "FIXTURE_TESTED",
                "native_stop": "FIXTURE_TESTED",
                "borrow": "UNSUPPORTED",
                "short": "UNSUPPORTED",
            },
            as_of="1970-01-01T00:00:00Z",
            status="FIXTURE_TESTED",
        )

    def snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            venue=self.venue,
            account_alias=self.account_alias,
            source="paper_fixture",
            as_of="1970-01-01T00:00:00Z",
            version=self.version,
            cash_available=self.cash,
            equity=self.cash,
            sod_equity=self.cash,
            positions=[Position(symbol=s, qty=q) for s, q in self.positions.items()],
            working_orders=[],
            quotes={},
            orders_ok=True,
            quotes_ok=True,
            note="FIXTURE_ONLY",
        )

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"PAPER-{prefix}-{self._seq:04d}"

    def submit(self, intent: dict[str, Any], writer_permit: str) -> SubmitAck:
        if writer_permit != "paper-writer-1":
            return SubmitAck("REJECTED", None, "writer_permit_mismatch")
        order_id = self._next_id("ORD")
        record = {"intent": intent, "broker_order_id": order_id, "state": "SUBMITTING"}
        if self.next_submit_result == "UNKNOWN":
            self.unknown_pending[intent["client_order_id"]] = record
            self.next_submit_result = "ACCEPTED"
            return SubmitAck("UNKNOWN", None, "transport_timeout_after_possible_send")
        if self.next_submit_result == "REJECTED":
            return SubmitAck("REJECTED", None, "fixture_reject")
        qty = Decimal(intent["quantity"])
        px = Decimal(intent["limit_price"])
        debit = entry_debit(qty, px, self.taker_fee)
        if intent["side"] == "buy" and debit > self.cash:
            return SubmitAck("REJECTED", None, "insufficient_cash")
        self.orders[order_id] = {
            "broker_order_id": order_id,
            "client_order_id": intent["client_order_id"],
            "state": "OPEN",
            "intent": intent,
        }
        return SubmitAck("ACCEPTED", order_id, "accepted")

    def recover_unknown(self, client_order_id: str) -> SubmitAck:
        pending = self.unknown_pending.pop(client_order_id, None)
        if pending is None:
            return SubmitAck("REJECTED", None, "not_found_after_reconcile")
        intent = pending["intent"]
        order_id = pending["broker_order_id"]
        self.orders[order_id] = {
            "broker_order_id": order_id,
            "client_order_id": client_order_id,
            "state": "OPEN",
            "intent": intent,
        }
        return SubmitAck("ACCEPTED", order_id, "recovered")

    def fill(
        self,
        broker_order_id: str,
        fill_id: str,
        quantity: Decimal,
        price: Decimal,
    ) -> dict[str, Any]:
        order = self.orders[broker_order_id]
        intent = order["intent"]
        fee = quantity * price * self.taker_fee
        if intent["side"] == "buy":
            debit = quantity * price + fee
            self.cash -= debit
            self.positions[intent["instrument_id"]] = (
                self.positions.get(intent["instrument_id"], Decimal("0")) + quantity
            )
        event = {
            "venue": self.venue,
            "account_alias": self.account_alias,
            "fill_id": fill_id,
            "broker_order_id": broker_order_id,
            "quantity_decimal": dstr(quantity),
            "price_decimal": dstr(price),
            "fee_decimal": dstr(fee),
            "fee_currency": "USD",
            "exchange_time": "1970-01-01T00:00:01Z",
            "recorded_at": "1970-01-01T00:00:02Z",
            "source_ref": "paper",
        }
        self.fills[fill_id] = event
        remaining = Decimal(intent["quantity"]) - sum(
            Decimal(f["quantity_decimal"])
            for f in self.fills.values()
            if f["broker_order_id"] == broker_order_id
        )
        order["state"] = "FILLED" if remaining == 0 else "PARTIAL"
        self.version += 1
        return event

    def attach_stop(self, broker_order_id: str, lot_qty: Decimal, stop_price: str) -> str:
        stop_id = self._next_id("STP")
        self.protection[stop_id] = {
            "parent": broker_order_id,
            "qty": dstr(lot_qty),
            "stop": stop_price,
            "state": "CONFIRMED",
        }
        return stop_id
