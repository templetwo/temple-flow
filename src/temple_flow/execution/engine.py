"""Campaign paper executor: evaluate, reserve, submit, fill, protect.

Does not import temple_flow_wire. No per-ticket human approval.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from temple_flow.adapters.paper import PaperBroker
from temple_flow.allocation.allocator import allocate_funded_weighted_v1
from temple_flow.campaign.contracts import ContractError, validate_document
from temple_flow.campaign.policy import policy_digest
from temple_flow.ledger.store import LedgerStore
from temple_flow.money import amount, dstr, entry_debit, round_trip_net


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PaperEngine:
    def __init__(
        self,
        store: LedgerStore,
        broker: PaperBroker,
        campaign: dict[str, Any],
        grant: dict[str, Any],
        writer_permit: str = "paper-writer-1",
    ):
        self.store = store
        self.broker = broker
        self.campaign = campaign
        self.grant = grant
        self.writer_permit = writer_permit
        self.digest = grant["policy_digest"]
        if policy_digest(campaign) != self.digest:
            raise ContractError("engine campaign digest mismatch")

    def evaluate(self, candidate: dict[str, Any], cash_available: str) -> dict[str, Any]:
        decision_id = candidate.get("decision_id") or str(uuid.uuid4())
        created = candidate.get("created_at") or _now()
        fee_id = candidate["fee_snapshot_id"]
        market_id = candidate["market_snapshot_id"]
        qty = amount(candidate["quantity"])
        price = amount(candidate["worst_entry"])
        fee = amount(candidate["entry_fee_fraction"])
        debit = entry_debit(qty, price, fee)
        net = round_trip_net(
            candidate["quantity"],
            candidate["worst_entry"],
            candidate["modeled_exit"],
            candidate["entry_fee_fraction"],
            candidate["exit_fee_fraction"],
        )
        if net <= 0:
            result = "DECLINE"
            reasons = ["NO_NET_EDGE"]
            exec_qty = None
            cash_req = dstr(debit)
        elif debit > amount(cash_available):
            result = "DECLINE"
            reasons = ["INSUFFICIENT_FUNDED_CASH"]
            exec_qty = None
            cash_req = dstr(debit)
        else:
            result = "PASS"
            reasons = ["NET_EDGE_AND_RESOURCES_PASS"]
            exec_qty = candidate["quantity"]
            cash_req = dstr(debit)
        decision = {
            "schema_version": "decision.v2",
            "decision_id": decision_id,
            "campaign_id": self.campaign["campaign_id"],
            "campaign_revision": self.campaign["revision"],
            "mode": "paper",
            "venue": candidate["venue"],
            "account_alias": candidate["account_alias"],
            "candidate_id": candidate["candidate_id"],
            "result": result,
            "reason_codes": reasons,
            "policy_digest": self.digest,
            "account_state_version": self.broker.version,
            "fee_snapshot_id": fee_id,
            "market_snapshot_id": market_id,
            "created_at": created,
            "net_edge_usd_estimate": dstr(net),
            "cash_required_usd": cash_req,
            "cash_available_usd": cash_available,
            "executable_quantity": exec_qty,
            "evidence_refs": candidate.get("evidence_refs", ["paper-fixture"]),
            "economic_evidence": self.campaign["economic_evidence"],
        }
        validate_document(decision)
        self.store.insert_decision(decision)
        self.store.record_audit(self.campaign["campaign_id"], "DECISION", {"result": result, "reasons": reasons})
        return decision

    def authorize_and_submit(self, candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        if decision["result"] != "PASS":
            raise ContractError("cannot submit a non-PASS decision")
        runtime = self.store.runtime(self.campaign["campaign_id"])
        if runtime is None or runtime["entry_permission"] != "ENABLED":
            raise ContractError("entries not enabled")
        grant = self.store.get_active_grant(self.campaign["campaign_id"])
        if grant is None or grant["generation"] != self.grant["generation"]:
            raise ContractError("grant generation mismatch at send boundary")
        intent_id = str(uuid.uuid4())
        reservation_id = str(uuid.uuid4())
        client_order_id = str(uuid.uuid4())
        created = _now()
        t = datetime.fromisoformat(created.replace("Z", "+00:00"))
        expires = (t + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        intent = {
            "schema_version": "order_intent.v2",
            "intent_id": intent_id,
            "client_order_id": client_order_id,
            "campaign_id": self.campaign["campaign_id"],
            "campaign_revision": self.campaign["revision"],
            "mode": "paper",
            "venue": candidate["venue"],
            "account_alias": candidate["account_alias"],
            "instrument_id": candidate["instrument_id"],
            "side": "buy",
            "purpose": "entry",
            "quantity": decision["executable_quantity"],
            "limit_price": candidate["worst_entry"],
            "time_in_force": "GTC",
            "created_at": created,
            "expires_at": expires,
            "policy_digest": self.digest,
            "grant_generation": grant["generation"],
            "account_state_version": decision["account_state_version"],
            "strategy_version": candidate.get("strategy_version", "fixture-strategy-v1"),
            "fee_snapshot_id": candidate["fee_snapshot_id"],
            "market_snapshot_id": candidate["market_snapshot_id"],
            "decision_id": decision["decision_id"],
            "reservation_id": reservation_id,
            "max_quote_debit": decision["cash_required_usd"],
            "protective_stop_price": candidate["stop"],
            "exit_protocol_id": self.campaign["execution"]["emergency_exit_protocol_id"],
        }
        validate_document(intent)
        avail, reserved = self.store.get_cash(candidate["venue"], candidate["account_alias"])
        debit = amount(decision["cash_required_usd"])
        if amount(avail) < debit:
            raise ContractError("reservation exceeds eligible cash")
        self.store.insert_intent_and_reservation(
            intent,
            grant["grant_id"],
            reservation_id,
            f"cash:{candidate['venue']}:{candidate['account_alias']}",
            decision["cash_required_usd"],
        )
        self.store.set_cash(
            candidate["venue"],
            candidate["account_alias"],
            dstr(amount(avail) - debit),
            dstr(amount(reserved) + debit),
        )
        ack = self.broker.submit(intent, self.writer_permit)
        if ack.result == "ACCEPTED":
            self.store.insert_broker_order(
                intent["venue"], intent["account_alias"], ack.broker_order_id, intent_id, "OPEN"
            )
            self.store.set_intent_state(intent_id, "ACCEPTED")
        elif ack.result == "UNKNOWN":
            self.store.set_intent_state(intent_id, "SUBMISSION_UNKNOWN")
        else:
            self.store.set_intent_state(intent_id, "REJECTED")
            # release reservation
            self.store.set_cash(
                candidate["venue"],
                candidate["account_alias"],
                avail,
                reserved,
            )
        self.store.record_audit(
            self.campaign["campaign_id"],
            "SUBMIT",
            {"intent_id": intent_id, "result": ack.result, "detail": ack.detail},
        )
        return {"intent": intent, "ack": ack}

    def recover_unknown(self, intent: dict[str, Any]) -> dict[str, Any]:
        ack = self.broker.recover_unknown(intent["client_order_id"])
        if ack.result == "ACCEPTED":
            self.store.insert_broker_order(
                intent["venue"], intent["account_alias"], ack.broker_order_id, intent["intent_id"], "OPEN"
            )
            self.store.set_intent_state(intent["intent_id"], "ACCEPTED")
        self.store.record_audit(
            self.campaign["campaign_id"],
            "RECONCILE_UNKNOWN",
            {"intent_id": intent["intent_id"], "result": ack.result},
        )
        return {"ack": ack}

    def apply_fill(
        self,
        broker_order_id: str,
        fill_id: str,
        quantity: Decimal,
        price: Decimal,
        intent: dict[str, Any],
    ) -> dict[str, Any]:
        event = self.broker.fill(broker_order_id, fill_id, quantity, price)
        applied = self.store.insert_fill(event)
        if not applied:
            return {"applied": False, "fill_id": fill_id}
        lot_id = str(uuid.uuid4())
        self.store.insert_lot(
            {
                "lot_id": lot_id,
                "campaign_id": self.campaign["campaign_id"],
                "venue": intent["venue"],
                "account_alias": intent["account_alias"],
                "instrument_id": intent["instrument_id"],
                "quantity_decimal": event["quantity_decimal"],
                "basis_decimal": event["price_decimal"],
                "last_event_ref": fill_id,
                "version": 1,
            }
        )
        stop_id = self.broker.attach_stop(
            broker_order_id, Decimal(event["quantity_decimal"]), intent["protective_stop_price"]
        )
        self.store.insert_protection(
            {
                "protection_id": str(uuid.uuid4()),
                "lot_id": lot_id,
                "state": "CONFIRMED",
                "reserved_quantity_decimal": event["quantity_decimal"],
                "protocol_revision": "paper-stop-v1",
                "orders_json": json.dumps({"stop_id": stop_id, "stop": intent["protective_stop_price"]}),
                "last_evidence_ref": fill_id,
            }
        )
        self.store.set_intent_state(intent["intent_id"], "FILLED" if self.broker.orders[broker_order_id]["state"] == "FILLED" else "PARTIAL")
        self.store.record_audit(
            self.campaign["campaign_id"],
            "FILL",
            {"fill_id": fill_id, "applied": True, "protection": stop_id},
        )
        return {"applied": True, "fill": event, "lot_id": lot_id, "stop_id": stop_id}


def size_candidates(eligible_cash: str, candidates: list[dict[str, Any]], profile: str) -> list[dict[str, Any]]:
    return allocate_funded_weighted_v1(eligible_cash, candidates, profile=profile)
