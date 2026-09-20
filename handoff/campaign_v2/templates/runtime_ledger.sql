-- REFERENCE DDL ONLY. Do not apply to a live database as a migration script.
-- Monetary TEXT requires exact Decimal arithmetic/application transactions.
-- Foreign keys and uniqueness alone do not implement financial correctness.
PRAGMA foreign_keys = ON;

CREATE TABLE campaign_revisions (
 campaign_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision > 0),
 definition_json TEXT NOT NULL, policy_digest TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(campaign_id,revision)
);
CREATE TABLE accounts (
 venue TEXT NOT NULL, account_alias TEXT NOT NULL,
 capabilities_json TEXT NOT NULL, capabilities_revision TEXT NOT NULL,
 PRIMARY KEY(venue,account_alias)
);
CREATE TABLE grants (
 grant_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, revision INTEGER NOT NULL,
 principal_ref TEXT NOT NULL, accepted_digest TEXT NOT NULL,
 generation INTEGER NOT NULL CHECK(generation > 0), state TEXT NOT NULL,
 accepted_at TEXT NOT NULL, revoked_at TEXT,
 FOREIGN KEY(campaign_id,revision) REFERENCES campaign_revisions(campaign_id,revision)
);
CREATE TABLE allocation_snapshots (
 snapshot_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, revision INTEGER NOT NULL,
 venue TEXT NOT NULL, account_alias TEXT NOT NULL, as_of TEXT NOT NULL,
 resources_json TEXT NOT NULL, source_ref TEXT NOT NULL,
 FOREIGN KEY(campaign_id,revision) REFERENCES campaign_revisions(campaign_id,revision),
 FOREIGN KEY(venue,account_alias) REFERENCES accounts(venue,account_alias)
);
CREATE TABLE source_snapshots (
 snapshot_id TEXT PRIMARY KEY, kind TEXT NOT NULL, as_of TEXT NOT NULL,
 received_at TEXT NOT NULL, content_hash TEXT NOT NULL, payload_ref TEXT NOT NULL
);
CREATE TABLE decisions (
 decision_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, revision INTEGER NOT NULL,
 policy_digest TEXT NOT NULL, state_version INTEGER NOT NULL,
 result TEXT NOT NULL, decision_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(campaign_id,revision) REFERENCES campaign_revisions(campaign_id,revision)
);
CREATE TABLE intents (
 intent_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, grant_id TEXT NOT NULL,
 venue TEXT NOT NULL, account_alias TEXT NOT NULL, client_order_id TEXT NOT NULL,
 state TEXT NOT NULL, exact_intent_json TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(venue,account_alias,client_order_id),
 FOREIGN KEY(decision_id) REFERENCES decisions(decision_id),
 FOREIGN KEY(grant_id) REFERENCES grants(grant_id),
 FOREIGN KEY(venue,account_alias) REFERENCES accounts(venue,account_alias)
);
CREATE TABLE reservations (
 reservation_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
 resource_key TEXT NOT NULL, amount_decimal TEXT NOT NULL,
 state TEXT NOT NULL, exclusive_group_id TEXT,
 FOREIGN KEY(intent_id) REFERENCES intents(intent_id)
);
CREATE TABLE broker_orders (
 venue TEXT NOT NULL, account_alias TEXT NOT NULL, broker_order_id TEXT NOT NULL,
 intent_id TEXT NOT NULL, parent_order_id TEXT, state TEXT NOT NULL,
 last_source_ref TEXT NOT NULL,
 PRIMARY KEY(venue,account_alias,broker_order_id),
 FOREIGN KEY(intent_id) REFERENCES intents(intent_id)
);
CREATE TABLE fills (
 venue TEXT NOT NULL, account_alias TEXT NOT NULL, fill_id TEXT NOT NULL,
 broker_order_id TEXT NOT NULL, quantity_decimal TEXT NOT NULL,
 price_decimal TEXT NOT NULL, fee_decimal TEXT NOT NULL, fee_currency TEXT NOT NULL,
 exchange_time TEXT NOT NULL, recorded_at TEXT NOT NULL, source_ref TEXT NOT NULL,
 PRIMARY KEY(venue,account_alias,fill_id),
 FOREIGN KEY(venue,account_alias,broker_order_id)
  REFERENCES broker_orders(venue,account_alias,broker_order_id)
);
CREATE TABLE inventory_lots (
 lot_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, venue TEXT NOT NULL,
 account_alias TEXT NOT NULL, instrument_id TEXT NOT NULL,
 quantity_decimal TEXT NOT NULL, basis_decimal TEXT,
 last_event_ref TEXT NOT NULL, version INTEGER NOT NULL
);
CREATE TABLE protection_groups (
 protection_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, state TEXT NOT NULL,
 reserved_quantity_decimal TEXT NOT NULL, protocol_revision TEXT NOT NULL,
 orders_json TEXT NOT NULL, last_evidence_ref TEXT NOT NULL,
 FOREIGN KEY(lot_id) REFERENCES inventory_lots(lot_id)
);
CREATE TABLE fee_snapshots (
 fee_snapshot_id TEXT PRIMARY KEY, venue TEXT NOT NULL, account_alias TEXT NOT NULL,
 instrument_id TEXT NOT NULL, maker_fraction_decimal TEXT NOT NULL,
 taker_fraction_decimal TEXT NOT NULL, as_of TEXT NOT NULL, source_ref TEXT NOT NULL
);
CREATE TABLE external_flows (
 flow_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, venue TEXT NOT NULL,
 account_alias TEXT NOT NULL, amount_signed_decimal TEXT NOT NULL,
 kind TEXT NOT NULL, adopted INTEGER NOT NULL CHECK(adopted IN(0,1)),
 occurred_at TEXT NOT NULL, source_ref TEXT NOT NULL
);
CREATE TABLE nav_observations (
 observation_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL,
 as_of TEXT NOT NULL, nav_decimal TEXT NOT NULL,
 unit_value_decimal TEXT, quality TEXT NOT NULL, components_json TEXT NOT NULL
);
CREATE TABLE financial_latches (
 latch_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, rule_id TEXT NOT NULL,
 state TEXT NOT NULL, triggered_at TEXT NOT NULL, evidence_ref TEXT NOT NULL,
 reset_grant_ref TEXT
);
CREATE TABLE writer_generations (
 venue TEXT NOT NULL, account_alias TEXT NOT NULL,
 generation INTEGER NOT NULL, owner_ref TEXT NOT NULL, state TEXT NOT NULL,
 PRIMARY KEY(venue,account_alias)
);
CREATE TABLE audit_events (
 event_id TEXT PRIMARY KEY, campaign_id TEXT, occurred_at TEXT NOT NULL,
 kind TEXT NOT NULL, payload_json TEXT NOT NULL, source_ref TEXT NOT NULL,
 preceding_event_hash TEXT, event_hash TEXT NOT NULL
);
CREATE TABLE checkpoints (
 consumer_id TEXT PRIMARY KEY, last_event_id TEXT,
 snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
);
