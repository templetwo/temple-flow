# Operating model — Temple Flow (cut down, 2026-08-28)

Two loops. That is the whole system.

| Loop | Where | Job |
| --- | --- | --- |
| Think | This chat / Funds-beast / phone | Watch, size, write rules, ping |
| Act | launchd on the Studio → `~/spiral-broker` | Place, protect, reprice. Schwab holds the order |

Grok Desktop is not the wire. Floor debate is not on the send path.

## Law (see `docs/AMENDMENTS_2026-08-28.md`)

1. Two loops. Act = Studio daemon.
2. One phrase per day: `arm MV session`. Then leave.
3. Live names: ETHA, IBIT. NVO/NOK = protect only.
4. One mutation: GTC pullback + attached stop. Through cap = dead.
5. Success = in the thesis with a stop on.
6. One-sell law (2026-08-30): never a second SELL on a share that already has a stop. Flatten = RTH cancel-stop then OCO. See `docs/AMENDMENTS_2026-08-30.md`.

Risk box unchanged: 2.5% / 4.5% day / 18% peak DD / hard stops / no unsupervised size / live Schwab equity.

## What Think does

- Morning watch and EOD attribution (routines).
- MV session watch: read-only from the phone when Anthony is away. No Allow-card nags.
- Write / edit `config/standing_rules.json` (human confirms numbers).
- Ping only on breaker, fill, or a protect gap (naked NVO).

## What Act does

`scripts/temple_flow_wire.py` under launchd (`deploy/com.templetwo.temple-flow-wire.plist`).

- Default **dry-run**. `--live` only on the Studio, only when the human starts it.
- Reads standing rules. Plans GTC+stop. Refuses chase through cap.
- Protects leftovers (NVO/NOK stops). Does not add to them.
- `--live` stays refused until the spiral-broker bracket helper is real.

## What we stopped doing

- Nine-seat debate before a $19 ETF send.
- DAY limits that die at AIRCO.
- Stop-after-fill as a second Auto-review card.
- A second SELL (LIMIT flatten or OCO) on a share that already has a stop.
- Replacing a stale bid up through the Risk cap.
- Treating ticket theater as the success metric.

## Honest size (illustrative, recompute from live equity)

On $597: 2.5% ≈ $15 · 18% ≈ $107 · 4.5% day ≈ $27.  
Example sleeve in `config/standing_rules.example.json`: 5 ETHA @ 18.70 GTC / stop 17.70 (risk ≈ $5.00 < $15) plus NVO 42.50 GTC stop (confirm tonight).
