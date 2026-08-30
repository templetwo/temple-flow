#!/usr/bin/env python3
"""One-shot: send already-approved TF-20260830-01 and -02. Never prints tokens/hash."""
from __future__ import annotations

import json
import os
import sys
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

BASE = "https://api.schwabapi.com"


def post_order(token: str, acct: str, payload: dict) -> tuple[int, str]:
    r = requests.post(
        f"{BASE}/trader/v1/accounts/{acct}/orders",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    loc = r.headers.get("Location") or r.headers.get("location") or ""
    return r.status_code, (loc or r.text[:300])


def main() -> int:
    acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "").strip()
    if not acct:
        print("missing_account_hash")
        return 2
    tm = TokenManager()
    token = tm.get_token()
    nvo = {
        "orderType": "STOP",
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderStrategyType": "SINGLE",
        "stopPrice": 42.50,
        "orderLegCollection": [
            {
                "instruction": "SELL",
                "quantity": 1,
                "instrument": {"symbol": "NVO", "assetType": "EQUITY"},
            }
        ],
    }
    ibit = {
        "orderStrategyType": "TRIGGER",
        "session": "NORMAL",
        "duration": "GOOD_TILL_CANCEL",
        "orderType": "LIMIT",
        "price": 43.90,
        "orderLegCollection": [
            {
                "instruction": "BUY",
                "quantity": 2,
                "instrument": {"symbol": "IBIT", "assetType": "EQUITY"},
            }
        ],
        "childOrderStrategies": [
            {
                "orderStrategyType": "SINGLE",
                "session": "NORMAL",
                "duration": "GOOD_TILL_CANCEL",
                "orderType": "STOP",
                "stopPrice": 41.20,
                "orderLegCollection": [
                    {
                        "instruction": "SELL",
                        "quantity": 2,
                        "instrument": {"symbol": "IBIT", "assetType": "EQUITY"},
                    }
                ],
            }
        ],
    }
    print("ticket TF-20260830-01")
    c1, b1 = post_order(token, acct, nvo)
    print("nvo_http", c1, "body", b1)
    print("ticket TF-20260830-02")
    c2, b2 = post_order(token, acct, ibit)
    print("ibit_http", c2, "body", b2)
    ok = c1 in (200, 201) and c2 in (200, 201)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
