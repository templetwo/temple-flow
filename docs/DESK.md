# Temple Flow Desk

Campaign-operated desk. Funds-beast owns **both venues in the campaign sense**. Sends stay host-split until WP7 cutover. Truth: [`STATUS.md`](campaign_v2/STATUS.md).

## Roster

| Role | Owner | Notes |
| --- | --- | --- |
| Desk Lead / Orchestrator | Funds-beast | Campaign outcome on Schwab + Kraken. Never orders/sizes. Never asks `approve TF-…` on in-envelope Kraken. |
| Data & Backfill | Data & Backfill bot | Multi-year data, indicators, regimes, SQLite. Async evidence. |
| Market / Technical | Market Technical bot | Price action evidence only. |
| Macro & Sentiment | Macro Sentiment bot | Macro/news/narrative evidence only. Not a per-trade veto. |
| Strategist | Strategist bot | Trade ideas with entry/stop/target. No size. |
| Risk Manager | Risk Manager bot | Only bot that proposes live size. A chat PASS is not a send. |
| Execution (Kraken) | Execution bot on **this MacBook** | Sole Kraken writer (claimed host + KeepAlive). Direct-call. |
| Execution (Schwab) | Studio Act `temple_flow_wire` | Sole Schwab sender until cutover. **Not this MacBook.** |
| Research Digest | Research Digest bot | Attribution vs research goal. Direct-call. Paper `$100→$200` is not live. |
| Crypto Velocity | Crypto Velocity bot | Kraken specialist. Direct-call under Funds-beast. |

Grok Bot paste profiles: [`bots/GROK_BOT_PROFILES.md`](../bots/GROK_BOT_PROFILES.md).

## Floor group

- Name: **Temple Flow Desk**
- Seats (channel max 6): Desk Lead, Data & Backfill, Market Technical, Macro Sentiment, Strategist, Risk Manager
- Execution + Research Digest: direct message from Desk Lead
- Execution DMs must name the host. Kraken = MacBook. Schwab = Studio. Never send from the wrong host.

## Cadence

| Routine | When (America/New_York) | Owner |
| --- | --- | --- |
| Morning Desk Brief | Weekdays 07:30 | Desk Lead |
| EOD Attribution | Weekdays 16:15 | Desk Lead + Research Digest |
| Kraken cycle | KeepAlive ~120s | MacBook `com.templetwo.temple-flow-kraken` |

## Sequence after campaign GO

Human capital gate is **one GO** on a prepared digest. After that, Kraken does **not** use `approve TF-YYYYMMDD-XX`.

1. Data refresh / backfill validation (async packages; do not stall a valid Kraken send on a missing Macro chat).
2. Technical package + Macro/Sentiment package (evidence, not a serial vote).
3. Strategy: Crypto Velocity on Kraken; equity strategy remains on Studio Act until Schwab cutover.
4. Risk Manager size or veto against the accepted campaign (funded cash, fees, increments). No inherited 2.5%/4.5%/18%/four-name caps.
5. Execution send + reconcile **on the venue's claimed host**.
6. Digest attribution.

### What still needs a human

- Campaign GO / new revision (scope change, borrow, second writer, Schwab hash/host cutover)
- Flatten / stop
- Schwab Act tickets on Studio **until WP7** (legacy `approve TF-…` path)

### This MacBook does not

- Send Schwab (`SCHWAB_ACCOUNT_HASH` empty here = UNAVAILABLE)
- Invent Schwab cash or positions
- Treat the paper `$100→$200` fixture as the live mandate
