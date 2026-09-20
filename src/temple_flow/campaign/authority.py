"""Durable campaign grants. GO is one authenticated action, not a per-trade card."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from temple_flow.campaign.contracts import ContractError, validate_document
from temple_flow.campaign.policy import assert_profile_explicit, policy_digest


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Authority:
    def __init__(self, store: Any):
        self.store = store

    def prepare(self, definition: dict[str, Any]) -> dict[str, Any]:
        doc = json.loads(json.dumps(definition))
        if doc.get("definition_state") == "draft":
            raise ContractError("draft cannot be prepared without resolved snapshots")
        doc["definition_state"] = "prepared"
        doc.setdefault(
            "activation",
            {
                "enabled": False,
                "grant_id": None,
                "deployment_receipt_id": None,
                "policy_digest": None,
            },
        )
        assert_profile_explicit(doc)
        digest = policy_digest(doc)
        self.store.put_campaign_revision(doc, digest)
        return {"campaign": doc, "policy_digest": digest}

    def go(
        self,
        campaign_id: str,
        revision: int,
        expected_digest: str,
        principal_ref: str = "operator:local-paper",
    ) -> dict[str, Any]:
        row = self.store.get_campaign_revision(campaign_id, revision)
        if row is None:
            raise ContractError("unknown prepared campaign revision")
        doc = json.loads(row["definition_json"])
        digest = row["policy_digest"]
        if digest != expected_digest:
            raise ContractError("stale preview: digest mismatch")
        if digest != policy_digest(doc):
            raise ContractError("definition does not match stored digest")
        assert_profile_explicit(doc)
        existing = self.store.get_active_grant(campaign_id)
        if existing is not None:
            if existing["accepted_digest"] != digest:
                raise ContractError("active grant digest differs; prepare a new revision")
            return {
                "grant_id": existing["grant_id"],
                "generation": existing["generation"],
                "policy_digest": digest,
                "idempotent": True,
            }
        grant_id = str(uuid.uuid4())
        receipt_id = str(uuid.uuid4())
        self.store.insert_grant(
            grant_id=grant_id,
            campaign_id=campaign_id,
            revision=revision,
            principal_ref=principal_ref,
            accepted_digest=digest,
            generation=1,
            accepted_at=_now(),
        )
        armed = json.loads(json.dumps(doc))
        armed["activation"] = {
            "enabled": True,
            "grant_id": grant_id,
            "deployment_receipt_id": receipt_id,
            "policy_digest": digest,
        }
        validate_document(armed)
        self.store.record_audit(
            campaign_id,
            "GRANT_ACCEPTED",
            {"grant_id": grant_id, "digest": digest, "principal_ref": principal_ref},
        )
        return {
            "grant_id": grant_id,
            "generation": 1,
            "policy_digest": digest,
            "deployment_receipt_id": receipt_id,
            "idempotent": False,
            "armed_definition": armed,
        }

    def stop(self, campaign_id: str) -> None:
        self.store.revoke_grant(campaign_id, _now())
        self.store.record_audit(campaign_id, "GRANT_REVOKED", {})

    def pause(self, campaign_id: str) -> None:
        self.store.set_entry_permission(campaign_id, "PAUSED")
        self.store.record_audit(campaign_id, "ENTRIES_PAUSED", {})

    def resume(self, campaign_id: str) -> None:
        grant = self.store.get_active_grant(campaign_id)
        if grant is None:
            raise ContractError("no active grant to resume")
        self.store.set_entry_permission(campaign_id, "ENABLED")
        self.store.record_audit(campaign_id, "ENTRIES_RESUMED", {})
