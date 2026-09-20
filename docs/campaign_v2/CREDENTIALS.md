# Where credentials live (v2 live path)

Do **not** put API keys in `config.toml`, campaign JSON, Helix, git, or the paper $100 fixture.

## Kraken (API key + private key)

Kraken's "private key" is the **API secret** (base64) from Kraken → Settings → API.

Add two lines to the same env file this MacBook already uses for Schwab:

```text
/Users/vaquez/spiral-broker/.env
```

```text
KRAKEN_API_KEY=<public API key>
KRAKEN_API_SECRET=<private key / API secret, base64>
```

Mode `600` (`chmod 600`). The file is outside the `temple-flow` git tree.

Optional aliases the loader also accepts: `KRAKEN_PRIVATE_KEY` for the secret.

Optional second file (gitignored if you ever put it in the repo): `/Users/vaquez/temple-flow/.env` with the same two names. `TEMPLE_FLOW_ENV_FILE` overrides both.

The live desk **never** invents Kraken balances if these are missing. It reports `unavailable`.

## Schwab (already on this machine)

| Item | Path |
|------|------|
| App key/secret + account hash | `/Users/vaquez/spiral-broker/.env` (`SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_ACCOUNT_HASH`) |
| OAuth tokens | `/Users/vaquez/spiral-broker/.schwab_tokens.json` |

`SCHWAB_ACCOUNT_HASH` must be a **non-empty** value. This MacBook currently has the key with an empty value, so Schwab reads are `UNAVAILABLE` (measured). Do not copy iCloud `TempleFlowKeys/` into git. The adapter uses spiral-broker only.

## What this seat will not do

- Print key values
- Commit `.env` or token JSON
- Treat a paper digest as live authority
- Send a live order until a live campaign digest is accepted **and** exclusive writer is claimed
