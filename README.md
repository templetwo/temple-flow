# Temple Flow

Research-capital multi-agent trading desk for **Temple of Two / Spiral** sustainability.

Orchestrated in Grok Bot (Desk Lead: **Funds-beast**). This repo is the durable source of truth for:

- the **Risk Constitution**
- bot role specs
- shared skills / routines
- data provenance notes
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

## Live order path

```
Data refresh → Technical + Macro packages → Strategist ideas
    → Risk Manager sized ticket (TF-YYYYMMDD-XX)
    → Human: approve TF-YYYYMMDD-XX
    → Execution sends exact params to Schwab
    → Reconcile + log → Research Digest attribution
```

## Capital

- Research capital = **live Schwab equity** (baseline 2026-08-22: ~$95.63)
- Broker: Schwab (local/Mac Studio API path; no unsupervised agent sends)
- Mode: shadow/paper until human opens live under ticket approval

## Status

- Day 0 scaffold: constitution + bot specs + skills checked in (local)
- Schemas: SQLite store, ticket JSON, audit events (`schemas/`)
- Runbooks: shadow mode + home unblock checklist (`runbooks/`)
- GitHub remote: https://github.com/templetwo/temple-flow (push pending Cursor GitHub reconnect)
- Universe: crypto hybrid — spot majors for signals, Schwab IBIT/FBTC/ETHA for live (`docs/UNIVERSE.md`)
- Historical backfill: blocked on crypto data source paths/feeds (5y daily default)
- Schwab OAuth / execution path: deferred
- Mode: **shadow** until human opens live
