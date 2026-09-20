#!/usr/bin/env python3
"""Send approved TF-20260830-03 SELL LIMIT 1 ETHA 19.80 GTC. No hash/token prints."""
from __future__ import annotations
import os, sys
from pathlib import Path
BROKER = Path("/Users/tony_studio/spiral-broker")
os.chdir(BROKER); sys.path.insert(0, str(BROKER))
try:
    from dotenv import load_dotenv
    load_dotenv(BROKER / ".env")
except Exception:
    pass
import requests
from src.token_manager import TokenManager

def main() -> int:
    acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "").strip()
    if not acct:
        print("missing_account_hash"); return 2
    token = TokenManager().get_token()
    payload = {
        "orderType": "LIMIT",
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderStrategyType": "SINGLE",
        "price": 19.80,
        "orderLegCollection": [{
            "instruction": "SELL",
            "quantity": 1,
            "instrument": {"symbol": "ETHA", "assetType": "EQUITY"},
        }],
    }
    r = requests.post(
        f"https://api.schwabapi.com/trader/v1/accounts/{acct}/orders",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        json=payload, timeout=30,
    )
    loc = r.headers.get("Location") or ""
    oid = loc.rsplit("/orders/", 1)[-1] if "/orders/" in loc else ""
    print("ticket TF-20260830-03")
    print("etha_tp_http", r.status_code, "order_id", oid or "none")
    if r.status_code not in (200, 201):
        print("body_prefix", (r.text or "")[:180])
    return 0 if r.status_code in (200, 201) else 1

if __name__ == "__main__":
    raise SystemExit(main())
