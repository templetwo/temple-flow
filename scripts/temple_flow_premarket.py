#!/usr/bin/env python3
"""Temple Flow pre-market automation.

Runs before the open to:
- Check git branch/SHA for drift
- Check Schwab OAuth token health
- Auto-arm MV session when conditions are met
- Check market data API key availability

Safe to run any time. Logs to stdout; never sends orders; never commits.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = timezone(timedelta(hours=-4))

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKER_ROOT = Path(
    os.environ.get("SPIRAL_BROKER_ROOT", Path.home() / "spiral-broker")
).expanduser()


def logj(obj: dict) -> None:
    """Log JSON to stdout."""
    print(json.dumps(obj, default=str))


def now_et(now: datetime | None = None) -> datetime:
    """Current time in ET."""
    return (now or datetime.now(timezone.utc)).astimezone(ET)


def is_weekday(t: datetime) -> bool:
    """True if t is Monday-Friday."""
    return t.weekday() < 5


def check_git_status(repo_root: Path) -> dict:
    """Check git branch, SHA, and drift from remote.
    
    Returns dict with branch, sha, remote_sha, behind_by, uncommitted, warnings.
    """
    result = {
        "check": "git_status",
        "ok": True,
        "warnings": [],
        "branch": None,
        "sha": None,
        "remote_sha": None,
        "behind_by": 0,
        "uncommitted": False,
    }
    
    try:
        # Get current branch
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch.returncode == 0:
            result["branch"] = branch.stdout.strip()
        
        # Get current SHA
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if sha.returncode == 0:
            result["sha"] = sha.stdout.strip()[:12]
        
        # Check for uncommitted changes
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status.returncode == 0 and status.stdout.strip():
            result["uncommitted"] = True
            result["ok"] = False
            result["warnings"].append(
                "Local uncommitted changes detected. Hot-patch may drift from repo."
            )
        
        # Try to fetch remote without failing if offline
        if result["branch"]:
            fetch = subprocess.run(
                ["git", "fetch", "origin", result["branch"], "--dry-run"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            # Ignore fetch failures (may be offline), but try to get remote SHA
            remote_sha = subprocess.run(
                ["git", "rev-parse", f"origin/{result['branch']}"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if remote_sha.returncode == 0:
                result["remote_sha"] = remote_sha.stdout.strip()[:12]
                
                # Count commits behind
                if result["sha"]:
                    rev_list = subprocess.run(
                        ["git", "rev-list", "--count", f"HEAD..origin/{result['branch']}"],
                        cwd=repo_root,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if rev_list.returncode == 0:
                        behind = int(rev_list.stdout.strip() or 0)
                        result["behind_by"] = behind
                        if behind > 0:
                            result["ok"] = False
                            result["warnings"].append(
                                f"Branch is {behind} commit(s) behind origin/{result['branch']}"
                            )
    
    except Exception as e:
        result["ok"] = False
        result["warnings"].append(f"Git check failed: {type(e).__name__}")
    
    return result


def check_oauth_health() -> dict:
    """Check Schwab OAuth token health and attempt refresh if needed.
    
    Returns dict with status, needs_reauth, details.
    """
    result = {
        "check": "oauth_health",
        "ok": True,
        "status": "unknown",
        "needs_reauth": False,
        "warnings": [],
    }
    
    if not BROKER_ROOT.exists():
        result["ok"] = False
        result["warnings"].append(f"BROKER_ROOT {BROKER_ROOT} not found")
        return result
    
    sys.path.insert(0, str(BROKER_ROOT))
    try:
        from dotenv import load_dotenv
        load_dotenv(BROKER_ROOT / ".env")
    except Exception:
        pass
    
    try:
        from src.token_manager import TokenManager
        
        tm = TokenManager()
        st = tm.get_token_status()
        
        if isinstance(st, dict):
            result["status"] = st.get("status", "unknown")
            result["refresh_valid"] = st.get("refresh_valid")
            result["access_valid"] = st.get("access_valid")
            
            if st.get("status") == "refresh_expired" or st.get("refresh_valid") is False:
                result["ok"] = False
                result["needs_reauth"] = True
                result["warnings"].append(
                    "CRITICAL: OAuth refresh token expired or invalid. "
                    "Run ~/spiral-broker/run_https_auth_loop.sh before market open."
                )
            elif st.get("access_valid") is False:
                # Try to refresh
                try:
                    token = tm.get_token()
                    if token:
                        result["status"] = "refreshed"
                        result["warnings"].append("Access token refreshed successfully")
                    else:
                        result["ok"] = False
                        result["needs_reauth"] = True
                        result["warnings"].append("Token refresh failed. Reauth required.")
                except Exception as e:
                    result["ok"] = False
                    result["needs_reauth"] = True
                    result["warnings"].append(f"Token refresh failed: {type(e).__name__}")
        else:
            result["ok"] = False
            result["warnings"].append("Token status returned non-dict")
    
    except Exception as e:
        result["ok"] = False
        result["warnings"].append(f"OAuth check failed: {type(e).__name__}")
    finally:
        if str(BROKER_ROOT) in sys.path:
            sys.path.remove(str(BROKER_ROOT))
    
    return result


def check_market_data_key() -> dict:
    """Check if TWELVE_DATA_API_KEY is available.
    
    Returns dict with ok, source, warnings.
    """
    result = {
        "check": "market_data_key",
        "ok": False,
        "source": None,
        "warnings": [],
    }
    
    # Check environment
    if os.environ.get("TWELVE_DATA_API_KEY"):
        result["ok"] = True
        result["source"] = "environment"
        return result
    
    # Check broker .env
    env_file = BROKER_ROOT / ".env"
    if env_file.exists():
        try:
            with env_file.open() as f:
                for line in f:
                    if line.startswith("TWELVE_DATA_API_KEY="):
                        value = line.split("=", 1)[1].strip()
                        if value and value != '""' and value != "''":
                            result["ok"] = True
                            result["source"] = str(env_file)
                            return result
        except Exception:
            pass
    
    result["warnings"].append(
        "TWELVE_DATA_API_KEY not found. Market data will fall back to Yahoo Finance. "
        "Add key to environment or ~/spiral-broker/.env for primary source."
    )
    return result


def check_kraken_keys() -> dict:
    """Check if Kraken API keys are present (for reporting only).
    
    Returns dict with ok, verified, last_seen.
    """
    result = {
        "check": "kraken_keys",
        "ok": False,
        "verified": False,
        "last_seen": None,
        "warnings": [],
    }
    
    # Check environment
    has_key = bool(os.environ.get("KRAKEN_API_KEY"))
    has_secret = bool(os.environ.get("KRAKEN_API_SECRET"))
    
    if not (has_key and has_secret):
        # Check broker .env
        env_file = BROKER_ROOT / ".env"
        if env_file.exists():
            try:
                with env_file.open() as f:
                    content = f.read()
                    has_key = has_key or "KRAKEN_API_KEY=" in content
                    has_secret = has_secret or "KRAKEN_API_SECRET=" in content
            except Exception:
                pass
    
    if has_key and has_secret:
        result["ok"] = True
        result["warnings"].append(
            "Kraken keys found but NOT VERIFIED. "
            "Kraken lane digests should state UNVERIFIED with last confirmation timestamp."
        )
    else:
        result["warnings"].append(
            "Kraken keys not found. Kraken lane is unavailable on this machine."
        )
    
    return result


def load_mv_session(repo_root: Path) -> dict | None:
    """Load config/mv_session.json if it exists."""
    path = repo_root / "config" / "mv_session.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_mv_session(session: dict, repo_root: Path) -> bool:
    """Save config/mv_session.json."""
    path = repo_root / "config" / "mv_session.json"
    try:
        path.write_text(json.dumps(session, indent=2) + "\n")
        return True
    except Exception:
        return False


def load_standing_grants(repo_root: Path) -> dict:
    """Load config/standing_grants.json with fallback to safe defaults."""
    path = repo_root / "config" / "standing_grants.json"
    defaults = {
        "desk_may_approve_risk_pass": False,
        "desk_may_arm_mv_session": False,
        "auto_arm_mv_session": {"enabled": False},
        "auto_disarm_mv_session": {"enabled": True, "time_et": "16:00"},
        "auto_approve_remint": {"enabled": False},
    }
    
    if not path.exists():
        return defaults
    
    try:
        grants = json.loads(path.read_text())
        # Merge with defaults to ensure all keys exist
        for key, value in defaults.items():
            if key not in grants:
                grants[key] = value
            elif isinstance(value, dict) and isinstance(grants[key], dict):
                for sub_key, sub_value in value.items():
                    if sub_key not in grants[key]:
                        grants[key][sub_key] = sub_value
        return grants
    except Exception:
        return defaults


def check_mv_session_auto_arm(
    repo_root: Path, now: datetime | None = None
) -> dict:
    """Check if MV session should be auto-armed and arm it if conditions are met.
    
    Returns dict with check, armed, reason, new_session.
    """
    t_now = now_et(now)
    result = {
        "check": "mv_auto_arm",
        "ok": True,
        "armed": False,
        "already_armed": False,
        "reason": None,
        "warnings": [],
    }
    
    grants = load_standing_grants(repo_root)
    auto_arm = grants.get("auto_arm_mv_session", {})
    
    if not auto_arm.get("enabled"):
        result["reason"] = "auto_arm_disabled_in_grants"
        return result
    
    # Check weekday
    if not is_weekday(t_now):
        result["reason"] = "not_weekday"
        return result
    
    # Check if already armed
    session = load_mv_session(repo_root)
    if session and session.get("armed"):
        result["already_armed"] = True
        result["reason"] = "already_armed"
        result["armed"] = True
        return result
    
    # Check conditions
    conditions = auto_arm.get("conditions", {})
    cash_min = conditions.get("cash_pct_min", 0.20)
    no_hard_hold = conditions.get("no_hard_hold", True)
    
    # Try to get book data to check cash
    sys.path.insert(0, str(BROKER_ROOT))
    try:
        from dotenv import load_dotenv
        load_dotenv(BROKER_ROOT / ".env")
        from src.token_manager import TokenManager
        import requests
        
        token = TokenManager().get_token()
        acct = os.environ.get("SCHWAB_ACCOUNT_HASH", "")
        
        if not acct:
            result["ok"] = False
            result["warnings"].append("SCHWAB_ACCOUNT_HASH not set, cannot check cash")
            return result
        
        headers = {"Authorization": "Bearer " + token}
        r = requests.get(
            "https://api.schwabapi.com/trader/v1/accounts",
            headers=headers,
            params={"fields": "positions"},
            timeout=30,
        )
        
        if r.status_code != 200:
            result["ok"] = False
            result["warnings"].append(f"Failed to fetch account data: HTTP {r.status_code}")
            return result
        
        raw = r.json()
        book = None
        for item in raw if isinstance(raw, list) else [raw]:
            a = item.get("securitiesAccount") or item.get("account") or item
            cb = a.get("currentBalances") or {}
            equity = cb.get("liquidationValue") or cb.get("equity") or cb.get("accountValue")
            cash = cb.get("cashBalance") or cb.get("availableFunds") or cb.get("cashAvailableForTrading")
            if equity and cash:
                book = {"equity": equity, "cash": cash, "cash_pct": cash / equity if equity else 0}
                break
        
        if not book:
            result["ok"] = False
            result["warnings"].append("Could not extract equity/cash from account data")
            return result
        
        result["equity"] = book["equity"]
        result["cash"] = book["cash"]
        result["cash_pct"] = round(book["cash_pct"], 4)
        
        # Check cash threshold
        if book["cash_pct"] < cash_min:
            result["reason"] = f"cash_pct {book['cash_pct']:.1%} < threshold {cash_min:.1%}"
            return result
        
        # TODO: Check hard-hold calendar if we add that file
        
        # Conditions met - arm the session
        new_session = {
            "armed": True,
            "armed_at": t_now.isoformat(),
            "until": t_now.replace(hour=16, minute=0, second=0, microsecond=0).isoformat(),
            "source": f"auto-arm pre-market {t_now.strftime('%Y-%m-%d %H:%M ET')} (cash {book['cash_pct']:.1%} > {cash_min:.1%})",
            "auto": True,
        }
        
        if save_mv_session(new_session, repo_root):
            result["armed"] = True
            result["reason"] = "conditions_met_auto_armed"
            result["new_session"] = new_session
            result["warnings"].append(
                f"MV session AUTO-ARMED: cash {book['cash_pct']:.1%} > {cash_min:.1%}"
            )
        else:
            result["ok"] = False
            result["warnings"].append("Failed to save mv_session.json")
    
    except Exception as e:
        result["ok"] = False
        result["warnings"].append(f"Auto-arm check failed: {type(e).__name__}: {e}")
    finally:
        if str(BROKER_ROOT) in sys.path:
            sys.path.remove(str(BROKER_ROOT))
    
    return result


def check_mv_session_auto_disarm(
    repo_root: Path, now: datetime | None = None
) -> dict:
    """Check if MV session should be auto-disarmed at/after 16:00 ET.
    
    Returns dict with check, disarmed, reason.
    """
    t_now = now_et(now)
    result = {
        "check": "mv_auto_disarm",
        "ok": True,
        "disarmed": False,
        "already_disarmed": False,
        "reason": None,
        "warnings": [],
    }
    
    grants = load_standing_grants(repo_root)
    auto_disarm = grants.get("auto_disarm_mv_session", {})
    
    if not auto_disarm.get("enabled"):
        result["reason"] = "auto_disarm_disabled_in_grants"
        return result
    
    # Check time
    disarm_time_str = auto_disarm.get("time_et", "16:00")
    try:
        h, m = map(int, disarm_time_str.split(":"))
        disarm_time = time(h, m)
    except Exception:
        result["ok"] = False
        result["warnings"].append(f"Invalid disarm time: {disarm_time_str}")
        return result
    
    if t_now.time() < disarm_time:
        result["reason"] = f"before_disarm_time_{disarm_time_str}_ET"
        return result
    
    # Check if already disarmed
    session = load_mv_session(repo_root)
    if not session or not session.get("armed"):
        result["already_disarmed"] = True
        result["reason"] = "already_disarmed"
        return result
    
    # Disarm
    session["armed"] = False
    session["disarmed_at"] = t_now.isoformat()
    session["disarm_source"] = f"auto-disarm {disarm_time_str} ET {t_now.strftime('%Y-%m-%d')}"
    
    if save_mv_session(session, repo_root):
        result["disarmed"] = True
        result["reason"] = f"auto_disarmed_at_{disarm_time_str}_ET"
        result["warnings"].append(f"MV session AUTO-DISARMED at {t_now.strftime('%H:%M ET')}")
    else:
        result["ok"] = False
        result["warnings"].append("Failed to save disarmed mv_session.json")
    
    return result


def main(argv: list[str] | None = None) -> int:
    """Run pre-market checks."""
    p = argparse.ArgumentParser(description="Temple Flow pre-market automation")
    p.add_argument(
        "--check",
        choices=["all", "git", "oauth", "market_data", "kraken", "mv_arm", "mv_disarm"],
        default="all",
        help="Which checks to run (default: all)",
    )
    p.add_argument(
        "--mv-arm-only",
        action="store_true",
        help="Only run MV auto-arm check (shortcut)",
    )
    p.add_argument(
        "--mv-disarm-only",
        action="store_true",
        help="Only run MV auto-disarm check (shortcut)",
    )
    args = p.parse_args(argv)
    
    results = []
    
    if args.mv_arm_only:
        results.append(check_mv_session_auto_arm(REPO_ROOT))
    elif args.mv_disarm_only:
        results.append(check_mv_session_auto_disarm(REPO_ROOT))
    else:
        if args.check in ("all", "git"):
            results.append(check_git_status(REPO_ROOT))
        
        if args.check in ("all", "oauth"):
            results.append(check_oauth_health())
        
        if args.check in ("all", "market_data"):
            results.append(check_market_data_key())
        
        if args.check in ("all", "kraken"):
            results.append(check_kraken_keys())
        
        if args.check in ("all", "mv_arm"):
            results.append(check_mv_session_auto_arm(REPO_ROOT))
        
        if args.check in ("all", "mv_disarm"):
            results.append(check_mv_session_auto_disarm(REPO_ROOT))
    
    # Output
    all_ok = all(r.get("ok", True) for r in results)
    t_now = now_et()
    summary = {
        "premarket_checks": "temple_flow",
        "timestamp": t_now.isoformat(),
        "all_ok": all_ok,
        "checks": results,
    }
    
    logj(summary)
    
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
