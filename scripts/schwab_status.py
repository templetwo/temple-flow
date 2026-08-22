#!/usr/bin/env python3
"""Read-only Schwab status for Temple Flow. Runs on Mac Studio with spiral-broker env.

Never prints secrets or full tokens.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BROKER_ROOT = Path(os.environ.get("SPIRAL_BROKER_ROOT", Path.home() / "spiral-broker")).expanduser()
ENV_PATH = BROKER_ROOT / ".env"


def _load_env(path: Path) -> dict:
    vals = {}
    if not path.exists():
        return vals
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def main() -> int:
    sys.path.insert(0, str(BROKER_ROOT))
    os.chdir(BROKER_ROOT)
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except Exception:
        for k, v in _load_env(ENV_PATH).items():
            os.environ.setdefault(k, v)

    env = _load_env(ENV_PATH)
    print("callback:", env.get("SCHWAB_CALLBACK_URL", ""))
    print("app_key_present:", bool(env.get("SCHWAB_APP_KEY")))
    print("app_secret_present:", bool(env.get("SCHWAB_APP_SECRET")))
    print("account_hash_present:", bool(env.get("SCHWAB_ACCOUNT_HASH")))

    from src.token_manager import TokenManager

    tm = TokenManager()
    status = tm.get_token_status()
    print("token_status:", json.dumps(status, default=str))

    if status.get("status") == "refresh_expired" or not status.get("refresh_valid"):
        print("action_required: run OAuth re-auth on this Mac (python -m src.schwab_auth)")
        return 2

    try:
        import requests

        token = tm.get_token()
        r = requests.get(
            "https://api.schwabapi.com/trader/v1/accounts/accountNumbers",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        print("accountNumbers_http:", r.status_code)
        if r.status_code == 200:
            data = r.json()
            print("accountNumbers_count:", len(data) if isinstance(data, list) else "n/a")
            return 0
        print("accountNumbers_body_prefix:", r.text[:120])
        return 1
    except Exception as e:
        print("probe_error:", type(e).__name__, str(e)[:200])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
