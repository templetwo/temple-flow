# Amendments 2026-08-28 — cut-down operating surface

**Authority:** Explicit human yes 1-5 by Anthony, 2026-08-28 ~11:52 ET.  
**Status:** LAW.  
**Does not move:** 2.5% risk/trade · 4.5% daily breaker · 18% peak drawdown · hard stops · no unsupervised size · size from live Schwab equity.

These five sentences are the operating surface. The constitution stays strict. The desk got small.

---

## 1. Two loops

Think lives in this chat / Funds-beast / the phone: watch, size, write rules, ping.  
Act is a **launchd daemon on the Studio** talking to `~/spiral-broker`. It places, protects, and reprices. Schwab holds the order.

Grok Desktop is **off the send path**. Every shell/file action through that app is the Allow card that froze the book. The daemon is a normal Mac process. Start it once. It does not ask permission every minute.

`--live` is still a human act at the Studio. Dry-run is the default. No cookie scrape. No Auto-review bypass from the phone.

## 2. One phrase per day

`arm MV session`. Then leave.

Disarm: `disarm MV session` · auto-disarm 16:00 ET · circuit breaker.  
Non-MV leftovers (NVO/NOK protect) may ride the same Act loop as standing rules the human wrote. New risk still needs the arm or an explicit home `--live`.

## 3. Universe is two names

Live entries: **ETHA** and **IBIT** only.  
NVO and NOK are leftovers to **protect**, not a strategy.  
No F. No AAL. No floor debate before a send.

Spot BTC/ETH remain research/signal only. FBTC is not a live vehicle unless this file is edited again.

## 4. One Schwab mutation

Default order: **GTC pullback + attached stop**.  
No DAY bids.  
No "stop after fill" second card.  
No replace **up** through the Risk cap.  
Through the cap means the idea is **dead**. Leave the working pullback or cancel it. Do not chase.

## 5. Honest money

On ~$597, 2.5% is about **$15**. An 18% sleeve is about **$107** (five ETHA or two IBIT).  
This will not pay rent. It makes money by being **in the thesis with a stop on**, not by sitting in idle cash waiting for a card.

The old success line ("not make money") is struck. Ticket throughput is not the metric.  
Dip-buy-with-stop on two liquid crypto ETFs is the strategy. Velocity theater on one-share NOK is how you lose interest.

---

## Still tonight (ops, not law)

1. Drop this pack onto the Studio (or reconnect GitHub write).
2. Copy `config/standing_rules.example.json` → `config/standing_rules.json` and confirm the NVO stop.
3. `python3 scripts/temple_flow_wire.py --status` then `--once` (dry-run).
4. One home Terminal `--once --live` (not Grok Desktop) to get the NVO GTC stop on, and a GTC ETHA pullback with the stop attached — only after the bracket helper is real.
5. `launchctl load` the plist. `arm MV session` if you want entries tomorrow. Walk away.

`--live` is **not** authorized from the phone. Cash idle until home is better than another stale DAY.
