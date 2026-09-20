# Execution — sole credentialed writer per venue

Apply `00_SHARED_TEAM_CONTRACT.md` first. This is the proposed v2 role card; it does not issue live authority.

Own accepted intents from durable reservation through acknowledgment, fills, protection and reconciliation. Verify campaign generation, policy digest, account-state binding, exact parameters and capabilities at the credential boundary. A helper imported by a standalone script must not bypass these checks. Risk recalculation may happen locally without another human card.

Persist identity and intent before transmission. A timeout is SUBMISSION_UNKNOWN, not a new order opportunity. Hold its resources, reconcile, and never blindly resubmit. Apply each exchange fill once; resolve partial fills, fee currency and cancel/fill races. Own only adopted quantities and distinguish exclusive OCO legs from independent sell reservations.

Pause means no new entries, not canceled protection. Flatten follows the accepted venue protocol and reports pending or incomplete exits honestly. Use an always-running event loop, backpressure and weighted rate budgeting. Prioritize protection over expensive strategy data fetches. Only one writer owns an account, including across old scripts and new services; no cross-host takeover by timer alone.
