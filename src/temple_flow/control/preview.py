"""Build a LIVE campaign preview from real venue probes. Never use the $100 fixture."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from temple_flow.campaign.policy import policy_digest
from temple_flow.money import dstr


def compile_live_definition(probe: dict[str, Any]) -> dict[str, Any]:
    venues = []
    basis = Decimal("0")
    snapshot_parts = []
    for venue, rec in (probe.get("venues") or {}).items():
        if rec.get("capability_status") == "UNAVAILABLE" or rec.get("snapshot_source") is None:
            continue
        cash = rec.get("cash_available")
        if cash is None:
            continue
        alias = "SCHWAB_RESEARCH" if venue == "schwab" else "KRAKEN_RESEARCH"
        pos_id = f"{rec['snapshot_source']}:{venue}"
        venues.append(
            {
                "venue": venue,
                "account_alias": alias,
                "allocation_usd": str(cash),
                "positions_snapshot_id": pos_id,
                "eligibility_policy_id": (
                    "cash-equity-unleveraged-etf"
                    if venue == "schwab"
                    else "accessible-usd-spot"
                ),
            }
        )
        basis += Decimal(str(cash))
        snapshot_parts.append(pos_id)
    if not venues:
        raise ValueError("no live venue snapshot is available; not substituting paper cash")
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": "campaign.v2",
        "campaign_id": "TF-CAMPAIGN-LIVE",
        "revision": 1,
        "definition_state": "prepared",
        "mode": "live",
        "purpose": "Live full-loss research campaign compiled from actual broker reads. Not the paper $100 fixture.",
        "economic_evidence": "EXPERIMENTAL_UNPROVEN",
        "profile": "full_loss_research",
        "total_allocation_loss_accepted": True,
        "capital_floor_usd": "0",
        "capital": {
            "adoption_mode": "snapshot_at_go",
            "snapshot_id": "+".join(snapshot_parts),
            "basis_net_usd": dstr(basis),
            "venues": venues,
            "allow_future_deposits": False,
            "compound_realized_gains": True,
        },
        "objective": {
            "kind": "none",
            "multiple": None,
            "on_reach": "stop_entries_and_exit_owned_positions",
            "success_basis": "reconciled_net_exit_value",
            "shortfall_action": "report_and_remain_stopped",
        },
        "execution": {
            "borrow": False,
            "short": False,
            "auto_transfer": False,
            "derivatives": False,
            "per_trade_human_approval": False,
            "native_protection_required": True,
            "single_writer_per_account": True,
            "continuous_kraken_eligibility": True,
            "schwab_session_policy": "verified_route_and_account_sessions",
            "sizing_policy_id": "funded_weighted_v1",
            "strategy_registry_id": "equity_pullback_v1+crypto_to_qualify",
            "parameter_envelope_id": "live-envelope-v1",
            "emergency_exit_protocol_id": "native-stop-then-flatten",
            "external_service_budget_id": "zero-extra-model-spend",
            "poc_trend_continuation": False,
        },
        "optional_limits": {
            "per_position_risk": {
                "enabled": False,
                "limit_fraction": None,
                "reason": "Explicit full-loss research selection; no inherited percentage",
            },
            "daily_loss": {
                "enabled": False,
                "limit_fraction": None,
                "reason": "Explicit full-loss research selection; no inherited percentage",
            },
            "peak_drawdown": {
                "enabled": False,
                "limit_fraction": None,
                "reason": "Explicit full-loss research selection; no inherited percentage",
            },
            "position_notional": {
                "enabled": False,
                "limit_fraction": None,
                "reason": "Explicit full-loss research selection; no inherited percentage",
            },
            "ticket_notional": {
                "enabled": False,
                "limit_fraction": None,
                "reason": "Explicit full-loss research selection; no inherited percentage",
            },
            "position_count": {
                "enabled": False,
                "limit_count": None,
                "reason": "Funded resources and venue capacities, not a name-count ceiling",
            },
        },
        "activation": {
            "enabled": False,
            "grant_id": None,
            "deployment_receipt_id": None,
            "policy_digest": None,
        },
    }


def render_preview_markdown(probe: dict[str, Any], definition: dict[str, Any] | None, error: str | None) -> str:
    digest = policy_digest(definition) if definition else None
    lines = [
        "# LIVE campaign preview",
        "",
        "**Not the paper $100→$200 fixture. Paper digest confers no live authority.**",
        "",
        f"Service mode: `{probe.get('mode')}` · entries `{probe.get('entry_permission')}`",
        "",
        "## Venue reads",
        "",
    ]
    for venue, rec in (probe.get("venues") or {}).items():
        lines.append(f"### {venue}")
        lines.append("")
        lines.append(f"- capability: `{rec.get('capability_status')}`")
        lines.append(f"- source: `{rec.get('snapshot_source')}`")
        if rec.get("unavailable"):
            lines.append(f"- unavailable: {rec['unavailable']}")
        lines.append(f"- cash_available: `{rec.get('cash_available')}`")
        lines.append(f"- equity: `{rec.get('equity')}`")
        lines.append(f"- positions: `{json.dumps(rec.get('positions') or [])}`")
        lines.append(f"- working_orders: `{json.dumps(rec.get('working_orders') or [])}`")
        lines.append("")
    if error:
        lines.append("## Not compiled")
        lines.append("")
        lines.append(error)
        lines.append("")
        lines.append("No simulated cash was substituted.")
        return "\n".join(lines)
    assert definition is not None
    lines += [
        "## Resolved live definition (unarmed until exclusive writer)",
        "",
        f"- campaign_id: `{definition['campaign_id']}`",
        f"- revision: `{definition['revision']}`",
        f"- profile: `{definition['profile']}`",
        f"- basis_net_usd: `{definition['capital']['basis_net_usd']}` (sum of proven venue cash, not a target)",
        f"- snapshot_id: `{definition['capital']['snapshot_id']}`",
        f"- policy_digest: `{digest}`",
        f"- objective: `{definition['objective']['kind']}` (no $200 carry-over)",
        f"- per_trade_human_approval: `{definition['execution']['per_trade_human_approval']}`",
        f"- inherited %/count caps: all `enabled: false`",
        "",
        "GO against this digest accepts this revision. Existing broker stops stay in place.",
        "New sends stay DISARMED until `desk claim-writer` on the exclusive host.",
        "",
        "Engineering verification ≠ profitability.",
    ]
    return "\n".join(lines)


def write_preview(path: Path, probe: dict[str, Any], definition: dict[str, Any] | None, error: str | None) -> str:
    text = render_preview_markdown(probe, definition, error)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")
    if definition:
        (path.parent / "campaign.live.prepared.json").write_text(
            json.dumps({k: v for k, v in definition.items() if not str(k).startswith("_")}, indent=2)
            + "\n"
        )
    return text
