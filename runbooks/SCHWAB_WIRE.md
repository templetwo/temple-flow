# Schwab wire — Temple Flow / Execution

## Local finding (Mac Studio, 2026-08-22)

Existing stack (reuse; do not reinvent):

| Item | Location |
| --- | --- |
| OAuth + token manager | `~/spiral-broker/src/schwab_auth.py`, `token_manager.py` |
| Tools | `~/spiral-broker/dashboard/api/services/schwab_tools.py` |
| App credentials | `~/spiral-broker/.env` (`SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`) |
| Callback | `https://127.0.0.1:8080` (must complete OAuth **on the Mac**) |
| Token file | `~/spiral-broker/.schwab_tokens.json` (chmod 600) |
| Account hash | `SCHWAB_ACCOUNT_HASH` currently **empty** — populate after re-auth |

**Status at wire time:** refresh token **expired/revoked** (last refresh 2026-01-02). Manual OAuth re-auth required. No Schwab MCP in Cursor catalog — Mac-local API only.

## Temple Flow rules

1. Execution Bot may send **only** approved ticket IDs (`approve TF-YYYYMMDD-XX`).
2. Live vehicles (crypto hybrid): IBIT / FBTC / ETHA only until constitution amended.
3. Never commit `.env`, tokens, or secrets into `temple-flow`.
4. Prefer calling spiral-broker auth/tools from Mac Studio; Grok Bot box is **not** the OAuth callback host for this app registration.

## Re-auth

```bash
cd ~/spiral-broker
# use spiral-broker-prod venv if needed
~/spiral-broker-prod/dashboard/api/venv_new/bin/python -m src.schwab_auth
```

Browser opens Schwab consent → callback hits `127.0.0.1:8080` → tokens saved.

Then: read-only `accountNumbers` probe → set `SCHWAB_ACCOUNT_HASH` in `.env`.

## Smoke tests (read-only first)

1. Token status != refresh_expired  
2. `GET /trader/v1/accounts/accountNumbers`  
3. Quotes for IBIT / ETHA (optional)  
4. **No live order** until a sized ticket is human-approved  

## Bridge script

`scripts/schwab_status.py` — read-only status for Desk Lead / Execution.

## Status (2026-08-22 evening ET)

- Re-auth **OK** via HTTPS `127.0.0.1:8080` + local certs
- Tokens valid; `SCHWAB_ACCOUNT_HASH` populated on Mac spiral-broker envs
- Read-only probes: accountNumbers 200; quotes IBIT/ETHA 200
- Live sends still require exact `approve TF-YYYYMMDD-XX`
