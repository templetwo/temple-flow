"""Schwab venue adapter. Read-only unless a live writer permit is presented.

Wraps spiral-broker TokenManager. Does not import temple_flow_wire.
Does not substitute fallback_book / paper balances.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from temple_flow.adapters.credentials import broker_root, load_env_files, present
from temple_flow.adapters.protocol import (
    AccountSnapshot,
    CapabilitySnapshot,
    Position,
    SubmitAck,
    VenueUnavailable,
    WorkingOrder,
    dec,
)

BASE = "https://api.schwabapi.com"
PAPER_DIGEST_FORBIDDEN = True


def flatten_orders(raw: list) -> list:
    out: list = []
    for o in raw or []:
        out.append(o)
        out.extend(flatten_orders(o.get("childOrderStrategies") or []))
    return out


def normalize_schwab_orders(raw: list) -> list[WorkingOrder]:
    orders: list[WorkingOrder] = []
    for o in flatten_orders(raw):
        legs = o.get("orderLegCollection") or []
        symbol = None
        side = ""
        if legs:
            inst = legs[0].get("instrument") or {}
            symbol = inst.get("symbol")
            ins = " ".join(str(leg.get("instruction") or "") for leg in legs)
            if "BUY" in ins:
                side = "BUY"
            elif "SELL" in ins:
                side = "SELL"
        oid = o.get("orderId")
        if oid is None:
            continue
        orders.append(
            WorkingOrder(
                broker_order_id=str(oid),
                symbol=symbol,
                side=side,
                status=str(o.get("status") or ""),
                order_type=o.get("orderType"),
                price=dec(o.get("price")),
                stop_price=dec(o.get("stopPrice")),
                qty=dec(o.get("quantity")),
                filled_qty=dec(o.get("filledQuantity")),
                remaining=dec(o.get("remainingQuantity")),
                duration=o.get("duration"),
                parent_id=str(o["parentOrderId"]) if o.get("parentOrderId") else None,
                raw={"status": o.get("status"), "type": o.get("orderType")},
            )
        )
    return orders


class SchwabAdapter:
    venue = "schwab"

    def __init__(self, account_alias: str = "SCHWAB_RESEARCH"):
        self.account_alias = account_alias
        self._version = 1

    def _auth(self) -> tuple[dict[str, str], str]:
        load_env_files()
        root = broker_root()
        if not (root / "src" / "token_manager.py").exists():
            raise VenueUnavailable("schwab: spiral-broker not on this machine")
        flags = present(["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SCHWAB_ACCOUNT_HASH"])
        missing = [k for k, ok in flags.items() if not ok]
        if missing:
            raise VenueUnavailable("schwab: missing " + ",".join(missing))
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from src.token_manager import TokenManager  # type: ignore

        token_file = root / ".schwab_tokens.json"
        tm = TokenManager(token_file=str(token_file) if token_file.exists() else None)
        st = tm.get_token_status()
        if isinstance(st, dict) and (
            st.get("status") == "refresh_expired" or st.get("refresh_valid") is False
        ):
            raise VenueUnavailable("schwab: oauth_required status=" + str(st.get("status")))
        token = tm.get_token()
        acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "").strip()
        if not acct:
            raise VenueUnavailable("schwab: missing_account_hash")
        headers = {"Authorization": "Bearer " + token}
        return headers, acct

    def capabilities(self) -> CapabilitySnapshot:
        try:
            self._auth()
            status = "DOCUMENTED_ONLY"
            note_ok = True
        except VenueUnavailable:
            note_ok = False
            status = "UNAVAILABLE"
        return CapabilitySnapshot(
            venue=self.venue,
            account_alias=self.account_alias,
            features={
                "account_snapshot": "ACCOUNT_VERIFIED" if note_ok else "UNAVAILABLE",
                "native_stop_on_entry": "DOCUMENTED_ONLY",
                "submit": "UNAVAILABLE" if not note_ok else "DOCUMENTED_ONLY",
                "borrow": "UNSUPPORTED",
                "short": "UNSUPPORTED",
                "fee_schedule": "UNKNOWN",
            },
            as_of=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            status=status,
        )

    def snapshot(self) -> AccountSnapshot:
        import requests  # type: ignore

        headers, acct = self._auth()
        now = datetime.now(timezone.utc)
        as_of = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        def get(path: str, params: dict | None = None):
            return requests.get(BASE + path, headers=headers, params=params, timeout=30)

        r = get("/trader/v1/accounts", {"fields": "positions"})
        if r.status_code != 200:
            raise VenueUnavailable(f"schwab: accounts_http={r.status_code}")
        raw = r.json()
        positions: list[Position] = []
        equity = cash = sod = None
        for item in raw if isinstance(raw, list) else [raw]:
            a = item.get("securitiesAccount") or item.get("account") or item
            cb = a.get("currentBalances") or {}
            ib = a.get("initialBalances") or {}
            equity = cb.get("liquidationValue") or cb.get("equity") or equity
            cash = cb.get("cashBalance") or cb.get("availableFunds") or cash
            sod = ib.get("liquidationValue") or ib.get("equity") or sod
            for p in a.get("positions") or []:
                inst = p.get("instrument") or {}
                positions.append(
                    Position(
                        symbol=str(inst.get("symbol") or ""),
                        qty=dec(p.get("longQuantity") or p.get("quantity")) or Decimal("0"),
                        avg=dec(p.get("averagePrice")),
                        market_value=dec(p.get("marketValue")),
                        day_pl=dec(p.get("currentDayProfitLoss")),
                    )
                )

        frm = (now - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        ro = get(
            f"/trader/v1/accounts/{acct}/orders",
            {"fromEnteredTime": frm, "toEnteredTime": to, "maxResults": 3000},
        )
        orders_ok = ro.status_code == 200
        orders: list[WorkingOrder] = []
        if orders_ok:
            data = ro.json()
            data = data if isinstance(data, list) else (data.get("orders") or [])
            orders = normalize_schwab_orders(data)

        symbols = sorted({p.symbol for p in positions if p.symbol} | {"ETHA", "IBIT", "NVO", "NOK"})
        rq = get("/marketdata/v1/quotes", {"symbols": ",".join(symbols)})
        quotes_ok = rq.status_code == 200
        quotes: dict[str, dict[str, Any]] = {}
        if quotes_ok:
            q = rq.json()
            for sym, rec in (q.items() if isinstance(q, dict) else []):
                if not isinstance(rec, dict):
                    continue
                quote = rec.get("quote") or rec
                quotes[sym] = {
                    "last": quote.get("lastPrice") or quote.get("mark"),
                    "mark": quote.get("mark"),
                    "bid": quote.get("bidPrice"),
                    "ask": quote.get("askPrice"),
                    "quote_time": quote.get("quoteTime") or quote.get("tradeTime"),
                }

        self._version += 1
        return AccountSnapshot(
            venue=self.venue,
            account_alias=self.account_alias,
            source="schwab_read",
            as_of=as_of,
            version=self._version,
            cash_available=dec(cash),
            equity=dec(equity),
            sod_equity=dec(sod),
            positions=positions,
            working_orders=orders,
            quotes=quotes,
            orders_ok=orders_ok,
            quotes_ok=quotes_ok,
            note="" if (orders_ok and quotes_ok) else "partial_book",
        )

    def submit(self, intent: dict[str, Any], writer_permit: str) -> SubmitAck:
        if not writer_permit.startswith("live-writer-"):
            return SubmitAck("REJECTED", None, "writer_permit_not_live")
        if intent.get("mode") != "live":
            return SubmitAck("REJECTED", None, "intent_not_live")
        import requests  # type: ignore

        headers, acct = self._auth()
        headers = {**headers, "Content-Type": "application/json"}
        payload = _bracket_payload(intent)
        r = requests.post(
            f"{BASE}/trader/v1/accounts/{acct}/orders",
            headers=headers,
            json=payload,
            timeout=30,
        )
        loc = r.headers.get("Location") or r.headers.get("location") or ""
        oid = loc.rsplit("/orders/", 1)[-1].split("?")[0] if "/orders/" in loc else ""
        if r.status_code in (200, 201):
            return SubmitAck("ACCEPTED", oid or None, "accepted")
        if r.status_code in (0,) or r.status_code >= 500:
            return SubmitAck("UNKNOWN", oid or None, f"http={r.status_code}")
        return SubmitAck("REJECTED", None, f"http={r.status_code}")

    def cancel(self, broker_order_id: str, writer_permit: str) -> SubmitAck:
        if not writer_permit.startswith("live-writer-"):
            return SubmitAck("REJECTED", None, "writer_permit_not_live")
        import requests  # type: ignore

        headers, acct = self._auth()
        r = requests.delete(
            f"{BASE}/trader/v1/accounts/{acct}/orders/{broker_order_id}",
            headers=headers,
            timeout=30,
        )
        if r.status_code in (200, 204):
            return SubmitAck("ACCEPTED", broker_order_id, "canceled")
        return SubmitAck("REJECTED", broker_order_id, f"http={r.status_code}")


def _bracket_payload(intent: dict[str, Any]) -> dict[str, Any]:
    qty = float(intent["quantity"])
    limit = float(intent["limit_price"])
    stop = float(intent["protective_stop_price"])
    symbol = str(intent["instrument_id"]).upper()
    return {
        "orderStrategyType": "TRIGGER",
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "LIMIT",
        "price": limit,
        "orderLegCollection": [
            {
                "instruction": "BUY",
                "quantity": int(qty),
                "instrument": {"symbol": symbol, "assetType": "EQUITY"},
            }
        ],
        "childOrderStrategies": [
            {
                "orderStrategyType": "SINGLE",
                "session": "NORMAL",
                "duration": "GOOD_TILL_CANCEL",
                "orderType": "STOP",
                "stopPrice": stop,
                "orderLegCollection": [
                    {
                        "instruction": "SELL",
                        "quantity": int(qty),
                        "instrument": {"symbol": symbol, "assetType": "EQUITY"},
                    }
                ],
            }
        ],
    }
