"""prepare / go / status / paper-cycle. Isolated state directory only."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from temple_flow.adapters.paper import PaperBroker
from temple_flow.campaign.authority import Authority
from temple_flow.campaign.contracts import ContractError, load_json
from temple_flow.campaign.policy import policy_digest
from temple_flow.execution.engine import PaperEngine
from temple_flow.ledger.store import LedgerStore
from temple_flow.money import dstr


class Desk:
    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = LedgerStore(self.state_dir / "ledger.sqlite")
        self.authority = Authority(self.store)
        self._broker: PaperBroker | None = None
        self._engine: PaperEngine | None = None
        self._campaign: dict[str, Any] | None = None
        self._grant: dict[str, Any] | None = None

    def prepare(self, campaign_path: Path) -> dict[str, Any]:
        doc = load_json(campaign_path)
        for sleeve in doc["capital"]["venues"]:
            self.store.ensure_account(
                sleeve["venue"],
                sleeve["account_alias"],
                {"mode": "paper", "borrow": False},
            )
        prepared = self.authority.prepare(doc)
        (self.state_dir / "prepared.json").write_text(
            json.dumps(
                {
                    "campaign_id": doc["campaign_id"],
                    "revision": doc["revision"],
                    "policy_digest": prepared["policy_digest"],
                },
                indent=2,
            )
            + "\n"
        )
        return prepared

    def go(
        self,
        campaign_id: str,
        revision: int,
        digest: str,
        *,
        allow_paper_fixture: bool = False,
        live: bool = False,
    ) -> dict[str, Any]:
        result = self.authority.go(
            campaign_id,
            revision,
            digest,
            principal_ref="operator:local-paper" if allow_paper_fixture else "operator:live-first",
            live=live,
        )
        row = self.store.get_campaign_revision(campaign_id, revision)
        self._campaign = json.loads(row["definition_json"])
        self._grant = result
        if self._campaign["mode"] == "paper":
            if not allow_paper_fixture:
                raise ContractError(
                    "paper campaign is a test fixture only; live-first desk refuses it as product GO"
                )
            sleeve = self._campaign["capital"]["venues"][0]
            cash = Decimal(sleeve["allocation_usd"])
            self.store.set_cash(sleeve["venue"], sleeve["account_alias"], dstr(cash), "0")
            self.store.insert_fee_snapshot(
                {
                    "fee_snapshot_id": "fixture-fees",
                    "venue": sleeve["venue"],
                    "account_alias": sleeve["account_alias"],
                    "instrument_id": "FIXTURE/USD",
                    "maker_fraction_decimal": "0.004",
                    "taker_fraction_decimal": "0.004",
                    "as_of": "1970-01-01T00:00:00Z",
                    "source_ref": "paper",
                }
            )
            self._broker = PaperBroker(
                sleeve["venue"],
                sleeve["account_alias"],
                cash,
                Decimal("0.004"),
                Decimal("0.004"),
            )
            self._engine = PaperEngine(self.store, self._broker, self._campaign, result)
            return result
        # Live: do not invent cash. Service probe writes real balances if the read succeeded.
        self._broker = None
        self._engine = None
        return result

    def status(self) -> dict[str, Any]:
        if self._campaign is None:
            return {"campaign": None}
        runtime = self.store.runtime(self._campaign["campaign_id"])
        grant = self.store.get_active_grant(self._campaign["campaign_id"])
        sleeve = self._campaign["capital"]["venues"][0]
        cash = self.store.get_cash(sleeve["venue"], sleeve["account_alias"])
        lots = [dict(r) for r in self.store.lots(self._campaign["campaign_id"])]
        return {
            "campaign_id": self._campaign["campaign_id"],
            "lifecycle": runtime["lifecycle"] if runtime else None,
            "entry_permission": runtime["entry_permission"] if runtime else None,
            "grant_id": grant["grant_id"] if grant else None,
            "policy_digest": grant["accepted_digest"] if grant else None,
            "cash_available": cash[0],
            "cash_reserved": cash[1],
            "lots": lots,
            "economic_evidence": self._campaign["economic_evidence"],
        }

    def paper_cycle(self, campaign_path: Path) -> dict[str, Any]:
        prepared = self.prepare(campaign_path)
        campaign = prepared["campaign"]
        go = self.go(
            campaign["campaign_id"],
            campaign["revision"],
            prepared["policy_digest"],
            allow_paper_fixture=True,
        )
        go2 = self.authority.go(campaign["campaign_id"], campaign["revision"], prepared["policy_digest"])
        engine = self._engine
        assert engine is not None
        sleeve = campaign["capital"]["venues"][0]
        cash = sleeve["allocation_usd"]
        qualifying = {
            "candidate_id": "qualifying-edge",
            "venue": sleeve["venue"],
            "account_alias": sleeve["account_alias"],
            "instrument_id": "FIXTURE/USD",
            "quantity": "2",
            "worst_entry": "10",
            "modeled_exit": "11",
            "stop": "9",
            "entry_fee_fraction": "0.004",
            "exit_fee_fraction": "0.004",
            "weight": "1",
            "fee_snapshot_id": "fixture-fees",
            "market_snapshot_id": "fixture-market",
            "strategy_version": "fixture-strategy-v1",
            "evidence_refs": ["paper-fixture-not-broker"],
        }
        fee_negative = {
            **qualifying,
            "candidate_id": "fee-negative",
            "quantity": "2",
            "worst_entry": "10",
            "modeled_exit": "10.05",
            "entry_fee_fraction": "0.004",
            "exit_fee_fraction": "0.008",
        }
        declined = engine.evaluate(fee_negative, cash)
        passed = engine.evaluate(qualifying, cash)
        submitted = engine.authorize_and_submit(qualifying, passed)
        intent = submitted["intent"]
        broker_id = submitted["ack"].broker_order_id
        fill1 = engine.apply_fill(broker_id, "FILL-1", Decimal("1"), Decimal("10"), intent)
        fill1b = engine.apply_fill(broker_id, "FILL-1", Decimal("1"), Decimal("10"), intent)
        fill2 = engine.apply_fill(broker_id, "FILL-2", Decimal("1"), Decimal("10"), intent)
        # unknown submission recovery on a second client
        engine.broker.next_submit_result = "UNKNOWN"
        unknown_candidate = {
            **qualifying,
            "candidate_id": "unknown-then-recover",
            "quantity": "1",
        }
        # remaining cash after 2 @ 10 * 1.004 = 20.08 from 100
        remaining = dstr(Decimal(cash) - Decimal(passed["cash_required_usd"]))
        # Do not actually consume more if we want isolation of the unknown path:
        # evaluate against remaining, but skip if we already used cash in broker.
        # Reconstruct remaining from broker.
        remaining = dstr(engine.broker.cash)
        unk_decision = engine.evaluate(unknown_candidate, remaining)
        unk_submit = engine.authorize_and_submit(unknown_candidate, unk_decision)
        recovered = engine.recover_unknown(unk_submit["intent"])
        # restart reconstruction
        restarted = LedgerStore(self.store.path)
        lots = [dict(r) for r in restarted.lots(campaign["campaign_id"])]
        fills = [dict(r) for r in restarted.fills(sleeve["venue"], sleeve["account_alias"])]
        restarted.close()
        return {
            "prepare_digest": prepared["policy_digest"],
            "go": {"grant_id": go["grant_id"], "idempotent": go["idempotent"]},
            "go_repeat_idempotent": go2["idempotent"],
            "fee_negative": declined,
            "qualifying": passed,
            "submit": {"result": submitted["ack"].result, "order_id": broker_id},
            "fills": {
                "first_applied": fill1["applied"],
                "duplicate_noop": fill1b["applied"] is False,
                "second_applied": fill2["applied"],
            },
            "protection_stop_ids": [fill1.get("stop_id"), fill2.get("stop_id")],
            "unknown_recovery": recovered["ack"].result,
            "restart_lot_count": len(lots),
            "restart_fill_count": len(fills),
            "status": self.status(),
        }
