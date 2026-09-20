"""SQLite ledger. Isolated path only. Decimal TEXT, not float SUM."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "ledger_schema.sql"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LedgerStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        existing = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_revisions'"
        ).fetchone()
        if existing is None:
            self.db.executescript(SCHEMA_PATH.read_text())
        self._ensure_runtime_tables()
        self.db.commit()

    def _ensure_runtime_tables(self) -> None:
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_runtime (
              campaign_id TEXT PRIMARY KEY,
              lifecycle TEXT NOT NULL,
              entry_permission TEXT NOT NULL,
              health_json TEXT NOT NULL
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS cash_balances (
              venue TEXT NOT NULL,
              account_alias TEXT NOT NULL,
              available_decimal TEXT NOT NULL,
              reserved_decimal TEXT NOT NULL,
              PRIMARY KEY(venue, account_alias)
            )
            """
        )

    def close(self) -> None:
        self.db.close()

    def put_campaign_revision(self, doc: dict[str, Any], digest: str) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO campaign_revisions
               (campaign_id, revision, definition_json, policy_digest, created_at)
               VALUES (?,?,?,?,?)""",
            (
                doc["campaign_id"],
                doc["revision"],
                json.dumps(doc, sort_keys=True),
                digest,
                _now(),
            ),
        )
        self.db.execute(
            """INSERT OR IGNORE INTO campaign_runtime
               (campaign_id, lifecycle, entry_permission, health_json)
               VALUES (?,?,?,?)""",
            (doc["campaign_id"], "PREPARED", "DISARMED", "{}"),
        )
        self.db.commit()

    def get_campaign_revision(self, campaign_id: str, revision: int) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM campaign_revisions WHERE campaign_id=? AND revision=?",
            (campaign_id, revision),
        ).fetchone()

    def ensure_account(self, venue: str, account_alias: str, capabilities: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT OR IGNORE INTO accounts
               (venue, account_alias, capabilities_json, capabilities_revision)
               VALUES (?,?,?,?)""",
            (venue, account_alias, json.dumps(capabilities, sort_keys=True), "paper-v1"),
        )
        self.db.commit()

    def insert_grant(self, **kwargs: Any) -> None:
        self.db.execute(
            """INSERT INTO grants
               (grant_id, campaign_id, revision, principal_ref, accepted_digest,
                generation, state, accepted_at, revoked_at)
               VALUES (:grant_id,:campaign_id,:revision,:principal_ref,:accepted_digest,
                       :generation,'ACTIVE',:accepted_at,NULL)""",
            kwargs,
        )
        self.db.execute(
            """UPDATE campaign_runtime
               SET lifecycle='RUNNING', entry_permission='ENABLED'
               WHERE campaign_id=?""",
            (kwargs["campaign_id"],),
        )
        self.db.commit()

    def get_active_grant(self, campaign_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM grants WHERE campaign_id=? AND state='ACTIVE'",
            (campaign_id,),
        ).fetchone()

    def revoke_grant(self, campaign_id: str, when: str) -> None:
        self.db.execute(
            "UPDATE grants SET state='REVOKED', revoked_at=? WHERE campaign_id=? AND state='ACTIVE'",
            (when, campaign_id),
        )
        self.db.execute(
            """UPDATE campaign_runtime
               SET lifecycle='STOPPED', entry_permission='REVOKED'
               WHERE campaign_id=?""",
            (campaign_id,),
        )
        self.db.commit()

    def set_entry_permission(self, campaign_id: str, permission: str) -> None:
        self.db.execute(
            "UPDATE campaign_runtime SET entry_permission=? WHERE campaign_id=?",
            (permission, campaign_id),
        )
        self.db.commit()

    def runtime(self, campaign_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM campaign_runtime WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()

    def set_cash(self, venue: str, account_alias: str, available: str, reserved: str) -> None:
        self.db.execute(
            """INSERT INTO cash_balances(venue, account_alias, available_decimal, reserved_decimal)
               VALUES (?,?,?,?)
               ON CONFLICT(venue, account_alias) DO UPDATE SET
                 available_decimal=excluded.available_decimal,
                 reserved_decimal=excluded.reserved_decimal""",
            (venue, account_alias, available, reserved),
        )
        self.db.commit()

    def get_cash(self, venue: str, account_alias: str) -> tuple[str, str]:
        row = self.db.execute(
            "SELECT available_decimal, reserved_decimal FROM cash_balances WHERE venue=? AND account_alias=?",
            (venue, account_alias),
        ).fetchone()
        if row is None:
            return "0", "0"
        return row[0], row[1]

    def record_audit(self, campaign_id: str | None, kind: str, payload: dict[str, Any]) -> None:
        event_id = str(uuid.uuid4())
        prev = self.db.execute(
            "SELECT event_hash FROM audit_events ORDER BY occurred_at DESC, event_id DESC LIMIT 1"
        ).fetchone()
        preceding = prev[0] if prev else ""
        body = json.dumps(payload, sort_keys=True)
        event_hash = hashlib.sha256(f"{preceding}|{kind}|{body}".encode()).hexdigest()
        self.db.execute(
            """INSERT INTO audit_events
               (event_id, campaign_id, occurred_at, kind, payload_json, source_ref,
                preceding_event_hash, event_hash)
               VALUES (?,?,?,?,?,?,?,?)""",
            (event_id, campaign_id, _now(), kind, body, "paper", preceding, event_hash),
        )
        self.db.commit()

    def insert_decision(self, decision: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO decisions
               (decision_id, campaign_id, revision, policy_digest, state_version,
                result, decision_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                decision["decision_id"],
                decision["campaign_id"],
                decision["campaign_revision"],
                decision["policy_digest"],
                decision["account_state_version"],
                decision["result"],
                json.dumps(decision, sort_keys=True),
                decision["created_at"],
            ),
        )
        self.db.commit()

    def insert_intent_and_reservation(
        self,
        intent: dict[str, Any],
        grant_id: str,
        reservation_id: str,
        resource_key: str,
        amount_decimal: str,
    ) -> None:
        with self.db:
            self.db.execute(
                """INSERT INTO intents
                   (intent_id, decision_id, grant_id, venue, account_alias, client_order_id,
                    state, exact_intent_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    intent["intent_id"],
                    intent["decision_id"],
                    grant_id,
                    intent["venue"],
                    intent["account_alias"],
                    intent["client_order_id"],
                    "RESERVED",
                    json.dumps(intent, sort_keys=True),
                    intent["created_at"],
                ),
            )
            self.db.execute(
                """INSERT INTO reservations
                   (reservation_id, intent_id, resource_key, amount_decimal, state, exclusive_group_id)
                   VALUES (?,?,?,?,?,NULL)""",
                (reservation_id, intent["intent_id"], resource_key, amount_decimal, "held"),
            )

    def set_intent_state(self, intent_id: str, state: str) -> None:
        self.db.execute("UPDATE intents SET state=? WHERE intent_id=?", (state, intent_id))
        self.db.commit()

    def get_intent(self, intent_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone()

    def insert_broker_order(self, venue: str, account: str, broker_order_id: str, intent_id: str, state: str) -> None:
        self.db.execute(
            """INSERT OR IGNORE INTO broker_orders
               (venue, account_alias, broker_order_id, intent_id, parent_order_id, state, last_source_ref)
               VALUES (?,?,?,?,NULL,?,?)""",
            (venue, account, broker_order_id, intent_id, state, "paper"),
        )
        self.db.commit()

    def insert_fill(self, fill: dict[str, Any]) -> bool:
        """Return True if this fill identity was newly applied."""
        cur = self.db.execute(
            """INSERT OR IGNORE INTO fills
               (venue, account_alias, fill_id, broker_order_id, quantity_decimal,
                price_decimal, fee_decimal, fee_currency, exchange_time, recorded_at, source_ref)
               VALUES (:venue,:account_alias,:fill_id,:broker_order_id,:quantity_decimal,
                       :price_decimal,:fee_decimal,:fee_currency,:exchange_time,:recorded_at,:source_ref)""",
            fill,
        )
        self.db.commit()
        return cur.rowcount == 1

    def insert_lot(self, lot: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO inventory_lots
               (lot_id, campaign_id, venue, account_alias, instrument_id,
                quantity_decimal, basis_decimal, last_event_ref, version)
               VALUES (:lot_id,:campaign_id,:venue,:account_alias,:instrument_id,
                       :quantity_decimal,:basis_decimal,:last_event_ref,:version)""",
            lot,
        )
        self.db.commit()

    def insert_protection(self, protection: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO protection_groups
               (protection_id, lot_id, state, reserved_quantity_decimal,
                protocol_revision, orders_json, last_evidence_ref)
               VALUES (:protection_id,:lot_id,:state,:reserved_quantity_decimal,
                       :protocol_revision,:orders_json,:last_evidence_ref)""",
            protection,
        )
        self.db.commit()

    def lots(self, campaign_id: str) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT * FROM inventory_lots WHERE campaign_id=?",
                (campaign_id,),
            )
        )

    def fills(self, venue: str, account: str) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT * FROM fills WHERE venue=? AND account_alias=?",
                (venue, account),
            )
        )

    def insert_fee_snapshot(self, snap: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO fee_snapshots
               (fee_snapshot_id, venue, account_alias, instrument_id,
                maker_fraction_decimal, taker_fraction_decimal, as_of, source_ref)
               VALUES (:fee_snapshot_id,:venue,:account_alias,:instrument_id,
                       :maker_fraction_decimal,:taker_fraction_decimal,:as_of,:source_ref)""",
            snap,
        )
        self.db.commit()
