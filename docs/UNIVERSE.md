# Temple Flow Universe — Crypto gear (hybrid)

**Decision (2026-08-22, Desk Lead):** Gear hard to crypto via a **hybrid** model.

| Layer | What | Why |
| --- | --- | --- |
| Research / signals / backfill | Spot crypto majors (USD pairs) | True crypto regimes, ATR, narrative |
| Live tickets (Day-1) | Schwab-listed crypto products | Keeps Risk Constitution + Schwab account intact |
| Later (optional) | Spot venue (e.g. Kraken) | Full spot execution when wired + constitution amended |

Live is **on** (Schwab). Operating surface is the 2026-08-28 cut-down: ETHA + IBIT entries only.

---

## A. Signal / data universe (spot)

Primary (must backfill first):

| Symbol | Notes |
| --- | --- |
| BTC-USD | Anchor |
| ETH-USD | Anchor |
| SOL-USD | High-beta major |

Secondary (after primary is clean):

| Symbol | Notes |
| --- | --- |
| BNB-USD | |
| XRP-USD | |
| AVAX-USD | |
| LINK-USD | |
| DOGE-USD | Liquid meme-major; optional |

Macro context (not trade ideas): DXY, VIX, US10Y (existing Macro lane).

**Lookback (default until overridden):** 5 years daily bars; intraday (1h) only after daily is validated.

**Data sources:** approved public OHLC — Kraken, then Coinbase, Yahoo fallback (see `docs/DATA_CONVENTIONS.md`). Studio goldbrick/spiral paths override when provided.

---

## B. Live execution universe (Schwab)

**Live entries (law 2026-08-28):** ETHA and IBIT only.

| Symbol | Role |
| --- | --- |
| ETHA | Live entry (Ethereum) |
| IBIT | Live entry (Bitcoin) |
| NVO | Leftover — **protect only** (stop). Not a strategy. |
| NOK | Leftover — **protect only** (stop). Not a strategy. |
| FBTC | Not a live vehicle unless this file is amended again |
| F / AAL / other | Out. No floor debate before a send. |

Mapping rule for Strategist/Risk:

- Spot signal on `BTC-USD` → candidate live vehicle `IBIT`
- Spot signal on `ETH-USD` → candidate live vehicle `ETHA`
- Spot signal on `SOL-USD` / alts → **research-only** until a Schwab vehicle exists or spot venue is approved; do not force a bad proxy

---

## C. Risk notes (crypto)

- ATR filter still applies (ATR_14 > 1.8× ATR_60D_AVG → cut size 50% or skip). Crypto will trigger often; that is intended.
- Hard stops mandatory; weekend/gap risk is higher — prefer defined-risk and smaller R in shadow until behavior is measured.
- Max 4 opens still absolute.

---

## D. Open

- Confirm/replace public feed if goldbrick/spiral-broker lack crypto
- Whether to install Kraken connector later for spot execution
