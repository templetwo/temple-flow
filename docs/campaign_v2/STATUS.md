# Temple Flow v2 status — 2026-09-20 MacBook

**Repo:** `main` @ merge of campaign v2 + HQ tickets. **Not HQ.** Schwab Act stays on Studio.

## Running now

- Kraken writer exclusive on this MacBook
- Grant ACTIVE / entries ENABLED (`/tmp/tf-kraken-run`)
- XXBT 0.0012 + native stop `O55VHG-TY4DM-O3KIJT` @ 78454.6
- KeepAlive `com.templetwo.temple-flow-kraken`
- CLI: `snapshot`, `kraken-cycle`, `explain-cash`, `attribution`, `reconcile`, `flatten` (dry-run default)

## Work packages

| WP | Spec | Truth |
|----|------|--------|
| 0 inventory | done | `WP0_LOCAL_INVENTORY.md` |
| 1 contracts/GO | done | `src/temple_flow/campaign/` |
| 2 paper slice | done as **tests only** | not the product |
| 3 allocator/async | partial | funded_weighted + same-cycle cash; not a full event bus |
| 4 adapters | Kraken live; Schwab **read blocked** (empty `SCHWAB_ACCOUNT_HASH` on this host) | |
| 5 control UI | CLI only | no dashboard |
| 6 acceptance 60 | not run | |
| 7 cutover both venues | **not done** | two writers still: Studio Schwab + MacBook Kraken |

## Blocked / will not fake

- Schwab live from this laptop
- TradeVolume fee tier
- Profitability (EXPERIMENTAL_UNPROVEN)
- Deposits as P&L vs FRIEND_PROFIT_BASELINE
