#!/usr/bin/env python3
"""Temple Flow Historical Backfill — secondary daily + indicator extend + regimes.

Appends to CANONICAL DB only. No invented bars. No second database.
Secondary: BNB-USD, XRP-USD, AVAX-USD, LINK-USD, DOGE-USD (~5y).
Then extend indicators + tf_trend_vol_v1 regimes for ALL symbols in DB.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = timezone.utc

REPO = "/workspace/temple-flow"
DB_PATH = f"{REPO}/data/temple_flow.sqlite"
SCHEMA = f"{REPO}/schemas/sqlite_schema.sql"
REPORT_PATH = f"{REPO}/data/backfill_secondary_report.md"
LOG_DIR = f"{REPO}/logs/backfill"

SECONDARY = ["BNB-USD", "XRP-USD", "AVAX-USD", "LINK-USD", "DOGE-USD"]

KRAKEN_PAIR = {
    "BNB-USD": "BNBUSD",
    "XRP-USD": "XXRPZUSD",
    "AVAX-USD": "AVAXUSD",
    "LINK-USD": "LINKUSD",
    "DOGE-USD": "XDGUSD",
}
KRAKEN_ALT = {
    "BNB-USD": "BNBUSD",
    "XRP-USD": "XRPUSD",
    "AVAX-USD": "AVAXUSD",
    "LINK-USD": "LINKUSD",
    "DOGE-USD": "XDGUSD",
}
COINBASE_PRODUCT = {s: s for s in SECONDARY}
YAHOO = {s: s for s in SECONDARY}

LOOKBACK_DAYS = 5 * 365 + 2
UA = "temple-flow-backfill/1.0 (+data-desk; secondary; no-secrets)"

# Regime method for this pass
REGIME_METHOD = "tf_trend_vol_v1"
SLOPE_LB = 5
TREND_BAND = 0.005
HV_THRESH = 1.8

ALL_INDICATOR_NAMES = [
    "RSI_14", "MACD", "MACD_SIGNAL", "MACD_HIST",
    "BB_UPPER", "BB_MID", "BB_LOWER",
    "SMA_20", "SMA_50", "SMA_200", "EMA_12", "EMA_26",
    "ATR_14", "ATR_60D_AVG", "ATR_RATIO_14_60",
]
EXTEND_NAMES = [
    "MACD", "MACD_SIGNAL", "MACD_HIST",
    "BB_UPPER", "BB_MID", "BB_LOWER",
    "SMA_20", "EMA_12", "EMA_26",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get_json(url: str, retries: int = 4, pause: float = 1.0):
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")), raw
        except Exception as e:
            last_err = e
            time.sleep(pause * (2 ** i))
    raise RuntimeError(f"GET failed {url}: {last_err}")


def session_date_from_period_end_unix(period_end_unix: int) -> str:
    dt = datetime.fromtimestamp(period_end_unix, tz=UTC).astimezone(NY)
    return dt.date().isoformat()


def bar_from_open_ts(open_ts: int, o, h, l, c, v) -> dict | None:
    period_end = open_ts + 86400
    if period_end > int(utc_now().timestamp()):
        return None
    try:
        o, h, l, c = float(o), float(h), float(l), float(c)
        v = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in (o, h, l, c)):
        return None
    if min(o, h, l, c) <= 0:
        return None
    h = max(h, o, c)
    l = min(l, o, c)
    if h < l:
        return None
    sd = session_date_from_period_end_unix(period_end)
    return {
        "session_date": sd,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v if v is not None else 0.0,
        "native_ts": open_ts,
    }


# ---- Sources -----------------------------------------------------------------

def fetch_kraken(pair: str, since: int | None = None) -> list[dict]:
    bars: dict[str, dict] = {}
    cursor = since
    now = time.time()
    while True:
        q = {"pair": pair, "interval": "1440"}
        if cursor is not None:
            q["since"] = str(cursor)
        url = "https://api.kraken.com/0/public/OHLC?" + urllib.parse.urlencode(q)
        data, _ = http_get_json(url)
        if data.get("error"):
            raise RuntimeError(f"Kraken error for {pair}: {data['error']}")
        result = data["result"]
        keys = [k for k in result.keys() if k != "last"]
        if not keys:
            break
        rows = result[keys[0]]
        last = result.get("last")
        if not rows:
            break
        added = 0
        for row in rows:
            t = int(row[0])
            if t + 86400 > now + 60:
                continue
            b = bar_from_open_ts(t, row[1], row[2], row[3], row[4], row[6])
            if b:
                bars[b["session_date"]] = b
                added += 1
        if last is None or (cursor is not None and last <= cursor):
            break
        if added == 0 and cursor is not None and last == cursor:
            break
        if len(rows) < 2:
            break
        prev = cursor
        cursor = last
        if prev is not None and cursor <= prev:
            break
        newest_t = int(rows[-1][0])
        if newest_t + 86400 >= now and len(rows) < 720:
            break
        time.sleep(0.35)
        if len(bars) > 3000:
            break
    return [bars[k] for k in sorted(bars.keys())]


def fetch_coinbase(product: str, start: datetime, end: datetime) -> list[dict]:
    bars: dict[str, dict] = {}
    gran = 86400
    chunk = timedelta(days=300)
    cur = start
    now = time.time()
    while cur < end:
        chunk_end = min(cur + chunk, end)
        q = {
            "granularity": str(gran),
            "start": cur.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "end": chunk_end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        url = f"https://api.exchange.coinbase.com/products/{product}/candles?" + urllib.parse.urlencode(q)
        data, _ = http_get_json(url)
        if isinstance(data, dict) and data.get("message"):
            raise RuntimeError(f"Coinbase {product}: {data.get('message')}")
        for row in data:
            t = int(row[0])
            if t + 86400 > now + 60:
                continue
            # [time, low, high, open, close, volume]
            b = bar_from_open_ts(t, row[3], row[2], row[1], row[4], row[5])
            if b:
                bars[b["session_date"]] = b
        cur = chunk_end
        time.sleep(0.25)
    return [bars[k] for k in sorted(bars.keys())]


def fetch_yahoo(symbol: str, start: datetime, end: datetime) -> list[dict]:
    q = {
        "period1": str(int(start.timestamp())),
        "period2": str(int(end.timestamp())),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?" + urllib.parse.urlencode(q)
    data, _ = http_get_json(url)
    result = data["chart"]["result"]
    if not result:
        raise RuntimeError(f"Yahoo empty for {symbol}: {data['chart'].get('error')}")
    r0 = result[0]
    ts = r0.get("timestamp") or []
    quote = r0["indicators"]["quote"][0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    vols = quote.get("volume") or []
    bars: dict[str, dict] = {}
    now = time.time()
    for i, t in enumerate(ts):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        if o is None or h is None or l is None or c is None:
            continue
        start_dt = datetime.fromtimestamp(int(t), tz=UTC)
        period_end = start_dt + timedelta(days=1)
        if period_end.timestamp() > now + 60:
            continue
        b = bar_from_open_ts(int(t), o, h, l, c, vols[i] if i < len(vols) else 0)
        if b:
            bars[b["session_date"]] = b
    return [bars[k] for k in sorted(bars.keys())]


def covers_lookback(bars: list[dict], min_days: int = LOOKBACK_DAYS - 60) -> bool:
    if len(bars) < max(300, min_days // 2):
        return False
    d0 = datetime.fromisoformat(bars[0]["session_date"]).date()
    d1 = datetime.fromisoformat(bars[-1]["session_date"]).date()
    return (d1 - d0).days >= min_days


def pull_symbol(sym: str) -> tuple[list[dict], str, str, str, str]:
    """Returns bars, source_name, source_uri, native, selection_note."""
    end = utc_now()
    start = end - timedelta(days=LOOKBACK_DAYS)
    start_sd = session_date_from_period_end_unix(int((start + timedelta(days=1)).timestamp()))
    notes = []

    # 1) Kraken
    try:
        bars = fetch_kraken(KRAKEN_PAIR[sym], since=int(start.timestamp()))
        bars = [b for b in bars if b["session_date"] >= start_sd]
        if covers_lookback(bars):
            uri = f"https://api.kraken.com/0/public/OHLC?pair={KRAKEN_PAIR[sym]}&interval=1440"
            return bars, "kraken", uri, KRAKEN_ALT[sym], "selected=kraken"
        span = 0
        if bars:
            span = (
                datetime.fromisoformat(bars[-1]["session_date"]).date()
                - datetime.fromisoformat(bars[0]["session_date"]).date()
            ).days
        notes.append(f"Kraken insufficient (bars={len(bars)}, span_days={span})")
        print(f"  {notes[-1]}")
    except Exception as e:
        notes.append(f"Kraken failed: {e}")
        print(f"  {notes[-1]}")

    # 2) Coinbase
    try:
        bars = fetch_coinbase(COINBASE_PRODUCT[sym], start, end)
        bars = [b for b in bars if b["session_date"] >= start_sd]
        if bars and covers_lookback(bars):
            uri = f"https://api.exchange.coinbase.com/products/{COINBASE_PRODUCT[sym]}/candles?granularity=86400"
            return bars, "coinbase_exchange", uri, COINBASE_PRODUCT[sym], "; ".join(notes + ["selected=coinbase_exchange"])
        if bars:
            notes.append(f"Coinbase short (bars={len(bars)})")
            print(f"  {notes[-1]}")
        else:
            notes.append("Coinbase 0 bars")
            print(f"  {notes[-1]}")
    except Exception as e:
        notes.append(f"Coinbase failed: {e}")
        print(f"  {notes[-1]}")

    # 3) Yahoo
    bars = fetch_yahoo(YAHOO[sym], start, end)
    bars = [b for b in bars if b["session_date"] >= start_sd]
    uri = f"https://query1.finance.yahoo.com/v8/finance/chart/{YAHOO[sym]}?interval=1d"
    return bars, "yahoo", uri, YAHOO[sym], "; ".join(notes + ["selected=yahoo"])


# ---- Indicators --------------------------------------------------------------

def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if n <= 0:
        return out
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if n <= 0 or not values or len(values) < n:
        return out
    k = 2.0 / (n + 1)
    seed = sum(values[:n]) / n
    out[n - 1] = seed
    prev = seed
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi_wilder(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n

    def _rsi(ag, al):
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    out[n] = _rsi(avg_g, avg_l)
    for i in range(n, len(gains)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
        out[i + 1] = _rsi(avg_g, avg_l)
    return out


def true_ranges(highs, lows, closes) -> list[float]:
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
    return trs


def atr_wilder(trs: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(trs)
    if len(trs) < n:
        return out
    atr = sum(trs[:n]) / n
    out[n - 1] = atr
    for i in range(n, len(trs)):
        atr = (atr * (n - 1) + trs[i]) / n
        out[i] = atr
    return out


def bollinger(closes: list[float], n: int = 20, k: float = 2.0):
    mid = sma(closes, n)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if mid[i] is None:
            continue
        window = closes[i - n + 1 : i + 1]
        mean = mid[i]
        var = sum((x - mean) ** 2 for x in window) / n
        std = math.sqrt(var)
        upper[i] = mean + k * std
        lower[i] = mean - k * std
    return upper, mid, lower


def compute_indicators(bars: list[dict]) -> list[dict]:
    if not bars:
        return []
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    dates = [b["session_date"] for b in bars]

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    rsi14 = rsi_wilder(closes, 14)
    trs = true_ranges(highs, lows, closes)
    atr14 = atr_wilder(trs, 14)

    atr60: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        if atr14[i] is None:
            continue
        if i >= 14 - 1 + 60 - 1:
            window = atr14[i - 59 : i + 1]
            if all(x is not None for x in window):
                atr60[i] = sum(window) / 60.0  # type: ignore
    atr_ratio: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        if atr14[i] is not None and atr60[i] not in (None, 0):
            atr_ratio[i] = atr14[i] / atr60[i]  # type: ignore

    bb_u, bb_m, bb_l = bollinger(closes, 20, 2.0)

    macd_line: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        if ema12[i] is not None and ema26[i] is not None:
            macd_line[i] = ema12[i] - ema26[i]  # type: ignore
    macd_signal: list[float | None] = [None] * len(bars)
    macd_hist: list[float | None] = [None] * len(bars)
    macd_compact = [(i, macd_line[i]) for i in range(len(bars)) if macd_line[i] is not None]
    if len(macd_compact) >= 9:
        vals = [v for _, v in macd_compact]
        idxs = [i for i, _ in macd_compact]
        e = ema(vals, 9)
        for j, idx in enumerate(idxs):
            if e[j] is not None:
                macd_signal[idx] = e[j]
                macd_hist[idx] = macd_line[idx] - e[j]  # type: ignore

    params = {
        "RSI_14": {"period": 14, "method": "wilder"},
        "MACD": {"fast": 12, "slow": 26, "signal": 9},
        "MACD_SIGNAL": {"fast": 12, "slow": 26, "signal": 9},
        "MACD_HIST": {"fast": 12, "slow": 26, "signal": 9},
        "BB_UPPER": {"period": 20, "k": 2.0, "ma": "sma"},
        "BB_MID": {"period": 20, "k": 2.0, "ma": "sma"},
        "BB_LOWER": {"period": 20, "k": 2.0, "ma": "sma"},
        "SMA_20": {"period": 20},
        "SMA_50": {"period": 50},
        "SMA_200": {"period": 200},
        "EMA_12": {"period": 12},
        "EMA_26": {"period": 26},
        "ATR_14": {"period": 14, "method": "wilder_tr"},
        "ATR_60D_AVG": {"period": 60, "of": "ATR_14"},
        "ATR_RATIO_14_60": {"num": "ATR_14", "den": "ATR_60D_AVG"},
    }
    series = {
        "SMA_20": sma20, "SMA_50": sma50, "SMA_200": sma200,
        "EMA_12": ema12, "EMA_26": ema26,
        "RSI_14": rsi14,
        "ATR_14": atr14, "ATR_60D_AVG": atr60, "ATR_RATIO_14_60": atr_ratio,
        "BB_UPPER": bb_u, "BB_MID": bb_m, "BB_LOWER": bb_l,
        "MACD": macd_line, "MACD_SIGNAL": macd_signal, "MACD_HIST": macd_hist,
    }
    out = []
    for i, sd in enumerate(dates):
        for name, arr in series.items():
            val = arr[i]
            if val is None or not math.isfinite(val):
                continue
            out.append({
                "session_date": sd,
                "name": name,
                "value": float(val),
                "params_json": json.dumps(params[name], sort_keys=True),
            })
    return out


def compute_regimes(bars: list[dict], indicators: list[dict]) -> list[dict]:
    """tf_trend_vol_v1: SMA_50 vs SMA_200 relation + SMA_50 slope + ATR_RATIO high_vol.

    Rules (deterministic, offline):
      - Require SMA_50 and SMA_200.
      - slope_50 = (SMA_50[t] - SMA_50[t-SLOPE_LB]) / SMA_50[t-SLOPE_LB]
        (skip if prior SMA_50 unavailable or zero).
      - high_vol if ATR_RATIO_14_60 > HV_THRESH (overrides base).
      - trend_up if SMA_50 > SMA_200*(1+BAND) and slope_50 >= 0
        (or relation up if slope unavailable).
      - trend_down if SMA_50 < SMA_200*(1-BAND) and slope_50 <= 0
        (or relation down if slope unavailable).
      - else range.
    """
    by: dict[str, dict] = {}
    for row in indicators:
        by.setdefault(row["session_date"], {})[row["name"]] = row["value"]
    dates = [b["session_date"] for b in bars]
    date_idx = {d: i for i, d in enumerate(dates)}
    out = []
    for b in bars:
        sd = b["session_date"]
        ind = by.get(sd) or {}
        sma50 = ind.get("SMA_50")
        sma200 = ind.get("SMA_200")
        atr_r = ind.get("ATR_RATIO_14_60")
        if sma50 is None or sma200 is None:
            continue
        # slope of SMA_50
        slope_50 = None
        i = date_idx[sd]
        if i >= SLOPE_LB:
            prev_sd = dates[i - SLOPE_LB]
            prev_sma50 = (by.get(prev_sd) or {}).get("SMA_50")
            if prev_sma50 not in (None, 0):
                slope_50 = (sma50 - prev_sma50) / prev_sma50

        high_vol = atr_r is not None and atr_r > HV_THRESH
        up = sma50 > sma200 * (1.0 + TREND_BAND)
        down = sma50 < sma200 * (1.0 - TREND_BAND)
        if up and (slope_50 is None or slope_50 >= 0):
            base = "trend_up"
        elif down and (slope_50 is None or slope_50 <= 0):
            base = "trend_down"
        elif up:
            base = "trend_up"  # relation dominates mild adverse slope
        elif down:
            base = "trend_down"
        else:
            base = "range"
        label = "high_vol" if high_vol else base
        score = (sma50 / sma200 - 1.0) if sma200 else None
        details = {
            "method": REGIME_METHOD,
            "params": {
                "trend_band": TREND_BAND,
                "slope_lookback": SLOPE_LB,
                "high_vol_threshold": HV_THRESH,
                "inputs": ["SMA_50", "SMA_200", "ATR_RATIO_14_60"],
            },
            "rules": {
                "trend_up": f"SMA_50 > SMA_200*(1+{TREND_BAND}) with slope_50>=0 (or slope NA)",
                "trend_down": f"SMA_50 < SMA_200*(1-{TREND_BAND}) with slope_50<=0 (or slope NA)",
                "range": "within band or conflicting slope/relation",
                "high_vol": f"ATR_RATIO_14_60 > {HV_THRESH} overrides base label",
            },
            "SMA_50": sma50,
            "SMA_200": sma200,
            "slope_50": slope_50,
            "ATR_RATIO_14_60": atr_r,
            "base_label": base,
            "high_vol": high_vol,
        }
        out.append({
            "as_of_date": sd,
            "label": label,
            "method": REGIME_METHOD,
            "score": score,
            "details_json": json.dumps(details, sort_keys=True),
        })
    return out


def checksum_bars(bars: list[dict]) -> str:
    h = hashlib.sha256()
    for b in bars:
        line = f"{b['session_date']},{b['open']},{b['high']},{b['low']},{b['close']},{b['volume']}\n"
        h.update(line.encode())
    return h.hexdigest()


def find_gaps(bars: list[dict]) -> list[dict]:
    if not bars:
        return [{"type": "empty", "note": "no bars"}]
    dates = [b["session_date"] for b in bars]
    d0 = datetime.fromisoformat(dates[0]).date()
    d1 = datetime.fromisoformat(dates[-1]).date()
    have = set(dates)
    gaps = []
    cur = d0
    while cur <= d1:
        s = cur.isoformat()
        if s not in have:
            gaps.append({"session_date": s, "type": "missing_bar"})
        cur += timedelta(days=1)
    return gaps


def ensure_calendar(conn: sqlite3.Connection, dmin: str, dmax: str) -> int:
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT session_date FROM trading_calendar WHERE session_date BETWEEN ? AND ?",
            (dmin, dmax),
        )
    }
    d0 = datetime.fromisoformat(dmin).date()
    d1 = datetime.fromisoformat(dmax).date()
    rows = []
    cur = d0
    while cur <= d1:
        s = cur.isoformat()
        if s not in existing:
            rows.append((s, 1, "regular", "crypto 24/7; no documented outage"))
        cur += timedelta(days=1)
    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO trading_calendar(session_date, is_open, session_label, notes) VALUES (?,?,?,?)",
            rows,
        )
    return len(rows)


def load_bars_from_db(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    rows = conn.execute(
        """SELECT session_date, open, high, low, close, volume
           FROM bars_daily WHERE symbol=? ORDER BY session_date""",
        (symbol,),
    ).fetchall()
    return [
        {
            "session_date": r[0],
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5] or 0.0,
        }
        for r in rows
    ]


def to_edt(iso_z: str) -> str:
    dt = datetime.strptime(iso_z, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(NY)
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    started = utc_now_iso()
    print(f"Starting secondary+extend backfill at {started}")
    print(f"Canonical DB: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"Canonical DB missing: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    # Ensure schema seeds (idempotent catalog)
    with open(SCHEMA) as f:
        # only run INSERT OR IGNORE catalog bits safely by ensuring tables exist
        pass
    for name, desc, risk in [
        ("RSI_14", "14-period Relative Strength Index", 0),
        ("MACD", "MACD line", 0),
        ("MACD_SIGNAL", "MACD signal line", 0),
        ("MACD_HIST", "MACD histogram", 0),
        ("BB_UPPER", "Bollinger upper", 0),
        ("BB_MID", "Bollinger mid", 0),
        ("BB_LOWER", "Bollinger lower", 0),
        ("SMA_20", "20-session SMA", 0),
        ("SMA_50", "50-session SMA", 0),
        ("SMA_200", "200-session SMA", 0),
        ("EMA_12", "12-session EMA", 0),
        ("EMA_26", "26-session EMA", 0),
        ("ATR_14", "14-period Average True Range", 1),
        ("ATR_60D_AVG", "60-session average of ATR_14", 1),
        ("ATR_RATIO_14_60", "ATR_14 / ATR_60D_AVG (Risk filter if > 1.8)", 1),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO indicator_catalog(name, description, required_for_risk) VALUES (?,?,?)",
            (name, desc, risk),
        )
    conn.commit()

    cur = conn.execute(
        """INSERT INTO backfill_runs(started_at_utc, status, universe_json, notes)
           VALUES (?,?,?,?)""",
        (
            started,
            "running",
            json.dumps(SECONDARY),
            "secondary daily OHLCV + extend indicators ALL symbols + regimes tf_trend_vol_v1",
        ),
    )
    run_id = cur.lastrowid
    conn.commit()

    report = {
        "secondary": {},
        "extend": {},
        "regimes": {},
        "failures": [],
        "blockers": [],
        "provenance_ids": [],
        "total_bars": 0,
        "total_indicators_new": 0,
        "total_regimes": 0,
        "all_gaps": {},
    }
    global_min = None
    global_max = None

    # ---- 1) Secondary OHLCV ----
    now_utc = utc_now_iso()
    for sym in SECONDARY:
        print(f"\n=== SECONDARY {sym} ===")
        # universe upsert
        exists = conn.execute("SELECT 1 FROM universe WHERE symbol=?", (sym,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO universe(symbol, asset_class, active, notes, added_at_utc) VALUES (?,?,?,?,?)",
                (sym, "other", 1, "secondary signal universe", now_utc),
            )
            conn.commit()

        try:
            bars, source_name, source_uri, native, sel_note = pull_symbol(sym)
        except Exception as e:
            msg = f"{sym}: pull failed: {e}"
            print(msg)
            report["failures"].append(msg)
            report["blockers"].append(msg)
            report["secondary"][sym] = {"error": str(e)}
            continue

        today_ny = datetime.now(NY).date().isoformat()
        bars = [b for b in bars if b["session_date"] <= today_ny]
        clean = []
        for b in bars:
            if b["high"] < b["low"]:
                continue
            if min(b["open"], b["high"], b["low"], b["close"]) <= 0:
                continue
            clean.append(b)
        bars = clean

        if not bars:
            msg = f"{sym}: zero bars from all sources"
            report["failures"].append(msg)
            report["blockers"].append(msg)
            report["secondary"][sym] = {"error": "zero bars"}
            continue

        # Skip dates already present (append-only / idempotent)
        existing_dates = {
            r[0]
            for r in conn.execute("SELECT session_date FROM bars_daily WHERE symbol=?", (sym,))
        }
        new_bars = [b for b in bars if b["session_date"] not in existing_dates]
        # For reporting use full desired series (existing+new); for insert only new
        if existing_dates and not new_bars:
            print(f"  {sym}: all {len(bars)} bars already in DB; skipping insert")
            bars_for_report = load_bars_from_db(conn, sym)
            gaps = find_gaps(bars_for_report)
            dmin, dmax = bars_for_report[0]["session_date"], bars_for_report[-1]["session_date"]
            report["secondary"][sym] = {
                "source": "already_present",
                "source_uri": None,
                "native": native,
                "date_min": dmin,
                "date_max": dmax,
                "bar_rows": len(bars_for_report),
                "bars_inserted": 0,
                "gap_count": len(gaps),
                "gaps_sample": gaps[:10],
                "provenance_id": None,
                "checksum": None,
                "note": "idempotent skip",
            }
            report["all_gaps"][sym] = gaps
            if global_min is None or dmin < global_min:
                global_min = dmin
            if global_max is None or dmax > global_max:
                global_max = dmax
            continue

        # Prefer writing the full pulled set if symbol is new; if partial existing, only new
        to_insert = new_bars if existing_dates else bars
        cs = checksum_bars(to_insert)
        pulled = utc_now_iso()
        notes = (
            f"native_venue_symbol={native}; interval=1d; adjust_method=none; "
            f"preferred_order=kraken>coinbase_exchange>yahoo; {sel_note}"
        )
        cur = conn.execute(
            """INSERT INTO data_provenance(source_name, source_uri, pulled_at_utc, as_of_utc, checksum, row_count, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (
                source_name,
                source_uri,
                pulled,
                to_insert[-1]["session_date"] + "T00:00:00Z",
                cs,
                len(to_insert),
                notes,
            ),
        )
        prov_id = cur.lastrowid
        report["provenance_ids"].append(prov_id)

        conn.executemany(
            """INSERT OR IGNORE INTO bars_daily(
                symbol, session_date, open, high, low, close, adj_close, volume,
                split_factor, dividend, adjust_method, provenance_id
            ) VALUES (?,?,?,?,?,?,NULL,?,NULL,NULL,'none',?)""",
            [
                (sym, b["session_date"], b["open"], b["high"], b["low"], b["close"], b["volume"], prov_id)
                for b in to_insert
            ],
        )
        conn.commit()

        bars_full = load_bars_from_db(conn, sym)
        gaps = find_gaps(bars_full)
        dmin, dmax = bars_full[0]["session_date"], bars_full[-1]["session_date"]
        if global_min is None or dmin < global_min:
            global_min = dmin
        if global_max is None or dmax > global_max:
            global_max = dmax

        report["secondary"][sym] = {
            "source": source_name,
            "source_uri": source_uri,
            "native": native,
            "date_min": dmin,
            "date_max": dmax,
            "bar_rows": len(bars_full),
            "bars_inserted": len(to_insert),
            "gap_count": len(gaps),
            "gaps_sample": gaps[:10],
            "provenance_id": prov_id,
            "checksum": cs,
            "selection_note": sel_note,
        }
        report["all_gaps"][sym] = gaps
        report["total_bars"] += len(to_insert)
        print(f"  source={source_name} inserted={len(to_insert)} total={len(bars_full)} {dmin}..{dmax} gaps={len(gaps)}")

    # Extend calendar for any new dates
    cal_added = 0
    if global_min and global_max:
        # also cover primary span already there; ensure union
        db_min = conn.execute("SELECT min(session_date) FROM bars_daily").fetchone()[0]
        db_max = conn.execute("SELECT max(session_date) FROM bars_daily").fetchone()[0]
        cal_added = ensure_calendar(conn, db_min, db_max)
        conn.commit()
        print(f"Calendar extended by {cal_added} days (span {db_min}..{db_max})")

    # ---- 2) EXTEND indicators for ALL symbols ----
    all_symbols = [r[0] for r in conn.execute("SELECT symbol FROM universe WHERE active=1 ORDER BY symbol")]
    print(f"\n=== EXTEND indicators for {all_symbols} ===")

    for sym in all_symbols:
        bars = load_bars_from_db(conn, sym)
        if not bars:
            report["extend"][sym] = {"error": "no bars"}
            report["blockers"].append(f"{sym}: no bars for indicators")
            continue

        # Existing indicator keys
        existing = {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT session_date, name FROM indicators_daily WHERE symbol=?", (sym,)
            )
        }
        ind_rows = compute_indicators(bars)
        # For secondary (new): insert all. For primary: only insert missing names/dates (extend).
        to_write = [r for r in ind_rows if (r["session_date"], r["name"]) not in existing]
        # Also: if primary already complete for EXTEND_NAMES, to_write may be empty — OK

        if not to_write:
            cov = {}
            for r in conn.execute(
                "SELECT name, count(*) FROM indicators_daily WHERE symbol=? GROUP BY name", (sym,)
            ):
                cov[r[0]] = r[1]
            report["extend"][sym] = {
                "bars": len(bars),
                "inserted": 0,
                "coverage": cov,
                "note": "already complete / nothing new",
                "provenance_id": None,
            }
            print(f"  {sym}: indicators already complete")
            continue

        payload = "\n".join(f"{r['session_date']},{r['name']},{r['value']}" for r in to_write)
        ind_cs = hashlib.sha256(payload.encode()).hexdigest()
        cur = conn.execute(
            """INSERT INTO data_provenance(source_name, source_uri, pulled_at_utc, checksum, row_count, notes)
               VALUES (?,?,?,?,?,?)""",
            (
                "offline_indicators_v1",
                f"offline://indicators_daily/{sym}",
                utc_now_iso(),
                ind_cs,
                len(to_write),
                f"Extend/compute indicators for {sym}; Wilder ATR/RSI; SMA/EMA/MACD/BB; skip warm-up only",
            ),
        )
        ind_prov = cur.lastrowid
        report["provenance_ids"].append(ind_prov)

        conn.executemany(
            """INSERT OR IGNORE INTO indicators_daily(symbol, session_date, name, value, params_json, provenance_id)
               VALUES (?,?,?,?,?,?)""",
            [
                (sym, r["session_date"], r["name"], r["value"], r["params_json"], ind_prov)
                for r in to_write
            ],
        )
        conn.commit()
        report["total_indicators_new"] += len(to_write)

        cov = {}
        for r in conn.execute(
            "SELECT name, count(*) FROM indicators_daily WHERE symbol=? GROUP BY name", (sym,)
        ):
            cov[r[0]] = r[1]
        report["extend"][sym] = {
            "bars": len(bars),
            "inserted": len(to_write),
            "coverage": cov,
            "provenance_id": ind_prov,
        }
        print(f"  {sym}: inserted {len(to_write)} indicator rows")

    # ---- 3) REGIMES for ALL symbols (tf_trend_vol_v1) ----
    print(f"\n=== REGIMES {REGIME_METHOD} ===")
    for sym in all_symbols:
        bars = load_bars_from_db(conn, sym)
        if not bars:
            continue
        # Load indicators from DB for this symbol
        ind_db = [
            {"session_date": r[0], "name": r[1], "value": r[2]}
            for r in conn.execute(
                "SELECT session_date, name, value FROM indicators_daily WHERE symbol=?",
                (sym,),
            )
        ]
        regimes = compute_regimes(bars, ind_db)
        # Idempotent: skip existing (symbol, as_of_date, method)
        existing_reg = {
            r[0]
            for r in conn.execute(
                "SELECT as_of_date FROM regimes WHERE symbol=? AND method=?",
                (sym, REGIME_METHOD),
            )
        }
        to_write = [r for r in regimes if r["as_of_date"] not in existing_reg]
        if not to_write:
            # counts from existing
            counts = {}
            for r in conn.execute(
                "SELECT label, count(*) FROM regimes WHERE symbol=? AND method=? GROUP BY label",
                (sym, REGIME_METHOD),
            ):
                counts[r[0]] = r[1]
            report["regimes"][sym] = {
                "inserted": 0,
                "total": len(existing_reg),
                "counts": counts,
                "note": "already present",
            }
            print(f"  {sym}: regimes already present ({len(existing_reg)})")
            continue

        reg_cs = hashlib.sha256(
            json.dumps([(r["as_of_date"], r["label"]) for r in to_write], sort_keys=True).encode()
        ).hexdigest()
        cur = conn.execute(
            """INSERT INTO data_provenance(source_name, source_uri, pulled_at_utc, checksum, row_count, notes)
               VALUES (?,?,?,?,?,?)""",
            (
                f"offline_regime_{REGIME_METHOD}",
                f"offline://regimes/{sym}/{REGIME_METHOD}",
                utc_now_iso(),
                reg_cs,
                len(to_write),
                (
                    f"{REGIME_METHOD}: SMA_50 vs SMA_200 relation (band={TREND_BAND}) + "
                    f"SMA_50 slope lookback={SLOPE_LB}; ATR_RATIO_14_60>{HV_THRESH} => high_vol"
                ),
            ),
        )
        reg_prov = cur.lastrowid
        report["provenance_ids"].append(reg_prov)

        conn.executemany(
            """INSERT OR IGNORE INTO regimes(
                symbol, as_of_date, label, method, score, details_json, provenance_id
            ) VALUES (?,?,?,?,?,?,?)""",
            [
                (sym, r["as_of_date"], r["label"], r["method"], r["score"], r["details_json"], reg_prov)
                for r in to_write
            ],
        )
        conn.commit()
        report["total_regimes"] += len(to_write)

        counts = {}
        for r in conn.execute(
            "SELECT label, count(*) FROM regimes WHERE symbol=? AND method=? GROUP BY label",
            (sym, REGIME_METHOD),
        ):
            counts[r[0]] = r[1]
        report["regimes"][sym] = {
            "inserted": len(to_write),
            "total": sum(counts.values()),
            "counts": counts,
            "provenance_id": reg_prov,
        }
        print(f"  {sym}: regimes inserted={len(to_write)} counts={counts}")

    finished = utc_now_iso()
    status = "ok"
    if report["failures"]:
        status = "partial" if report["total_bars"] or report["total_indicators_new"] else "failed"

    gaps_summary = {
        s: {"count": len(g), "sample": g[:20]} for s, g in report["all_gaps"].items()
    }
    # include primary gap note (0 expected)
    for sym in all_symbols:
        if sym not in gaps_summary:
            bars = load_bars_from_db(conn, sym)
            g = find_gaps(bars) if bars else []
            gaps_summary[sym] = {"count": len(g), "sample": g[:20]}

    db_min = conn.execute("SELECT min(session_date) FROM bars_daily").fetchone()[0]
    db_max = conn.execute("SELECT max(session_date) FROM bars_daily").fetchone()[0]
    rows_written = (
        report["total_bars"] + report["total_indicators_new"] + report["total_regimes"]
    )

    conn.execute(
        """UPDATE backfill_runs SET finished_at_utc=?, status=?, date_start=?, date_end=?,
           rows_written=?, gaps_json=?, provenance_ids_json=?, notes=? WHERE id=?""",
        (
            finished,
            status,
            db_min,
            db_max,
            rows_written,
            json.dumps(gaps_summary),
            json.dumps(report["provenance_ids"]),
            (
                f"secondary_bars={report['total_bars']} "
                f"indicators_new={report['total_indicators_new']} "
                f"regimes={report['total_regimes']} method={REGIME_METHOD}; "
                f"calendar_added={cal_added}"
            ),
            run_id,
        ),
    )
    conn.commit()

    # ---- Report markdown ----
    lines = []
    lines.append("# Temple Flow — Secondary + Extend Backfill Report")
    lines.append("")
    lines.append(f"- **Run started (UTC):** {started}")
    lines.append(f"- **Run finished (UTC):** {finished}")
    lines.append(f"- **Started (ET):** {to_edt(started)}")
    lines.append(f"- **Finished (ET):** {to_edt(finished)}")
    lines.append(f"- **Status:** `{status}`")
    lines.append(f"- **DB (canonical only):** `{DB_PATH}`")
    lines.append(f"- **backfill_runs.id:** {run_id}")
    lines.append(f"- **Secondary universe:** {', '.join(SECONDARY)}")
    lines.append(f"- **All active symbols after run:** {', '.join(all_symbols)}")
    lines.append(f"- **Lookback target:** ~5 years daily OHLCV")
    lines.append(f"- **DB date span:** {db_min} → {db_max}")
    lines.append(f"- **Secondary bars inserted:** {report['total_bars']}")
    lines.append(f"- **Indicator rows inserted (extend):** {report['total_indicators_new']}")
    lines.append(f"- **Regime rows inserted ({REGIME_METHOD}):** {report['total_regimes']}")
    lines.append(f"- **Calendar days added:** {cal_added}")
    lines.append(f"- **Provenance IDs:** {report['provenance_ids']}")
    lines.append("")
    lines.append("## Secondary OHLCV summary")
    lines.append("")
    lines.append("| Symbol | Source | Native | Date min | Date max | Bars | Inserted | Gaps |")
    lines.append("| --- | --- | --- | --- | --- | ---: | ---: | ---: |")
    for sym in SECONDARY:
        info = report["secondary"].get(sym, {})
        if "error" in info:
            lines.append(f"| {sym} | FAIL | — | — | — | 0 | 0 | — |")
            continue
        lines.append(
            f"| {sym} | {info.get('source')} | `{info.get('native')}` | {info.get('date_min')} | "
            f"{info.get('date_max')} | {info.get('bar_rows')} | {info.get('bars_inserted')} | "
            f"{info.get('gap_count')} |"
        )
    lines.append("")
    lines.append("## Sources & provenance (secondary)")
    lines.append("")
    for sym in SECONDARY:
        info = report["secondary"].get(sym, {})
        lines.append(f"### {sym}")
        if "error" in info:
            lines.append(f"- **Failure / blocker:** {info['error']}")
            lines.append("")
            continue
        lines.append(f"- **source_name:** `{info.get('source')}`")
        lines.append(f"- **source_uri:** `{info.get('source_uri')}`")
        lines.append(f"- **native venue symbol:** `{info.get('native')}`")
        lines.append(f"- **provenance_id (bars):** {info.get('provenance_id')}")
        lines.append(f"- **checksum (bars):** `{info.get('checksum')}`")
        lines.append(f"- **selection note:** {info.get('selection_note') or info.get('note')}")
        lines.append("- **adjust_method:** `none` (spot); adj_close/split/dividend null")
        lines.append(f"- **session_date:** America/New_York date of daily bar period end")
        lines.append("")

    lines.append("## Indicator coverage (all symbols)")
    lines.append("")
    for sym in all_symbols:
        info = report["extend"].get(sym, {})
        lines.append(f"### {sym}")
        if "error" in info:
            lines.append(f"- **Error:** {info['error']}")
            lines.append("")
            continue
        lines.append(f"- bars: {info.get('bars')}")
        lines.append(f"- indicator rows inserted this run: {info.get('inserted')}")
        lines.append(f"- provenance_id: {info.get('provenance_id')}")
        if info.get("note"):
            lines.append(f"- note: {info['note']}")
        lines.append("")
        lines.append("| Indicator | Rows |")
        lines.append("| --- | ---: |")
        cov = info.get("coverage") or {}
        for name in ALL_INDICATOR_NAMES:
            c = cov.get(name, 0)
            flag = "" if c else " _(warm-up / missing)_"
            lines.append(f"| `{name}` | {c}{flag} |")
        lines.append("")

    lines.append(f"## Regimes (`{REGIME_METHOD}`)")
    lines.append("")
    lines.append(
        f"Deterministic offline method `{REGIME_METHOD}`: "
        f"SMA_50 vs SMA_200 relation (band={TREND_BAND}) + SMA_50 slope "
        f"(lookback={SLOPE_LB}) + ATR_RATIO_14_60 high_vol flag (threshold={HV_THRESH}). "
        "Params cited in each row's `details_json`. FK via `universe.symbol`."
    )
    lines.append("")
    lines.append("| Symbol | Inserted | Total | trend_up | trend_down | range | high_vol |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for sym in all_symbols:
        info = report["regimes"].get(sym, {})
        c = info.get("counts") or {}
        lines.append(
            f"| {sym} | {info.get('inserted', 0)} | {info.get('total', 0)} | "
            f"{c.get('trend_up', 0)} | {c.get('trend_down', 0)} | "
            f"{c.get('range', 0)} | {c.get('high_vol', 0)} |"
        )
    lines.append("")

    lines.append("## Gaps")
    lines.append("")
    lines.append(
        "Crypto calendar: every America/New_York day `is_open=1` except documented outages. "
        "No equity holidays treated as missing. No bars invented."
    )
    lines.append("")
    for sym in SECONDARY:
        gaps = report["all_gaps"].get(sym, [])
        lines.append(f"### {sym}")
        lines.append(f"- Missing session_date count: **{len(gaps)}**")
        if gaps:
            sample = ", ".join(g["session_date"] for g in gaps[:15])
            more = f" … (+{len(gaps)-15} more)" if len(gaps) > 15 else ""
            lines.append(f"- Sample: {sample}{more}")
        else:
            lines.append("- No gaps in contiguous daily series.")
        lines.append("")

    lines.append("## Failures / blockers")
    lines.append("")
    if report["blockers"] or report["failures"]:
        for f in report["blockers"] or report["failures"]:
            lines.append(f"- {f}")
    else:
        lines.append("- None.")
    lines.append("")
    lines.append("## Validation notes")
    lines.append("")
    lines.append("- Appended to canonical DB only; no second database created.")
    lines.append("- Source order honored: Kraken → Coinbase Exchange → Yahoo.")
    lines.append("- Indicators computed offline from stored bars; warm-up skipped (no invention).")
    lines.append(f"- Regimes method `{REGIME_METHOD}` reproducible from params in details_json.")
    lines.append("")

    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines))

    # also write a short log
    log_path = f"{LOG_DIR}/{started.replace(':', '')}_secondary_daily.md"
    with open(log_path, "w") as f:
        f.write("\n".join(lines))

    conn.close()
    print(f"\nWrote report {REPORT_PATH}")
    print(f"DB {DB_PATH} status={status} run_id={run_id}")
    return report


if __name__ == "__main__":
    main()
