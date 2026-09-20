#!/usr/bin/env python3
"""Replace ETHA stop with OCO: SELL LIMIT 19.80 XOR STOP 17.70. No hash prints."""
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

STOP_ID = "1007757064203"

def oid(loc: str) -> str:
    return loc.rsplit("/orders/", 1)[-1] if "/orders/" in (loc or "") else ""

def main() -> int:
    acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "").strip()
    if not acct:
        print("missing_account_hash"); return 2
    token = TokenManager().get_token()
    h = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    base = f"https://api.schwabapi.com/trader/v1/accounts/{acct}/orders"
    # cancel standalone stop
    r = requests.delete(f"{base}/{STOP_ID}", headers=h, timeout=30)
    print("cancel_stop_http", r.status_code)
    oco = {
        "orderStrategyType": "OCO",
        "childOrderStrategies": [
            {
                "orderStrategyType": "SINGLE",
                "session": "NORMAL",
                "duration": "GOOD_TILL_CANCEL",
                "orderType": "LIMIT",
                "price": 19.80,
                "orderLegCollection": [{
                    "instruction": "SELL", "quantity": 1,
                    "instrument": {"symbol": "ETHA", "assetType": "EQUITY"},
                }],
            },
            {
                "orderStrategyType": "SINGLE",
                "session": "NORMAL",
                "duration": "GOOD_TILL_CANCEL",
                "orderType": "STOP",
                "stopPrice": 17.70,
                "orderLegCollection": [{
                    "instruction": "SELL", "quantity": 1,
                    "instrument": {"symbol": "ETHA", "assetType": "EQUITY"},
                }],
            },
        ],
    }
    p = requests.post(base, headers=h, json=oco, timeout=30)
    loc = p.headers.get("Location") or ""
    print("oco_http", p.status_code, "order_id", oid(loc) or "none")
    if p.status_code not in (200, 201):
        print("body_prefix", (p.text or "")[:220])
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
