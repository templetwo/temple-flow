# LIVE campaign preview

**Not the paper $100→$200 fixture. Paper digest confers no live authority.**

Service mode: `READ_ONLY` · entries `DISARMED`  
Seat: MacBook Pro (not Studio). Measured 2026-09-20. No live send. No `LIVE_OK`.

## Venue reads

### schwab

- capability: `UNAVAILABLE`
- source: none
- unavailable: `schwab: missing SCHWAB_ACCOUNT_HASH`
- App key/secret **are** present in `~/spiral-broker/.env`. Account hash key exists but is **empty**, so the adapter refuses to invent a book.
- cash_available / equity / positions / working orders: not claimed

### kraken_spot

- capability: `UNAVAILABLE`
- source: none
- unavailable: `kraken: missing KRAKEN_API_KEY,KRAKEN_API_SECRET`
- Put them in `~/spiral-broker/.env` (see `CREDENTIALS.md`). Missing keys do not become paper cash.

## Not compiled

No live venue snapshot is available; paper cash was not substituted. There is no live policy digest to GO.

## Exclusive writer

This MacBook has no `temple-flow` launchd job. Studio plist still names `/Users/tony_studio/temple-flow`. Do not `claim-writer` here while Studio may still send.

## After credentials

```sh
# Kraken
# add to ~/spiral-broker/.env:
# KRAKEN_API_KEY=...
# KRAKEN_API_SECRET=...   # Kraken "private key", base64
chmod 600 /Users/vaquez/spiral-broker/.env

# Schwab account hash (same file): SCHWAB_ACCOUNT_HASH=<hash from accountNumbers>

PYTHONPATH=src python3 scripts/temple_flow_desk.py --state /tmp/tf-live-probe preview-live
```

Engineering verification ≠ profitability.
