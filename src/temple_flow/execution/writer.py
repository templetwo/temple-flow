"""Exclusive writer lease. Do not claim this while Studio launchd still sends."""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WriterConflict(RuntimeError):
    """Another process already owns the live send path."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WriterLease:
    def __init__(self, state_dir: Path, venue: str, account_alias: str):
        self.path = Path(state_dir) / f"writer-{venue}-{account_alias}.json"
        self.venue = venue
        self.account_alias = account_alias

    def status(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text())

    def claim(self, *, force: bool = False) -> dict[str, Any]:
        existing = self.status()
        if existing and existing.get("state") == "ACTIVE" and not force:
            if existing.get("host") == socket.gethostname():
                return self._reclaim(existing)
            raise WriterConflict(
                f"writer already claimed host={existing.get('host')} pid={existing.get('pid')}"
            )
        rec = {
            "venue": self.venue,
            "account_alias": self.account_alias,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "state": "ACTIVE",
            "claimed_at": _now(),
            "permit": f"live-writer-{os.getpid()}",
        }
        self.path.write_text(json.dumps(rec, indent=2) + "\n")
        return rec

    def release(self) -> None:
        rec = self.status()
        if rec is None:
            return
        rec["state"] = "RELEASED"
        rec["released_at"] = _now()
        self.path.write_text(json.dumps(rec, indent=2) + "\n")

    def _reclaim(self, existing: dict[str, Any]) -> dict[str, Any]:
        rec = dict(existing)
        rec["pid"] = os.getpid()
        rec["permit"] = f"live-writer-{os.getpid()}"
        rec["reclaimed_at"] = _now()
        rec["state"] = "ACTIVE"
        rec["host"] = socket.gethostname()
        self.path.write_text(json.dumps(rec, indent=2) + "\n")
        return rec

    def permit(self) -> str | None:
        rec = self.status()
        if not rec or rec.get("state") != "ACTIVE":
            return None
        if rec.get("host") != socket.gethostname():
            return None
        if rec.get("pid") != os.getpid():
            rec = self._reclaim(rec)
        return rec.get("permit")
