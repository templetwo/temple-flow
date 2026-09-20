"""Campaign/decision/intent shape + semantic checks.

Success is not a grant. Production still requires a trusted receipt and writer
permit at the send boundary.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from temple_flow.money import MoneyError, amount

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "schemas"
SCHEMA_FILES = {
    "campaign.v2": "campaign.v2.schema.json",
    "order_intent.v2": "order_intent.v2.schema.json",
    "decision.v2": "decision.v2.schema.json",
}


class ContractError(ValueError):
    """A supplied contract does not satisfy a declared requirement."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_document(doc: dict[str, Any]) -> None:
    filename = SCHEMA_FILES.get(doc.get("schema_version", ""))
    _require(filename is not None, "Unknown schema version")
    schema = json.loads((SCHEMAS_DIR / filename).read_text())
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(doc),
        key=lambda error: str(list(error.path)),
    )
    if errors:
        raise ContractError("; ".join(f"{list(e.path)}: {e.message}" for e in errors))
    version = doc["schema_version"]
    if version == "campaign.v2":
        _validate_campaign(doc)
    elif version == "order_intent.v2":
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
        _require(
            not any(x["enabled"] for x in limits.values()),
            "Full-loss profile has inherited optional cap",
        )
        forbidden = {
            "0.025",
            "0.045",
            "0.18",
            "0.35",
        }
        for key, check in limits.items():
            if key == "position_count":
                _require(check["limit_count"] is None, "Full-loss must not carry a count cap")
            else:
                _require(
                    check["limit_fraction"] not in forbidden,
                    f"Full-loss must not restore inherited {key}",
                )
    else:
        _require(selected_loss_boundary, "Bounded profile has no selected loss boundary")
    keys = [(v["venue"], v["account_alias"]) for v in doc["capital"]["venues"]]
    _require(len(keys) == len(set(keys)), "Duplicate venue/account allocation")
    objective = doc["objective"]
    if objective["kind"] == "none":
        _require(objective["multiple"] is None, "Disabled objective must not carry a target")
    else:
        _require(
            objective["multiple"] is not None and amount(objective["multiple"]) > 1,
            "Target multiple must exceed one",
        )
    if doc["definition_state"] == "prepared":
        capital = doc["capital"]
        _require(capital["snapshot_id"] is not None, "Prepared snapshot absent")
        _require(
            capital["basis_net_usd"] is not None and amount(capital["basis_net_usd"]) > 0,
            "Prepared basis absent or empty",
        )
        for v in capital["venues"]:
            _require(
                v["allocation_usd"] is not None and v["positions_snapshot_id"] is not None,
                "Unresolved prepared allocation",
            )
        total = sum((amount(v["allocation_usd"]) for v in capital["venues"]), Decimal(0))
        _require(total == amount(capital["basis_net_usd"]), "Sleeves do not reconcile to campaign basis")
        _require(amount(doc["capital_floor_usd"]) < total, "Floor must be below starting basis")
        for key in [
            "sizing_policy_id",
            "strategy_registry_id",
            "parameter_envelope_id",
            "emergency_exit_protocol_id",
            "external_service_budget_id",
        ]:
            _require(not doc["execution"][key].startswith("UNRESOLVED_"), f"Prepared {key} unresolved")
    if doc["activation"]["enabled"]:
        _require(doc["definition_state"] == "prepared", "Draft cannot activate")
        for field in ["grant_id", "deployment_receipt_id", "policy_digest"]:
            _require(doc["activation"][field] is not None, f"Activation missing {field}")


def _validate_intent(doc: dict[str, Any]) -> None:
    quantity, price = amount(doc["quantity"]), amount(doc["limit_price"])
    _require(quantity > 0 and price > 0, "Quantity and limit price must be positive")
    _require(_time(doc["expires_at"]) > _time(doc["created_at"]), "Intent validity interval is empty")
    if doc["purpose"] == "entry":
        _require(doc["side"] == "buy", "Cash long/flat entry must buy")
        _require(doc["protective_stop_price"] is not None, "Entry protection absent")
        _require(0 < amount(doc["protective_stop_price"]) < price, "Invalid long entry stop")
        _require(
            amount(doc["max_quote_debit"]) >= quantity * price,
            "Entry reservation below gross debit",
        )
    else:
        _require(doc["side"] == "sell", "Cash long/flat exit must sell")


def _validate_decision(doc: dict[str, Any]) -> None:
    if doc["result"] != "PASS":
        return
    for field in [
        "fee_snapshot_id",
        "market_snapshot_id",
        "net_edge_usd_estimate",
        "cash_required_usd",
        "cash_available_usd",
        "executable_quantity",
    ]:
        _require(doc[field] is not None, f"PASS missing {field}")
    try:
        edge = Decimal(doc["net_edge_usd_estimate"])
    except Exception as exc:
        raise ContractError("PASS net edge is not a decimal") from exc
    _require(edge > 0, "Entry PASS requires positive modelled net edge")
    _require(amount(doc["executable_quantity"]) > 0, "PASS quantity must be positive")
    _require(
        amount(doc["cash_required_usd"]) <= amount(doc["cash_available_usd"]),
        "PASS exceeds available resources",
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


# Re-export MoneyError so tests can treat bad decimals as contract failures.
ContractError = ContractError  # noqa: PLW0127
MoneyError = MoneyError
