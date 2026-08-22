# Capital baseline — Temple Flow

**Effective 2026-08-22 (Desk Lead):** Research capital tracks **live Schwab equity**. The old $1,000 placeholder is retired.

## Baseline snapshot (start point)

| Field | Value |
| --- | --- |
| As-of | 2026-08-22 ~19:42 America/New_York |
| Broker | Schwab (spiral-broker on Mac Studio) |
| Account | MARGIN …8585 |
| Equity / liquidation | $95.63 |
| Cash / buying power | $2.15 |
| Positions | NVO 2 @ avg $38.92 · MTM $93.48 |
| Day P&L at snapshot | $0.00 (weekend) |

## Rules

1. Risk Manager sizes every ticket from **fresh Schwab equity**, not this file’s stale dollars alone.
2. Hard % limits in `RISK_CONSTITUTION.md` still apply (2.5% risk/trade, 18% position, 4.5% daily loss, 18% drawdown from **peak equity**, max 4 opens).
3. Peak equity for drawdown starts at this baseline until a new peak prints.
4. Crypto live vehicles remain IBIT / FBTC / ETHA; current book is NVO (legacy equity) until rotated under ticket protocol.
