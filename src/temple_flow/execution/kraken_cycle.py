"""One Kraken cycle: probe, evaluate, optionally send. No paper fallback."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

from temple_flow.adapters.kraken import PAIR_ASSET, SPOT_PAIRS, KrakenAdapter
from temple_flow.adapters.protocol import VenueUnavailable
from temple_flow.allocation.allocator import allocate_funded_weighted_v1
from temple_flow.campaign.contracts import validate_document
from temple_flow.execution.writer import WriterLease
from temple_flow.ledger.store import LedgerStore
from temple_flow.money import dstr
from temple_flow.strategies.crypto_spot import evaluate_pullback, evaluate_trend_continuation


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _round_price(value: str, decimals: str | int) -> str:
    q = Decimal("1").scaleb(-int(decimals))
    return str(Decimal(value).quantize(q, rounding=ROUND_DOWN))


def _round_qty(value: str, decimals: str | int) -> str:
    q = Decimal("1").scaleb(-int(decimals))
    return str(Decimal(value).quantize(q, rounding=ROUND_DOWN))


def run_kraken_cycle(
    store: LedgerStore,
    state_dir,
    campaign: dict[str, Any] | None,
    grant: dict[str, Any] | None,
    *,
    send: bool,
) -> dict[str, Any]:
    adapter = KrakenAdapter()
    try:
        snap = adapter.snapshot()
    except VenueUnavailable as exc:
        return {"ok": False, "unavailable": str(exc), "submitted": False}
    cash = snap.cash_available
    # Kraken Balance can still show ZUSD while a buy rests. Subtract working buy notional.
    for o in snap.working_orders:
        if (o.side or "").upper() == "BUY" and o.remaining and o.price:
            cash = (cash or Decimal("0")) - (o.remaining * o.price)
            if cash < 0:
                cash = Decimal("0")
    held_assets = {p.symbol for p in snap.positions if p.qty and p.qty > 0}
    poc_trend = bool((campaign or {}).get("execution", {}).get("poc_trend_continuation"))
    evaluations = []
    submitted = []
    for pair in SPOT_PAIRS:
        if PAIR_ASSET.get(pair) in held_assets:
            evaluations.append({"pair": pair, "result": "DECLINE", "reason": "ALREADY_LONG"})
            continue
        try:
            tick = adapter.ticker(pair)
            bars = adapter.ohlc(pair, 1440)
            fees = adapter.pair_fees(pair)
        except VenueUnavailable as exc:
            evaluations.append({"pair": pair, "result": "DEFER", "reason": str(exc)[:200]})
            continue
        last = tick["last"]
        if last is None:
            evaluations.append({"pair": pair, "result": "DECLINE", "reason": "NO_LAST"})
            continue
        cash_s = dstr(cash) if cash is not None else "0"
        ev = evaluate_pullback(
            pair,
            bars,
            last,
            fees["taker"],
            fees["maker"],
            cash_s,
            fees["ordermin"],
        )
        if ev.get("result") != "PASS" and poc_trend:
            trend = evaluate_trend_continuation(
                pair,
                bars,
                last,
                fees["taker"],
                fees["maker"],
                cash_s,
                fees["ordermin"],
            )
            if trend.get("result") == "PASS":
                ev = trend
            else:
                ev["trend_reason"] = trend.get("reason")
        elif ev.get("result") != "PASS":
            ev["trend_reason"] = "poc_trend_continuation_off"
        ev["last"] = dstr(last)
        ev["fees"] = fees
        evaluations.append(ev)
        if not (
            send
            and ev.get("result") == "PASS"
            and campaign
            and grant
            and campaign.get("mode") == "live"
        ):
            continue
        runtime = store.runtime(campaign["campaign_id"])
        if runtime is None or runtime["entry_permission"] != "ENABLED":
            ev["send"] = "blocked_disarmed"
            continue
        lease = WriterLease(state_dir, "kraken_spot", adapter.account_alias)
        permit = lease.permit()
        if not permit:
            ev["send"] = "blocked_no_writer"
            continue
        sized = allocate_funded_weighted_v1(
            dstr(cash),
            [
                {
                    "candidate_id": f"cv-{pair}",
                    "venue": "kraken_spot",
                    "instrument_id": pair,
                    "weight": ev["weight"],
                    "worst_entry": ev["worst_entry"],
                    "modeled_exit": ev["modeled_exit"],
                    "entry_fee_fraction": ev["entry_fee_fraction"],
                    "exit_fee_fraction": ev["exit_fee_fraction"],
                    "increment": ev["increment"],
                }
            ],
            profile=campaign["profile"],
        )
        if not sized:
            ev["send"] = "blocked_zero_qty"
            continue
        qty = sized[0]["quantity"]
        created = _now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        intent = {
            "schema_version": "order_intent.v2",
            "intent_id": str(uuid.uuid4()),
            "client_order_id": str(uuid.uuid4()),
            "campaign_id": campaign["campaign_id"],
            "campaign_revision": campaign["revision"],
            "mode": "live",
            "venue": "kraken_spot",
            "account_alias": adapter.account_alias,
            "instrument_id": pair,
            "side": "buy",
            "purpose": "entry",
            "quantity": dstr(qty),
            "limit_price": ev["limit"],
            "time_in_force": "GTC",
            "created_at": created,
            "expires_at": expires,
            "policy_digest": grant["policy_digest"],
            "grant_generation": grant["generation"],
            "account_state_version": snap.version,
            "strategy_version": ("crypto_spot_trend_poc_v0" if ev.get("reason") == "TREND_CONTINUATION_POC" else "crypto_spot_pullback_v0"),
            "fee_snapshot_id": "kraken-assetpairs",
            "market_snapshot_id": "kraken-ohlc-ticker",
            "decision_id": str(uuid.uuid4()),
            "reservation_id": str(uuid.uuid4()),
            "max_quote_debit": dstr(sized[0]["cash_required"]),
            "protective_stop_price": ev["stop"],
            "exit_protocol_id": campaign["execution"]["emergency_exit_protocol_id"],
        }
        # Kraken rejects excess decimals (AssetPairs pair_decimals / lot_decimals).
        intent["limit_price"] = _round_price(intent["limit_price"], fees["pair_decimals"])
        intent["protective_stop_price"] = _round_price(intent["protective_stop_price"], fees["pair_decimals"])
        intent["quantity"] = _round_qty(intent["quantity"], fees["lot_decimals"])
        validate_document(intent)
        ack = adapter.submit(intent, permit)
        submitted.append({"pair": pair, "result": ack.result, "order_id": ack.broker_order_id, "detail": ack.detail})
        store.record_audit(campaign["campaign_id"], "KRAKEN_SUBMIT", submitted[-1])
        if ack.result == "ACCEPTED":
            # Do not double-spend the same ZUSD across pairs in one cycle.
            try:
                cash = (cash or Decimal("0")) - Decimal(str(sized[0]["cash_required"]))
                if cash < 0:
                    cash = Decimal("0")
            except Exception:
                cash = Decimal("0")
    return {
        "ok": True,
        "source": snap.source,
        "cash": dstr(cash) if cash is not None else None,
        "positions": [{"symbol": p.symbol, "qty": dstr(p.qty)} for p in snap.positions],
        "evaluations": evaluations,
        "submitted": submitted,
        "economic_evidence": "EXPERIMENTAL_UNPROVEN",
    }
