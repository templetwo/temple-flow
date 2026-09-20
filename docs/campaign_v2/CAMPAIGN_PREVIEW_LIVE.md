# LIVE campaign preview

**Not the paper $100→$200 fixture. Paper digest confers no live authority.**

Service mode: `READ_ONLY` · entries `DISARMED`

## Venue reads

### schwab

- capability: `UNAVAILABLE`
- source: `None`
- unavailable: schwab: missing SCHWAB_ACCOUNT_HASH
- cash_available: `None`
- equity: `None`
- positions: `[]`
- working_orders: `[]`

### kraken_spot

- capability: `DOCUMENTED_ONLY`
- source: `kraken_read`
- cash_available: `100`
- equity: `None`
- positions: `[]`
- working_orders: `[]`

## Resolved live definition (unarmed until exclusive writer)

- campaign_id: `TF-CAMPAIGN-LIVE`
- revision: `1`
- profile: `full_loss_research`
- basis_net_usd: `100` (sum of proven venue cash, not a target)
- snapshot_id: `kraken_read:kraken_spot`
- policy_digest: `64bad098c45611e1bfd89c5683886bdab03c98313877281d699ef4abe8749e40`
- objective: `none` (no $200 carry-over)
- per_trade_human_approval: `False`
- inherited %/count caps: all `enabled: false`

GO against this digest accepts this revision. Existing broker stops stay in place.
New sends stay DISARMED until `desk claim-writer` on the exclusive host.

Engineering verification ≠ profitability.
