# Temple Flow Desk

## Roster

| Role | Owner | Notes |
| --- | --- | --- |
| Desk Lead / Orchestrator | Funds-beast | Ticket lifecycle, cadence, final brief. Never orders/sizes. |
| Data & Backfill | Data & Backfill bot | Multi-year data, indicators, regimes, SQLite. |
| Market / Technical | Market Technical bot | Price action evidence only. |
| Macro & Sentiment | Macro Sentiment bot | Macro/news/narrative evidence only. |
| Strategist | Strategist bot | Trade ideas with entry/stop/target. No size. |
| Risk Manager | Risk Manager bot | Only bot that proposes live size. Tickets. |
| Execution | Execution bot | Sends only approved tickets. Direct-call (not floor-seated). |
| Research Digest | Research Digest bot | Attribution vs $1k research goal. Direct-call. |

## Floor group

- Name: **Temple Flow Desk**
- Seats (channel max 6): Desk Lead, Data & Backfill, Market Technical, Macro Sentiment, Strategist, Risk Manager
- Execution + Research Digest: direct message from Desk Lead

## Cadence

| Routine | When (America/New_York) | Owner |
| --- | --- | --- |
| Morning Desk Brief | Weekdays 07:30 | Desk Lead |
| EOD Attribution | Weekdays 16:15 | Desk Lead + Research Digest |

## Sequence (never skip)

1. Data refresh / backfill validation  
2. Technical package + Macro/Sentiment package  
3. Strategist consensus ideas  
4. Risk Manager size or veto → ticket  
5. Human `approve TF-YYYYMMDD-XX`  
6. Execution send + reconcile  
7. Digest attribution  

Any deviation is out of scope.
