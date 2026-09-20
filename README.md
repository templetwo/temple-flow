# Temple Flow

Research-capital multi-agent trading desk for **Temple of Two / Spiral** sustainability.

Orchestrated in **Grok Bot** (Desk Lead: **Funds-beast**). Paste-ready profiles: [`bots/GROK_BOT_PROFILES.md`](bots/GROK_BOT_PROFILES.md).

This repo is the durable source of truth for:

- the **Risk Constitution** (historical) and v2 **campaign** grant
- bot role specs (including Crypto Velocity)
- Kraken-first live adapter (`src/temple_flow/`)
- ticket and audit logs (as the experiment runs)

## Core principles

1. **One clear owner per outcome** — each bot has a single primary job, scope, never-do list, and approval boundary.
2. **Human gate on capital** — every live order requires exact ticket-ID approval. No unsupervised sends.
3. **Fixed risk constitution** — day-one rules; no progressive tiers; agents cannot override.
4. **Historical backfill first** — trend/regime/technicals start from multi-year cleaned data.
5. **Full auditability** — signals, debates, risk decisions, and fills logged with provenance.
6. **Research attribution** — P&L tracked against Temple funding goals.

## Canonical docs

- [`docs/RISK_CONSTITUTION.md`](docs/RISK_CONSTITUTION.md) — **single source of truth for risk**
- [`docs/DESK.md`](docs/DESK.md) — roster, sequence, group seating
- [`bots/`](bots/) — paste-ready role descriptions
- [`skills/`](skills/) — backfill, ticket lifecycle, circuit breaker, brief, attribution

## Live order path (Kraken-first)

```
Accepted campaign GO (once)
  → Kraken Balance + ticker/OHLC + fee snapshot
  → Crypto Velocity setup + Risk PASS
  → Execution POST with native stop (claimed writer)
  → Reconcile fills
```

Schwab stays dark until `SCHWAB_ACCOUNT_HASH` is set. Paper digest is not live authority.

## Capital

- **Kraken research:** live ZUSD from `kraken_read` (see `docs/campaign_v2/CAMPAIGN_PREVIEW_LIVE.md`)
- **Schwab:** not this cut
- Profile: `full_loss_research`. Edge labeled `EXPERIMENTAL_UNPROVEN`

## Status

- v2 campaign runtime on `feat/campaign-v2-wp0-wp2`
- Grok Bot profiles in `bots/GROK_BOT_PROFILES.md`
- Kraken keys: `~/spiral-broker/.env` (`KRAKEN_API_KEY`, `KRAKEN_API_SECRET`)
- Mode: READ_ONLY / DISARMED until `desk go --live` and `claim-writer` for Kraken
