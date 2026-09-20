"""Immutable policy digest. Disabled caps are explicit, never omitted."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from temple_flow.campaign.contracts import ContractError, validate_document

LEGACY_UNIVERSAL_CAPS = (
    ("per_position_risk", "0.025"),
    ("daily_loss", "0.045"),
    ("peak_drawdown", "0.18"),
    ("position_notional", "0.18"),
    ("ticket_notional", "0.35"),
)


def canonical_definition(doc: dict[str, Any]) -> dict[str, Any]:
    """Definition bytes that GO binds. Activation grant fields are excluded."""
    body = {k: v for k, v in doc.items() if k != "activation"}
    return json.loads(json.dumps(body, sort_keys=True))


def policy_digest(doc: dict[str, Any]) -> str:
    payload = json.dumps(canonical_definition(doc), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assert_profile_explicit(doc: dict[str, Any]) -> None:
    validate_document(doc)
    if doc["profile"] != "full_loss_research":
        return
    limits = doc["optional_limits"]
    if any(check["enabled"] for check in limits.values()):
        raise ContractError("full_loss_research must explicitly disable optional limits")
    if limits["position_count"]["limit_count"] is not None:
        raise ContractError("full_loss_research must not restore a position-count cap")
    for key, inherited in LEGACY_UNIVERSAL_CAPS:
        if limits[key]["limit_fraction"] == inherited:
            raise ContractError(f"full_loss_research silently restored {key}={inherited}")
    if doc["execution"]["per_trade_human_approval"] is not False:
        raise ContractError("campaign execution must not require per-trade human approval")
    if doc["execution"]["borrow"] or doc["execution"]["short"] or doc["execution"]["derivatives"]:
        raise ContractError("funded long/flat only")
