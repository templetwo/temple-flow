#!/usr/bin/env python3
"""Temple Flow v2 desk CLI.

Default: READ_ONLY / UNARMED. Paper cycle is a test fixture, not the product.
Live GO does not send until exclusive writer is claimed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from temple_flow.control.commands import Desk  # noqa: E402
from temple_flow.control.preview import compile_live_definition, write_preview  # noqa: E402
from temple_flow.execution.service import DeskService  # noqa: E402
from temple_flow.execution.writer import WriterConflict, WriterLease  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Temple Flow v2 campaign desk")
    p.add_argument("--state", required=True, help="Isolated state directory")
    sub = p.add_subparsers(dest="cmd", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--campaign", required=True)
    go = sub.add_parser("go")
    go.add_argument("--campaign-id", required=True)
    go.add_argument("--revision", type=int, required=True)
    go.add_argument("--digest", required=True)
    go.add_argument("--live", action="store_true")
    go.add_argument("--allow-paper-fixture", action="store_true")
    sub.add_parser("status")
    cycle = sub.add_parser("paper-cycle")
    cycle.add_argument(
        "--campaign",
        default=str(ROOT / "examples/campaign_v2/campaign.paper_100_to_200.json"),
    )
    sub.add_parser("preview")
    sub.add_parser("snapshot")
    sub.add_parser("preview-live")
    serve = sub.add_parser("serve")
    serve.add_argument("--cycles", type=int, default=1)
    serve.add_argument("--interval", type=float, default=5.0)
    claim = sub.add_parser("claim-writer")
    claim.add_argument("--venue", default="schwab")
    claim.add_argument("--account", default="SCHWAB_RESEARCH")
    claim.add_argument("--force", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "snapshot":
        svc = DeskService(Path(args.state))
        try:
            print(json.dumps(svc.probe(), indent=2, default=str))
        finally:
            svc.close()
        return 0
    if args.cmd == "preview-live":
        svc = DeskService(Path(args.state))
        try:
            probe = svc.probe()
            err = None
            definition = None
            try:
                definition = compile_live_definition(probe)
            except ValueError as exc:
                err = str(exc)
            dest = ROOT / "docs/campaign_v2/CAMPAIGN_PREVIEW_LIVE.md"
            text = write_preview(dest, probe, definition, err)
            print(text)
            if definition:
                print(
                    json.dumps(
                        {
                            "campaign_id": definition["campaign_id"],
                            "policy_digest": __import__(
                                "temple_flow.campaign.policy", fromlist=["policy_digest"]
                            ).policy_digest(definition),
                            "preview": str(dest),
                        },
                        indent=2,
                    )
                )
        finally:
            svc.close()
        return 0 if definition else 2
    if args.cmd == "serve":
        svc = DeskService(Path(args.state))
        try:
            out = svc.run_once() if args.cycles == 1 else None
            if args.cycles == 1:
                print(json.dumps(out, indent=2, default=str))
            else:
                svc.serve(cycles=args.cycles, interval_s=args.interval)
        finally:
            svc.close()
        return 0
    if args.cmd == "claim-writer":
        lease = WriterLease(Path(args.state), args.venue, args.account)
        try:
            rec = lease.claim(force=args.force)
        except WriterConflict as exc:
            print(str(exc), file=sys.stderr)
            return 3
        print(json.dumps(rec, indent=2))
        return 0

    desk = Desk(Path(args.state))
    if args.cmd == "prepare":
        out = desk.prepare(Path(args.campaign))
        print(
            json.dumps(
                {
                    "policy_digest": out["policy_digest"],
                    "campaign_id": out["campaign"]["campaign_id"],
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "go":
        out = desk.go(
            args.campaign_id,
            args.revision,
            args.digest,
            allow_paper_fixture=args.allow_paper_fixture,
            live=args.live,
        )
        print(
            json.dumps(
                {
                    k: out[k]
                    for k in ("grant_id", "generation", "policy_digest", "idempotent")
                    if k in out
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "status":
        print(json.dumps(desk.status(), indent=2, default=str))
        return 0
    if args.cmd == "paper-cycle":
        out = desk.paper_cycle(Path(args.campaign))
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "preview":
        path = ROOT / "docs/campaign_v2/CAMPAIGN_PREVIEW_LIVE.md"
        if not path.exists():
            path = ROOT / "docs/campaign_v2/CAMPAIGN_PREVIEW_GO.md"
        print(path.read_text())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
