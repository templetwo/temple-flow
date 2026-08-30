#!/usr/bin/env python3
"""Read-only Schwab snapshot for Temple Flow MV session watch. Never prints tokens or account hash."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BROKER = Path(os.environ.get("SPIRAL_BROKER_ROOT", Path.home() / "spiral-broker")).expanduser()
sys.path.insert(0, str(BROKER))
os.chdir(BROKER)

try:
    from dotenv import load_dotenv
    load_dotenv(BROKER / ".env")
except Exception:
    pass

from src.token_manager import TokenManager
import requests


def money(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def main() -> int:
    tm = TokenManager()
    st = tm.get_token_status()
    safe = {k: st.get(k) for k in ("status", "refresh_valid", "access_valid") if isinstance(st, dict)}
    print("token_status:", json.dumps(safe, default=str))
    if isinstance(st, dict) and (st.get("status") == "refresh_expired" or st.get("refresh_valid") is False):
        print("action_required: oauth")
        return 2

    token = tm.get_token()
    acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "")
    if not acct:
        print("missing_account_hash")
        return 2

    headers = {"Authorization": "Bearer " + token}
    base = "https://api.schwabapi.com"

    def get(path, params=None):
        r = requests.get(base + path, headers=headers, params=params, timeout=30)
        return r.status_code, r

    code, r = get("/trader/v1/accounts", {"fields": "positions"})
    print("accounts_http:", code)
    if code != 200:
        print("accounts_body_prefix:", r.text[:200])
        return 1

    raw = r.json()
    books = []
    for item in raw if isinstance(raw, list) else [raw]:
        a = item.get("securitiesAccount") or item.get("account") or item
        cb = a.get("currentBalances") or {}
        ib = a.get("initialBalances") or {}
        pos = []
        for p in a.get("positions") or []:
            inst = p.get("instrument") or {}
            pos.append(
                {
                    "symbol": inst.get("symbol"),
                    "qty": p.get("longQuantity") or p.get("quantity"),
                    "avg": p.get("averagePrice"),
                    "mv": p.get("marketValue"),
                    "dayPL": p.get("currentDayProfitLoss"),
                }
            )
        books.append(
            {
                "equity": money(cb, "liquidationValue", "equity", "accountValue"),
                "cash": money(cb, "cashBalance", "availableFunds", "cashAvailableForTrading"),
                "avail": money(cb, "availableFunds"),
                "bp": money(cb, "buyingPower", "availableFunds"),
                "lmv": money(cb, "longMarketValue"),
                "sod": money(ib, "liquidationValue", "accountValue", "equity"),
                "positions": pos,
            }
        )
    print("book:", json.dumps(books, default=str))

    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    code, r = get(
        "/trader/v1/accounts/" + acct + "/orders",
        {"fromEnteredTime": frm, "toEnteredTime": to, "maxResults": 50},
    )
    print("orders_http:", code)
    if code != 200:
        print("orders_body_prefix:", r.text[:200])
    else:
        data = r.json()
        data = data if isinstance(data, list) else (data.get("orders") or [])
        out = []
        for o in data:
            legs = [
                {
                    "instruction": leg.get("instruction"),
                    "symbol": (leg.get("instrument") or {}).get("symbol"),
                    "qty": leg.get("quantity"),
                }
                for leg in (o.get("orderLegCollection") or [])
            ]
            out.append(
                {
                    "id": o.get("orderId"),
                    "status": o.get("status"),
                    "type": o.get("orderType"),
                    "price": o.get("price"),
                    "stopPrice": o.get("stopPrice"),
                    "duration": o.get("duration"),
                    "entered": o.get("enteredTime"),
                    "filledQty": o.get("filledQuantity"),
                    "remaining": o.get("remainingQuantity"),
                    "qty": o.get("quantity"),
                    "legs": legs,
                }
            )
        print("orders:", json.dumps(out, default=str))

    code, r = get("/marketdata/v1/quotes", {"symbols": "ETHA,IBIT,NVO,NOK,FBTC"})
    print("quotes_http:", code)
    if code != 200:
        print("quotes_body_prefix:", r.text[:200])
    else:
        q = r.json()
        slim = {}
        for sym, rec in (q.items() if isinstance(q, dict) else []):
            if not isinstance(rec, dict):
                continue
            quote = rec.get("quote") or rec
            slim[sym] = {
                "last": quote.get("lastPrice") or quote.get("mark"),
                "mark": quote.get("mark"),
                "bid": quote.get("bidPrice"),
                "ask": quote.get("askPrice"),
            }
        print("quotes:", json.dumps(slim, default=str))

    print("now_utc:", now.isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
