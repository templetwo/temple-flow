#!/usr/bin/env python3
from __future__ import annotations
import os, sys
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

def main() -> int:
    token = TokenManager().get_token()
    h = {"Authorization": "Bearer " + token}
    r = requests.get(
        "https://api.schwabapi.com/marketdata/v1/quotes",
        headers=h,
        params={"symbols": "SOFI"},
        timeout=30,
    )
    print("quotes_http", r.status_code)
    if not r.ok:
        print("body_prefix", (r.text or "")[:200])
        return 1
    j = r.json()
    q = j.get("SOFI") or {}
    quote = q.get("quote") or q
    print(
        "sofi",
        {
            "last": quote.get("lastPrice") or quote.get("last"),
            "mark": quote.get("mark") or quote.get("markPrice"),
            "bid": quote.get("bidPrice") or quote.get("bid"),
            "ask": quote.get("askPrice") or quote.get("ask"),
            "high": quote.get("highPrice"),
            "low": quote.get("lowPrice"),
        },
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
