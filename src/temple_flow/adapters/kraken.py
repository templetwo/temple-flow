"""Kraken spot adapter. Missing keys => UNAVAILABLE, never paper cash.

Credentials: KRAKEN_API_KEY + KRAKEN_API_SECRET (or KRAKEN_PRIVATE_KEY)
in ~/spiral-broker/.env — see docs/campaign_v2/CREDENTIALS.md.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from temple_flow.adapters.credentials import kraken_key_names, load_env_files, present
from temple_flow.adapters.protocol import (
    AccountSnapshot,
    CapabilitySnapshot,
    Position,
    SubmitAck,
    VenueUnavailable,
    dec,
)

PUBLIC = "https://api.kraken.com"


class KrakenAdapter:
    venue = "kraken_spot"

    def __init__(self, account_alias: str = "KRAKEN_RESEARCH"):
        self.account_alias = account_alias
        self._version = 1

    def _keys(self) -> tuple[str, str]:
        load_env_files()
        key_name, secret_name = kraken_key_names()
        flags = present([key_name, secret_name])
        missing = [n for n, ok in flags.items() if not ok]
        if missing:
            raise VenueUnavailable(
                "kraken: missing "
                + ",".join(missing)
                + " (put KRAKEN_API_KEY and KRAKEN_API_SECRET in ~/spiral-broker/.env)"
            )
        return os.environ[key_name].strip(), os.environ[secret_name].strip()

    def capabilities(self) -> CapabilitySnapshot:
        try:
            self._keys()
            status = "DOCUMENTED_ONLY"
        except VenueUnavailable:
            status = "UNAVAILABLE"
        return CapabilitySnapshot(
            venue=self.venue,
            account_alias=self.account_alias,
            features={
                "account_snapshot": "DOCUMENTED_ONLY" if status != "UNAVAILABLE" else "UNAVAILABLE",
                "submit": "DOCUMENTED_ONLY" if status != "UNAVAILABLE" else "UNAVAILABLE",
                "native_stop": "DOCUMENTED_ONLY",
                "borrow": "UNSUPPORTED",
                "fee_schedule": "DOCUMENTED_ONLY",
            },
            as_of=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            status=status,
        )

    def _private(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        import requests  # type: ignore

        api_key, api_secret = self._keys()
        api_key = api_key.strip()
        api_secret = "".join(api_secret.split())
        data = dict(data or {})
        data["nonce"] = str(int(time.time() * 1000))
        postdata = urllib.parse.urlencode(data)
        encoded = (data["nonce"] + postdata).encode()
        message = path.encode() + hashlib.sha256(encoded).digest()
        try:
            secret = base64.b64decode(api_secret)
        except Exception as exc:
            raise VenueUnavailable("kraken: API secret is not valid base64") from exc
        if not secret:
            raise VenueUnavailable("kraken: API secret decoded empty")
        sig = hmac.new(secret, message, hashlib.sha512)
        headers = {
            "API-Key": api_key,
            "API-Sign": base64.b64encode(sig.digest()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # Body must be the exact string we signed. A dict here is a common
        # EAPI:Invalid key: requests re-encodes and the signature misses.
        r = requests.post(PUBLIC + path, headers=headers, data=postdata, timeout=30)
        if r.status_code != 200:
            raise VenueUnavailable(f"kraken: http={r.status_code}")
        body = r.json()
        if body.get("error"):
            raise VenueUnavailable("kraken: " + ",".join(body["error"]))
        return body.get("result") or {}

    def snapshot(self) -> AccountSnapshot:
        result = self._private("/0/private/Balance")
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        usd = dec(result.get("ZUSD") or result.get("USD") or "0") or Decimal("0")
        positions: list[Position] = []
        for asset, qty in result.items():
            q = dec(qty) or Decimal("0")
            if q == 0 or asset in {"ZUSD", "USD", "USDT"}:
                continue
            positions.append(Position(symbol=str(asset), qty=q))
        open_orders: list = []
        orders_ok = True
        try:
            oo = self._private("/0/private/OpenOrders")
            open_orders = list((oo.get("open") or {}).items())
        except VenueUnavailable:
            orders_ok = False
        working = []
        from temple_flow.adapters.protocol import WorkingOrder

        for oid, rec in open_orders:
            descr = rec.get("descr") or {}
            working.append(
                WorkingOrder(
                    broker_order_id=str(oid),
                    symbol=descr.get("pair"),
                    side=str(descr.get("type") or "").upper(),
                    status=str(rec.get("status") or ""),
                    order_type=descr.get("ordertype"),
                    price=dec(descr.get("price")),
                    qty=dec(rec.get("vol")),
                    remaining=dec(rec.get("vol")) - (dec(rec.get("vol_exec")) or Decimal("0"))
                    if rec.get("vol")
                    else None,
                )
            )
        self._version += 1
        return AccountSnapshot(
            venue=self.venue,
            account_alias=self.account_alias,
            source="kraken_read",
            as_of=as_of,
            version=self._version,
            cash_available=usd,
            equity=None,
            sod_equity=None,
            positions=positions,
            working_orders=working,
            quotes={},
            orders_ok=orders_ok,
            quotes_ok=False,
            note="quotes not fetched on this read",
        )

    def submit(self, intent: dict[str, Any], writer_permit: str) -> SubmitAck:
        if not writer_permit.startswith("live-writer-"):
            return SubmitAck("REJECTED", None, "writer_permit_not_live")
        if intent.get("mode") != "live":
            return SubmitAck("REJECTED", None, "intent_not_live")
        try:
            result = self._private(
                "/0/private/AddOrder",
                {
                    "pair": intent["instrument_id"],
                    "type": "buy" if intent["side"] == "buy" else "sell",
                    "ordertype": "limit",
                    "price": intent["limit_price"],
                    "volume": intent["quantity"],
                    "oflags": "post",
                },
            )
        except VenueUnavailable as exc:
            return SubmitAck("UNKNOWN", None, str(exc))
        txid = (result.get("txid") or [None])[0]
        return SubmitAck("ACCEPTED", txid, "accepted")

    def cancel(self, broker_order_id: str, writer_permit: str) -> SubmitAck:
        if not writer_permit.startswith("live-writer-"):
            return SubmitAck("REJECTED", None, "writer_permit_not_live")
        try:
            self._private("/0/private/CancelOrder", {"txid": broker_order_id})
        except VenueUnavailable as exc:
            return SubmitAck("UNKNOWN", broker_order_id, str(exc))
        return SubmitAck("ACCEPTED", broker_order_id, "canceled")
