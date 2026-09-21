"""One Kraken cycle: probe, evaluate, optionally send. No paper fallback."""

from __future__ import annotations

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
from temple_flow.money import dstr, min_entry_notional
from temple_flow.strategies.crypto_spot import evaluate_pullback, evaluate_trend_continuation


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _round_price(value: str, decimals: str | int) -> str:
    q = Decimal("1").scaleb(-int(decimals))
    return str(Decimal(value).quantize(q, rounding=ROUND_DOWN))


def _round_qty(value: str, decimals: str | int) -> str:
    q = Decimal("1").scaleb(-int(decimals))
    return str(Decimal(value).quantize(q, rounding=ROUND_DOWN))


def _stop_present(value: Any) -> bool:
    if value is None or value == "":
        return False
    try:
        return Decimal(str(value)) > 0
    except Exception:
        return False


def _persist_decision(
    store: LedgerStore,
    campaign: dict[str, Any] | None,
    grant: dict[str, Any] | None,
    snap,
    adapter: KrakenAdapter,
    pair: str,
    *,
    result: str,
    reason_codes: list[str],
    cash: Decimal | None,
    net: str | None = None,
    cash_required: str | None = None,
    quantity: str | None = None,
    fee_id: str | None = "kraken-assetpairs",
    market_id: str | None = "kraken-ohlc-ticker",
) -> None:
    if campaign is None or grant is None or not grant.get("policy_digest"):
        return
    if store.get_campaign_revision(campaign["campaign_id"], campaign["revision"]) is None:
        store.record_audit(
            campaign["campaign_id"],
            "DECISION_PERSIST_SKIPPED",
            {"pair": pair, "reason": "missing_campaign_revision"},
        )
        return
    cash_s = dstr(cash) if cash is not None else None
    decision = {
        "schema_version": "decision.v2",
        "decision_id": str(uuid.uuid4()),
        "campaign_id": campaign["campaign_id"],
        "campaign_revision": campaign["revision"],
        "mode": "live",
        "venue": "kraken_spot",
        "account_alias": adapter.account_alias,
        "candidate_id": f"cv-{pair}",
        "result": result,
        "reason_codes": reason_codes,
        "policy_digest": grant["policy_digest"],
        "account_state_version": snap.version,
        "fee_snapshot_id": fee_id,
        "market_snapshot_id": market_id,
        "created_at": _now(),
        "net_edge_usd_estimate": net,
        "cash_required_usd": cash_required,
        "cash_available_usd": cash_s,
        "executable_quantity": quantity,
        "evidence_refs": ["kraken_read"],
        "economic_evidence": campaign.get("economic_evidence") or "EXPERIMENTAL_UNPROVEN",
    }
    try:
        validate_document(decision)
        store.insert_decision(decision)
        store.record_audit(
            campaign["campaign_id"],
            "DECISION",
            {"pair": pair, "result": result, "reason_codes": reason_codes},
        )
    except Exception as exc:
        store.record_audit(
            campaign["campaign_id"],
            "DECISION_PERSIST_FAILED",
            {"pair": pair, "error": str(exc)[:300]},
        )


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
    accepted_this_cycle = False
    for pair in SPOT_PAIRS:
        if PAIR_ASSET.get(pair) in held_assets:
            ev = {"pair": pair, "result": "DECLINE", "reason": "ALREADY_LONG"}
            evaluations.append(ev)
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE", reason_codes=["ALREADY_LONG"], cash=cash,
                fee_id=None, market_id=None,
            )
            continue
        try:
            tick = adapter.ticker(pair)
            bars = adapter.ohlc(pair, 1440)
            fees = adapter.pair_fees(pair)
        except VenueUnavailable as exc:
            evaluations.append({"pair": pair, "result": "DEFER", "reason": str(exc)[:200]})
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DEFER", reason_codes=["VENUE_UNAVAILABLE"], cash=cash,
                fee_id=None, market_id=None,
            )
            continue
        last = tick["last"]
        if last is None:
            evaluations.append({"pair": pair, "result": "DECLINE", "reason": "NO_LAST"})
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE", reason_codes=["NO_LAST"], cash=cash,
            )
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
        leftover = cash or Decimal("0")
        min_n = min_entry_notional(last, fees["ordermin"], fees["taker"])
        ev["min_entry_notional"] = dstr(min_n)
        ev["leftover"] = dstr(leftover)
        evaluations.append(ev)
        if ev.get("result") != "PASS":
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE",
                reason_codes=[str(ev.get("reason") or "NO_SETUP")],
                cash=cash,
                net=ev.get("net"),
            )
            continue
        if not _stop_present(ev.get("stop")):
            ev["send"] = "blocked_stop_missing"
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE", reason_codes=["STOP_MISSING"], cash=cash, net=ev.get("net"),
            )
            continue
        if leftover < min_n:
            ev["send"] = "leftover_below_ordermin"
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE",
                reason_codes=["INELIGIBLE_DUST"],
                cash=cash,
                net=ev.get("net"),
                cash_required=dstr(min_n),
            )
            continue
        if accepted_this_cycle:
            ev["send"] = "same_cycle_one_pair"
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE", reason_codes=["SAME_CYCLE_ONE_PAIR"], cash=cash, net=ev.get("net"),
            )
            continue
        if not (
            send
            and campaign
            and grant
            and campaign.get("mode") == "live"
        ):
            sized = allocate_funded_weighted_v1(
                dstr(leftover),
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
                profile=(campaign or {}).get("profile") or "full_loss_research",
            )
            if sized:
                _persist_decision(
                    store, campaign, grant, snap, adapter, pair,
                    result="PASS",
                    reason_codes=[str(ev.get("reason") or "PASS")],
                    cash=cash,
                    net=ev.get("net"),
                    cash_required=dstr(sized[0]["cash_required"]),
                    quantity=dstr(sized[0]["quantity"]),
                )
            else:
                ev["send"] = "blocked_zero_qty"
                _persist_decision(
                    store, campaign, grant, snap, adapter, pair,
                    result="DECLINE", reason_codes=["INELIGIBLE_DUST"], cash=cash, net=ev.get("net"),
                )
            continue
        runtime = store.runtime(campaign["campaign_id"])
        if runtime is None or runtime["entry_permission"] != "ENABLED":
            ev["send"] = "blocked_disarmed"
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE", reason_codes=["DISARMED"], cash=cash, net=ev.get("net"),
            )
            continue
        lease = WriterLease(state_dir, "kraken_spot", adapter.account_alias)
        permit = lease.permit()
        if not permit:
            ev["send"] = "blocked_no_writer"
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE", reason_codes=["NO_WRITER"], cash=cash, net=ev.get("net"),
            )
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
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE", reason_codes=["INELIGIBLE_DUST"], cash=cash, net=ev.get("net"),
            )
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
        if not _stop_present(intent["protective_stop_price"]):
            ev["send"] = "blocked_stop_missing"
            _persist_decision(
                store, campaign, grant, snap, adapter, pair,
                result="DECLINE", reason_codes=["STOP_MISSING"], cash=cash, net=ev.get("net"),
            )
            continue
        validate_document(intent)
        _persist_decision(
            store, campaign, grant, snap, adapter, pair,
            result="PASS",
            reason_codes=[str(ev.get("reason") or "PASS")],
            cash=cash,
            net=ev.get("net"),
            cash_required=dstr(sized[0]["cash_required"]),
            quantity=intent["quantity"],
        )
        ack = adapter.submit(intent, permit)
        submitted.append({"pair": pair, "result": ack.result, "order_id": ack.broker_order_id, "detail": ack.detail})
        store.record_audit(campaign["campaign_id"], "KRAKEN_SUBMIT", submitted[-1])
        if ack.result == "ACCEPTED":
            accepted_this_cycle = True
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
