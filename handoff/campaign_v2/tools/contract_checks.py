"""Offline build-contract checks only. No networking, authentication or trading.

These functions demonstrate shape/semantic requirements and exact arithmetic.
They are not the production Risk engine and do not establish execution authority.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR, localcontext
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
DECIMAL_RE = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
SCHEMAS = {
    "campaign.v2": "campaign.v2.schema.json",
    "order_intent.v2": "order_intent.v2.schema.json",
    "decision.v2": "decision.v2.schema.json",
}


class ContractError(ValueError):
    """A supplied offline contract does not satisfy a declared requirement."""


def amount(value: Any) -> Decimal:
    """Accept canonical nonnegative decimal strings; reject floats and NaN."""
    if not isinstance(value, str) or DECIMAL_RE.fullmatch(value) is None:
        raise ContractError("Expected a nonnegative decimal string, not a float")
    return Decimal(value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_document(doc: dict[str, Any]) -> None:
    """Shape plus local semantics; success does NOT grant authority to trade."""
    filename = SCHEMAS.get(doc.get("schema_version", ""))
    _require(filename is not None, "Unknown schema version")
    schema = json.loads((ROOT / "contracts" / str(filename)).read_text())
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(doc),
        key=lambda error: str(list(error.path)),
    )
    if errors:
        raise ContractError("; ".join(f"{list(e.path)}: {e.message}" for e in errors))
    if doc["schema_version"] == "campaign.v2":
        _validate_campaign(doc)
    elif doc["schema_version"] == "order_intent.v2":
        _validate_intent(doc)
    else:
        _validate_decision(doc)


def _validate_campaign(doc: dict[str, Any]) -> None:
    limits = doc["optional_limits"]
    selected_loss_boundary = amount(doc["capital_floor_usd"]) > 0
    for key, check in limits.items():
        field = "limit_count" if key == "position_count" else "limit_fraction"
        value = check[field]
        if check["enabled"]:
            _require(value is not None, f"Enabled {key} needs a limit")
            if field == "limit_fraction":
                _require(Decimal(0) < amount(value) <= Decimal(1), f"Invalid {key} fraction")
            if key in {"daily_loss", "peak_drawdown", "per_position_risk"}:
                selected_loss_boundary = True
        else:
            _require(value is None, f"Disabled {key} must not carry an active limit")
    if doc["profile"] == "full_loss_research":
        _require(doc["total_allocation_loss_accepted"], "Full-loss consent absent")
        _require(amount(doc["capital_floor_usd"]) == 0, "Full-loss floor must be explicit zero")
        _require(not any(x["enabled"] for x in limits.values()), "Full-loss profile has inherited optional cap")
    else:
        _require(selected_loss_boundary, "Bounded profile has no selected loss boundary")
    keys = [(v["venue"], v["account_alias"]) for v in doc["capital"]["venues"]]
    _require(len(keys) == len(set(keys)), "Duplicate venue/account allocation")
    objective = doc["objective"]
    if objective["kind"] == "none":
        _require(objective["multiple"] is None, "Disabled objective must not carry a target")
    else:
        _require(objective["multiple"] is not None and amount(objective["multiple"]) > 1, "Target multiple must exceed one")
    if doc["definition_state"] == "prepared":
        capital = doc["capital"]
        _require(capital["snapshot_id"] is not None, "Prepared snapshot absent")
        _require(capital["basis_net_usd"] is not None and amount(capital["basis_net_usd"]) > 0, "Prepared basis absent or empty")
        for v in capital["venues"]:
            _require(v["allocation_usd"] is not None and v["positions_snapshot_id"] is not None, "Unresolved prepared allocation")
        total = sum((amount(v["allocation_usd"]) for v in capital["venues"]), Decimal(0))
        _require(total == amount(capital["basis_net_usd"]), "Sleeves do not reconcile to campaign basis")
        _require(amount(doc["capital_floor_usd"]) < total, "Floor must be below starting basis")
        for key in ["sizing_policy_id", "strategy_registry_id", "parameter_envelope_id", "emergency_exit_protocol_id", "external_service_budget_id"]:
            _require(not doc["execution"][key].startswith("UNRESOLVED_"), f"Prepared {key} unresolved")
    if doc["activation"]["enabled"]:
        _require(doc["definition_state"] == "prepared", "Draft cannot activate")
        for field in ["grant_id", "deployment_receipt_id", "policy_digest"]:
            _require(doc["activation"][field] is not None, f"Activation missing {field}")
        # Deliberately do not authenticate these strings or return a writer permit.
        # Production must resolve trusted receipt records and current revocations.


def _validate_intent(doc: dict[str, Any]) -> None:
    quantity, price = amount(doc["quantity"]), amount(doc["limit_price"])
    _require(quantity > 0 and price > 0, "Quantity and limit price must be positive")
    _require(_time(doc["expires_at"]) > _time(doc["created_at"]), "Intent validity interval is empty")
    if doc["purpose"] == "entry":
        _require(doc["side"] == "buy", "Cash long/flat entry must buy")
        _require(doc["protective_stop_price"] is not None, "Entry protection absent")
        _require(0 < amount(doc["protective_stop_price"]) < price, "Invalid long entry stop")
        _require(amount(doc["max_quote_debit"]) >= quantity * price, "Entry reservation below gross debit")
    else:
        _require(doc["side"] == "sell", "Cash long/flat exit must sell")
    # Actual fees, tick/lot rules, spot sellable units, trusted state and
    # protection capabilities must be checked by the production adapter/Risk.


def _validate_decision(doc: dict[str, Any]) -> None:
    if doc["result"] != "PASS":
        return
    for field in ["fee_snapshot_id", "market_snapshot_id", "net_edge_usd_estimate", "cash_required_usd", "cash_available_usd", "executable_quantity"]:
        _require(doc[field] is not None, f"PASS missing {field}")
    _require(Decimal(doc["net_edge_usd_estimate"]) > 0, "Entry PASS requires positive modelled net edge")
    _require(amount(doc["executable_quantity"]) > 0, "PASS quantity must be positive")
    _require(amount(doc["cash_required_usd"]) <= amount(doc["cash_available_usd"]), "PASS exceeds available resources")


def funded_quantity(cash: str, price: str, entry_fee_fraction: str, increment: str) -> Decimal:
    """Illustrative all-eligible-cash ceiling, NOT a strategy size recommendation."""
    c, p, fee, step = map(amount, [cash, price, entry_fee_fraction, increment])
    _require(p > 0 and step > 0 and fee < 1, "Invalid price, increment or fee")
    with localcontext() as ctx:
        ctx.prec = 50
        raw = c / (p * (1 + fee))
        q = (raw / step).to_integral_value(rounding=ROUND_FLOOR) * step
        _require(q * p * (1 + fee) <= c, "Rounded reservation exceeds funds")
        return q


def round_trip_net(qty: str, buy: str, sell: str, entry_fee: str, exit_fee: str) -> Decimal:
    """Exact quote-currency-fee example. Execution prices already include spread."""
    q, a, b, fi, fo = map(amount, [qty, buy, sell, entry_fee, exit_fee])
    _require(fi < 1 and fo < 1, "Fee fraction invalid")
    with localcontext() as ctx:
        ctx.prec = 50
        return q * b * (1 - fo) - q * a * (1 + fi)


def flow_adjusted_pnl(start: str, end: str, contributions: str, distributions: str) -> Decimal:
    """Period P&L only; this is not a time-weighted return implementation."""
    s, e, c, d = map(amount, [start, end, contributions, distributions])
    return e - s - c + d


if __name__ == "__main__":
    paths = sorted((ROOT / "examples").glob("*.json"))
    for path in paths:
        validate_document(json.loads(path.read_text()))
        print(f"OK offline contract: {path.name}")
    print(f"{len(paths)} examples validated; no authority issued and no network calls made.")
