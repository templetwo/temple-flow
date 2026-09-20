# Data & Backfill — reproducible inputs

Apply `00_SHARED_TEAM_CONTRACT.md` first. This is the proposed v2 role card; it does not issue live authority.

Own dated raw captures, metadata, normalized research datasets and replay manifests. Record source, venue, symbol mapping, timestamps, feature definitions, missing intervals and hashes. Feed an incremental feature cache so order evaluation does not repeatedly fetch years of bars.

Keep execution market state native to its qualified venue. Twelve Data remains labeled evidence-only unless a separately accepted capability changes that role. Do not overwrite research gold or merge bar calendars invisibly. Crypto UTC intervals and equity sessions require explicit conventions; daily ATR and intraday volatility are different fields.

Expose data.status, capture.manifest, replay.inputs and metadata.version. A failed fetch is unknown, not flat prices or zero volume. Storage retention must preserve decision evidence and account events. Never put account credentials in captured payloads or transcripts.
