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
2. **Human gate on capital** — campaign GO is the grant. Kraken intents after GO do not use `approve TF-…`. Schwab Act on Studio still uses ticket IDs until cutover.
3. **Campaign policy, not inherited caps** — live grant is `full_loss_research`. Agents cannot restore 2.5%/4.5%/18%/four-name ceilings or override the digest.
4. **Historical backfill first** — trend/regime/technicals start from multi-year cleaned data.
5. **Full auditability** — signals, debates, risk decisions, and fills logged with provenance.
6. **Research attribution** — P&L tracked against Temple funding goals. Paper `$100→$200` is a fixture, not live P&L.

## Canonical docs

- [`docs/campaign_v2/STATUS.md`](docs/campaign_v2/STATUS.md) — done / running / blocked / not built
- [`docs/RISK_CONSTITUTION.md`](docs/RISK_CONSTITUTION.md) — historical risk text (superseded for this campaign by the live digest)
- [`docs/DESK.md`](docs/DESK.md) — roster, sequence, group seating
- [`bots/GROK_BOT_PROFILES.md`](bots/GROK_BOT_PROFILES.md) — paste-ready Grok Bot profiles
- [`skills/`](skills/) — backfill, ticket lifecycle, circuit breaker, brief, attribution

## Live order path (dual venue, host-split)

```
Accepted campaign GO (once per revision/digest)
  Kraken — this MacBook exclusive writer + KeepAlive
    → Balance + ticker/OHLC + fee snapshot
    → Crypto Velocity setup + Risk PASS
    → Execution POST with native stop
    → Reconcile fills
    No approve TF-… on in-envelope Kraken intents
  Schwab — Studio Act (`temple_flow_wire`) until WP7 cutover
    → This MacBook: SCHWAB_ACCOUNT_HASH empty = UNAVAILABLE
    → Do not send Schwab from this host
    → Do not invent Schwab cash/positions
```

Paper digest confers no live authority. Never send from the wrong host.

## Capital

- **Kraken:** live `kraken_read` on this MacBook. Not the paper `$100→$200` fixture.
- **Schwab:** Studio Act owns sends. This MacBook hash is empty → UNAVAILABLE. Do not invent balances.
- Profile: `full_loss_research`. Edge: `EXPERIMENTAL_UNPROVEN`.

## Status

See [`docs/campaign_v2/STATUS.md`](docs/campaign_v2/STATUS.md).

- `main` carries Kraken campaign v2 + Studio Schwab tickets
- Grok Bot profiles: `bots/GROK_BOT_PROFILES.md`
- Kraken on this MacBook: grant ENABLED, KeepAlive loop, XXBT + native stop
- Schwab: not sent from this host (`SCHWAB_ACCOUNT_HASH` empty here)
- Edge: `EXPERIMENTAL_UNPROVEN`. Tests ≠ profit.
