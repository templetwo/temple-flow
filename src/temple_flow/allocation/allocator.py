"""funded_weighted_v1 — resource allocator, not a profitability proof."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Any

from temple_flow.money import MoneyError, amount, dstr, entry_debit, funded_quantity, round_trip_net


def allocate_funded_weighted_v1(
    eligible_cash: str,
    candidates: list[dict[str, Any]],
    *,
    profile: str,
) -> list[dict[str, Any]]:
    """Return sized candidates. Full-loss has no inherited 18%/35%/2.5% term."""
    cash = amount(eligible_cash)
    eligible: list[dict[str, Any]] = []
    for c in candidates:
        w = c.get("weight")
        try:
            weight = Decimal(str(w))
        except Exception as exc:
            raise MoneyError("weight must be a finite decimal") from exc
        if weight.is_nan() or weight.is_infinite() or weight < 0:
            raise MoneyError("weight must be finite and nonnegative")
        if weight == 0:
            continue
        eligible.append({**c, "weight": weight})
    if not eligible:
        return []
    # coalesce same instrument: highest priority then id
    by_inst: dict[str, dict[str, Any]] = {}
    for c in eligible:
        key = f"{c['venue']}:{c['instrument_id']}"
        prev = by_inst.get(key)
        if prev is None or (c.get("priority", 0), c["candidate_id"]) > (
            prev.get("priority", 0),
            prev["candidate_id"],
        ):
            by_inst[key] = c
    chosen = list(by_inst.values())
    total_w = sum((c["weight"] for c in chosen), Decimal(0))
    out = []
    for c in sorted(chosen, key=lambda x: (-x.get("priority", 0), x["candidate_id"])):
        share = cash if (profile == "full_loss_research" and len(chosen) == 1) else (cash * c["weight"] / total_w)
        price = amount(c["worst_entry"])
        fee = amount(c["entry_fee_fraction"])
        increment = amount(c.get("increment", "0.01"))
        q_cash = funded_quantity(dstr(share), dstr(price), dstr(fee), dstr(increment))
        if "desired_notional" in c:
            q_strat = amount(c["desired_notional"]) / price
            if q_strat < q_cash:
                q_cash = (q_strat / increment).to_integral_value(rounding=ROUND_FLOOR) * increment
        if q_cash <= 0:
            continue
        debit = entry_debit(q_cash, price, fee)
        net = round_trip_net(
            dstr(q_cash),
            dstr(price),
            c["modeled_exit"],
            dstr(fee),
            c["exit_fee_fraction"],
        )
        out.append(
            {
                **c,
                "quantity": q_cash,
                "cash_required": debit,
                "net_edge": net,
            }
        )
    return out
