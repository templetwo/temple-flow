#!/usr/bin/env python3
"""Temple Flow v2 desk CLI.

Paper/isolated-state only. Does not load LIVE_OK, launchd, spiral-broker
tokens, or scripts/temple_flow_wire.py. GO here is a paper grant unless a
separately authorized live cutover is performed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from temple_flow.control.commands import Desk  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Temple Flow v2 campaign desk (paper)")
    p.add_argument(
        "--state",
        required=True,
        help="Isolated state directory (ledger + prepared digest). Never the live Studio root.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--campaign", required=True)
    go = sub.add_parser("go")
    go.add_argument("--campaign-id", required=True)
    go.add_argument("--revision", type=int, required=True)
    go.add_argument("--digest", required=True)
    sub.add_parser("status")
    cycle = sub.add_parser("paper-cycle")
    cycle.add_argument(
        "--campaign",
        default=str(ROOT / "examples/campaign_v2/campaign.paper_100_to_200.json"),
    )
    sub.add_parser("preview")
    args = p.parse_args(argv)
    desk = Desk(Path(args.state))
    if args.cmd == "prepare":
        out = desk.prepare(Path(args.campaign))
        print(json.dumps({"policy_digest": out["policy_digest"], "campaign_id": out["campaign"]["campaign_id"]}, indent=2))
        return 0
    if args.cmd == "go":
        out = desk.go(args.campaign_id, args.revision, args.digest)
        print(json.dumps({k: out[k] for k in ("grant_id", "generation", "policy_digest", "idempotent") if k in out}, indent=2))
        return 0
    if args.cmd == "status":
        print(json.dumps(desk.status(), indent=2, default=str))
        return 0
    if args.cmd == "paper-cycle":
        out = desk.paper_cycle(Path(args.campaign))
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "preview":
        path = ROOT / "docs/campaign_v2/CAMPAIGN_PREVIEW_GO.md"
        print(path.read_text())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
