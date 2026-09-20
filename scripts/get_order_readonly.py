#!/usr/bin/env python3
"""Read-only GET of a single Schwab order. Never prints tokens or account hash."""
from __future__ import annotations
import json, os, sys
from pathlib import Path

order_id = sys.argv[1] if len(sys.argv) > 1 else "1007762031725"
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

tm = TokenManager()
st = tm.get_token_status()
safe = {k: st.get(k) for k in ("status", "refresh_valid", "access_valid") if isinstance(st, dict)}
print("token_status:", json.dumps(safe, default=str))
token = tm.get_token()
acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "")
if not acct:
    print("missing_account_hash")
    raise SystemExit(2)
headers = {"Authorization": "Bearer " + token}
url = f"https://api.schwabapi.com/trader/v1/accounts/{acct}/orders/{order_id}"
r = requests.get(url, headers=headers, timeout=30)
print("order_http:", r.status_code)
if r.status_code != 200:
    print("order_body_prefix:", r.text[:300])
    raise SystemExit(1)
o = r.json()
legs = [
    {
        "instruction": leg.get("instruction"),
        "symbol": (leg.get("instrument") or {}).get("symbol"),
        "qty": leg.get("quantity"),
    }
    for leg in (o.get("orderLegCollection") or [])
]
out = {
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
    "childOrderStrategies": bool(o.get("childOrderStrategies")),
    "parent": (o.get("orderActivityCollection") or None),
    "legs": legs,
}
# Also surface child linkage fields if present
for k in ("orderStrategyType", "statusDescription", "cancelable", "editable"):
    if k in o:
        out[k] = o.get(k)
print("order:", json.dumps(out, default=str))
