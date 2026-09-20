#!/usr/bin/env python3
"""Approved TF-20260831-01: cancel IBIT 1724, then BUY 6 SOFI GTC 17.66 + STOP 16.80.
Never prints tokens or account hash."""
from __future__ import annotations
import os, sys, time
from pathlib import Path
BROKER = Path("/Users/tony_studio/spiral-broker")
os.chdir(BROKER)
sys.path.insert(0, str(BROKER))
try:
    from dotenv import load_dotenv
    load_dotenv(BROKER / ".env")
except Exception:
    pass
import requests
from src.token_manager import TokenManager

IBIT_ID = "1007762031724"
BASE = "https://api.schwabapi.com"

def oid_from_loc(loc: str) -> str:
    return loc.rsplit("/orders/", 1)[-1] if "/orders/" in (loc or "") else ""

def main() -> int:
    acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "").strip()
    if not acct:
        print("missing_account_hash")
        return 2
    token = TokenManager().get_token()
    h = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    orders_url = f"{BASE}/trader/v1/accounts/{acct}/orders"

    # 1. cancel IBIT parent
    cr = requests.delete(f"{orders_url}/{IBIT_ID}", headers=h, timeout=30)
    print("cancel_ibit_http", cr.status_code)
    if cr.status_code not in (200, 201):
        print("cancel_body_prefix", (cr.text or "")[:180])
        if cr.status_code not in (400, 404):
            print("abort_no_sofi")
            return 1

    # 2. confirm IBIT not WORKING
    time.sleep(0.8)
    st = None
    for _ in range(6):
        gr = requests.get(f"{orders_url}/{IBIT_ID}", headers=h, timeout=30)
        if gr.ok:
            st = (gr.json() or {}).get("status")
            print("ibit_status", st)
            if st in ("CANCELED", "CANCELLED", "REJECTED", "EXPIRED"):
                break
        time.sleep(0.7)
    if st not in ("CANCELED", "CANCELLED", "REJECTED", "EXPIRED"):
        print("abort_ibit_still", st or "unknown")
        return 1

    # 3. one mutation SOFI TRIGGER + attached stop
    payload = {
        "orderStrategyType": "TRIGGER",
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "LIMIT",
        "price": 17.66,
        "orderLegCollection": [{
            "instruction": "BUY",
            "quantity": 6,
            "instrument": {"symbol": "SOFI", "assetType": "EQUITY"},
        }],
        "childOrderStrategies": [{
            "orderStrategyType": "SINGLE",
            "session": "NORMAL",
            "duration": "GOOD_TILL_CANCEL",
            "orderType": "STOP",
            "stopPrice": 16.80,
            "orderLegCollection": [{
                "instruction": "SELL",
                "quantity": 6,
                "instrument": {"symbol": "SOFI", "assetType": "EQUITY"},
            }],
        }],
    }
    pr = requests.post(orders_url, headers=h, json=payload, timeout=30)
    loc = pr.headers.get("Location") or ""
    print("sofi_http", pr.status_code, "order_id", oid_from_loc(loc) or "none")
    if pr.status_code not in (200, 201):
        print("sofi_body_prefix", (pr.text or "")[:220])
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
