"""Load venue credentials from env files. Never log values."""

from __future__ import annotations

import os
from pathlib import Path


def broker_root() -> Path:
    return Path(os.environ.get("SPIRAL_BROKER_ROOT", Path.home() / "spiral-broker")).expanduser()


def env_files() -> list[Path]:
    files: list[Path] = []
    override = os.environ.get("TEMPLE_FLOW_ENV_FILE")
    if override:
        files.append(Path(override).expanduser())
    files.append(Path.home() / "temple-flow" / ".env")
    files.append(broker_root() / ".env")
    return files


def load_env_files() -> dict[str, str]:
    """Parse KEY=VALUE files. Does not print values. Later files do not override process env."""
    found: dict[str, str] = {}
    for path in env_files():
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw = line.split("=", 1)
            key = key.strip()
            val = raw.strip().strip('"').strip("'")
            found.setdefault(key, val)
            os.environ.setdefault(key, val)
    return found


def present(names: list[str]) -> dict[str, bool]:
    load_env_files()
    return {n: bool(os.environ.get(n, "").strip()) for n in names}


def require(names: list[str]) -> tuple[bool, list[str]]:
    flags = present(names)
    missing = [n for n, ok in flags.items() if not ok]
    return (not missing, missing)


def kraken_key_names() -> tuple[str, str]:
    load_env_files()
    key = "KRAKEN_API_KEY"
    secret = "KRAKEN_API_SECRET"
    if os.environ.get("KRAKEN_PRIVATE_KEY", "").strip() and not os.environ.get("KRAKEN_API_SECRET", "").strip():
        secret = "KRAKEN_PRIVATE_KEY"
    return key, secret
