#!/usr/bin/env python3
"""Temple Flow eyes — on-demand, read-only market data from Twelve Data.

WHY THIS EXISTS: every price the Act loop sees comes from Schwab. When the
Schwab login lapses the desk goes blind: no quotes, no history, no plan. This
tool is a second pair of eyes that does not depend on Schwab at all.

WHAT IT IS: a command an operating agent CALLS when it needs to look. It is not
a daemon and it never polls. Nothing runs, and no credit is spent, unless
someone asks. Every call is metered against the plan's budget in a local ledger
and answered from a disk cache when the cache is fresh enough.

WHAT IT IS NOT: a data source for execution. `book_is_live_eligible` in the wire
only lets a proven Schwab read drive a POST or DELETE, and this file does not
change that. It does not import the wire, it cannot place, change or cancel an
order, it writes nowhere except its own cache directory, and everything it
prints is stamped `evidence_only`. Sizing still comes from live Schwab equity,
never from here.

Standard library only. The key is read from TWELVE_DATA_API_KEY (or an ignored
.env), sent as a header, and never printed, logged, cached or put in a URL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

PROVIDER = "twelve_data"
KEY_ENV = "TWELVE_DATA_API_KEY"
API_BASE = "https://api.twelvedata.com"
USER_AGENT = "temple-flow-eyes/1.0 (+read-only; on-demand)"
MINUTE_LIMIT = 8  # Basic plan: 8 credits per minute
PLAN_DAY_LIMIT = 800  # Basic plan: 800 credits per UTC day; no setting may exceed it
DEFAULT_DAY_BUDGET = 400  # half of the plan; the Tape apps share the key
QUOTE_TTL_S = 120  # a second look inside two minutes is answered from disk
HISTORY_TTL_S = 6 * 3600  # finished daily bars do not change within a session
STALE_AFTER_S = 900  # open (or unknown) market: a last print older than this is stale
CLOSED_STALE_AFTER_S = 5 * 86400  # closed market: older than a long weekend is stale
HISTORY_DAYS = 260  # same one-year window the planner reads
MAX_HISTORY_DAYS = 4999  # outputsize is days + 1 and the provider caps it at 5000
HTTP_TIMEOUT_S = 15.0
# ET. A bar dated today is unfinished before this. Twenty minutes past the bell,
# not five: the provider's daily bar is provisional right after 16:00, and a
# provisional close cached as finished would be served for hours.
EQUITY_CLOSE = dt.time(16, 20)
ATR_FILTER_MULTIPLE = 1.8  # RISK_CONSTITUTION: ATR14 > 1.8x its 60-day average
# Mirrors temple_flow_strategy.PARAMS. A test holds the two together.
FEATURE_PARAMS = {"sma_fast": 20, "sma_slow": 50, "slope_lookback": 5, "atr_period": 14}
DESK_SYMBOLS = ("ETHA", "IBIT", "NVO", "NOK")  # the four names the wire quotes
CRYPTO_ANCHORS = ("BTC-USD", "ETH-USD")  # docs/UNIVERSE.md: the spot signals behind IBIT and ETHA
REPO_ROOT = Path(__file__).resolve().parent.parent
# The cache may never live where the wire or a human reads: a ledger.json inside
# config/outbox would sit in the wire's ticket glob.
CACHE_FORBIDDEN = ("config", "logs", "scripts", "docs", "schemas", "runbooks", "skills", "bots", "deploy")
UTC = dt.timezone.utc
ET = ZoneInfo("America/New_York")
_LEDGER_EVENT = re.compile(r'\{"t": ([0-9]+(?:\.[0-9]+)?), "n": ([0-9]+), "what": "[^"]*"(, "minute_only": true)?\}')


def _utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


# ---------------------------------------------------------------- key handling
def _read_env_value(path: Path, name: str) -> str:
    """One variable out of a KEY=VALUE file. Only that one is ever kept: the
    broker's .env also holds Schwab secrets, and this tool has no use for them."""
    try:
        text = Path(path).read_text()
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        left, _, value = line.partition("=")
        if left.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def _usable_key(value: str) -> bool:
    """A key with whitespace or control characters cannot be a header value, and
    the error urllib raises for it would quote the key back at us."""
    return bool(value) and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)


def load_key(environ: Mapping[str, str] | None = None, env_files: Iterable[Path] | None = None) -> str | None:
    """The API key, or None. The environment wins; then each env file in order.

    Returned to the caller and nowhere else: this never writes the key into
    os.environ, so a child process or a crash dump does not inherit it.
    """
    env = os.environ if environ is None else environ
    candidates = [str(env.get(KEY_ENV) or "").strip()]
    candidates += [_read_env_value(Path(p), KEY_ENV).strip() for p in (env_files or [])]
    for value in candidates:
        if _usable_key(value):
            return value
    return None


def redact(text: Any, key: str | None) -> str:
    """`text` with the key removed, in plain, URL-encoded and escaped forms.
    Twelve Data echoes the key in some error messages."""
    s = str(text)
    if not key:
        return s
    forms = {key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key),
             repr(key)[1:-1], json.dumps(key)[1:-1]}
    for form in sorted(forms, key=len, reverse=True):
        if form:
            s = s.replace(form, "[redacted]")
    return s


def parse_day_budget(raw: Any) -> int:
    """Credits per UTC day this machine may spend. Zero is a real answer (spend
    nothing); nonsense falls back to the default; nothing exceeds the plan."""
    x = _f(raw)
    if x is None or x < 0:
        return DEFAULT_DAY_BUDGET
    return min(int(x), PLAN_DAY_LIMIT)


def safe_cache_dir(path: Path) -> Path:
    """`path`, unless it sits inside a directory the wire or a human reads."""
    p = Path(path).resolve()
    for name in CACHE_FORBIDDEN:
        bad = REPO_ROOT / name
        if p == bad or bad in p.parents:
            raise ValueError("cache directory may not be inside %s/" % name)
    return p


# -------------------------------------------------------------------- symbols
def provider_symbol(symbol: str) -> str:
    """Desk label -> Twelve Data symbol. BTC-USD -> BTC/USD; equities unchanged."""
    s = str(symbol).strip().upper()
    if "-" in s and "/" not in s:
        base, _, quote = s.partition("-")
        if base and quote:
            return base + "/" + quote
    return s


def desk_symbol(symbol: str) -> str:
    """Twelve Data symbol -> desk label. BTC/USD -> BTC-USD."""
    return str(symbol).strip().upper().replace("/", "-")


def is_pair(symbol: str) -> bool:
    """True for crypto/forex pairs, which trade around the clock in UTC days."""
    return "/" in provider_symbol(symbol)


# --------------------------------------------------------------------- ledger
class Ledger:
    """What this machine has spent, so no caller can overrun the plan.

    Two limits bind: a rolling 60 second window (8 credits) and a UTC-day
    budget. `reserve` reads, decides and charges inside ONE file lock, so two
    agents calling at the same instant cannot both be granted the same credit.
    If the ledger cannot be written, nothing is granted: spend that cannot be
    metered is spend that does not happen.
    """

    def __init__(
        self,
        path: Path,
        now: Callable[[], dt.datetime] = _utcnow,
        day_budget: int = DEFAULT_DAY_BUDGET,
        minute_limit: int = MINUTE_LIMIT,
    ):
        self.path = Path(path)
        self.now = now
        self.day_budget = max(0, int(day_budget))
        self.minute_limit = int(minute_limit)

    # -- storage (callers hold the lock)
    def _read(self) -> list | None:
        """Events, [] when there is no file yet, None when the file is unreadable."""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
            events = data["events"]
            return [e for e in events if isinstance(e, dict) and "t" in e and "n" in e]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write(self, events: list) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"events": events}))
        os.replace(tmp, self.path)

    def _locked(self, fn: Callable[[], Any]) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return fn()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _heal_unlocked(self) -> list:
        """Quarantine an unreadable ledger and start a new one that (a) treats
        this minute as spent and (b) keeps whatever spend can still be read out
        of the wreck. With nothing to salvage, assume half the day is gone: a
        lost counter must not read as an untouched budget."""
        now_ts = self.now().timestamp()
        try:
            wreck = self.path.read_text(errors="replace")
        except OSError:
            wreck = ""
        salvaged = []
        for m in _LEDGER_EVENT.finditer(wreck):
            t, n = float(m.group(1)), int(m.group(2))
            if 0 <= now_ts - t < 48 * 3600:
                ev = {"t": t, "n": n, "what": "salvaged"}
                if m.group(3):
                    ev["minute_only"] = True
                salvaged.append(ev)
        if not salvaged:
            salvaged = [{"t": now_ts, "n": self.day_budget // 2, "what": "unknown_spend_assumed"}]
        try:
            os.replace(self.path, self.path.with_name(self.path.name + ".corrupt-%d" % int(now_ts)))
        except OSError:
            pass
        fresh = salvaged + [{"t": now_ts, "n": self.minute_limit, "what": "ledger_healed", "minute_only": True}]
        self._write(fresh)
        return fresh

    def _events_unlocked(self) -> tuple[list, bool]:
        events = self._read()
        if events is None:
            return self._heal_unlocked(), True
        return events, False

    # -- arithmetic
    @staticmethod
    def _minute_events(events: list, now_ts: float) -> list:
        return [e for e in events if now_ts - float(e["t"]) < 60.0]

    def _status_from(self, events: list, healed: bool) -> dict:
        now = self.now()
        day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_used = sum(int(e["n"]) for e in events if float(e["t"]) >= day_start and not e.get("minute_only"))
        return {
            # Reported raw: an overrun must be visible, not rounded down to the limit.
            "minute_used": sum(int(e["n"]) for e in self._minute_events(events, now.timestamp())),
            "minute_limit": self.minute_limit,
            "day_used": day_used,
            "day_budget": self.day_budget,
            "day_remaining": max(0, self.day_budget - day_used),
            "ledger_healed": healed,
        }

    def _retry_after_from(self, events: list, n: int) -> int:
        now_ts = self.now().timestamp()
        n = max(1, min(int(n), self.minute_limit))
        live = sorted(self._minute_events(events, now_ts), key=lambda e: float(e["t"]))
        used = sum(int(e["n"]) for e in live)
        wait = 0.0
        for e in live:
            if used + n <= self.minute_limit:
                break
            used -= int(e["n"])
            wait = 60.0 - (now_ts - float(e["t"]))
        return max(0, int(round(wait)))

    def seconds_to_next_day(self) -> int:
        now = self.now().astimezone(UTC)
        nxt = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(1, int((nxt - now).total_seconds()))

    # -- public operations (each takes the lock exactly once)
    def status(self) -> dict:
        return self._locked(lambda: self._status_from(*self._events_unlocked()))

    def allowance(self) -> int:
        s = self.status()
        return max(0, min(s["minute_limit"] - s["minute_used"], s["day_remaining"]))

    def retry_after(self, n: int) -> int:
        return self._locked(lambda: self._retry_after_from(self._events_unlocked()[0], n))

    def reserve(self, n: int, what: str) -> dict:
        """Grant up to `n` credits and charge them, atomically.

        Returns {"granted", "reason", "retry_after_s"}. `reason` names the limit
        that held credits back (None when all `n` were granted). On a tie the
        minute is blamed: it clears in seconds, the day does not.
        """
        def op() -> dict:
            events, healed = self._events_unlocked()
            st = self._status_from(events, healed)
            minute_room = max(0, st["minute_limit"] - st["minute_used"])
            day_room = st["day_remaining"]
            granted = max(0, min(int(n), minute_room, day_room))
            if granted:
                now_ts = self.now().timestamp()
                events = [e for e in events if now_ts - float(e["t"]) < 48 * 3600]
                events.append({"t": now_ts, "n": granted, "what": str(what)})
                self._write(events)
            short = int(n) - granted
            reason = None
            retry = 0
            if short > 0:
                by_day = day_room < minute_room
                reason = "day_budget" if by_day else "minute_budget"
                retry = self.seconds_to_next_day() if by_day else self._retry_after_from(events, short)
            return {"granted": granted, "reason": reason, "retry_after_s": retry}

        return self._locked(op)

    def record(self, n: int, what: str, minute_only: bool = False) -> None:
        """Charge `n` credits unconditionally. `minute_only` closes the minute
        without charging the day: for credits someone else spent on the shared
        key, and for a provider that said slow down."""
        if int(n) <= 0:
            return

        def op() -> None:
            events, _ = self._events_unlocked()
            now_ts = self.now().timestamp()
            events = [e for e in events if now_ts - float(e["t"]) < 48 * 3600]
            event = {"t": now_ts, "n": int(n), "what": str(what)}
            if minute_only:
                event["minute_only"] = True
            events.append(event)
            self._write(events)

        self._locked(op)

    def close_minute(self, what: str) -> None:
        # status() then record() is two locks, unlike reserve(). That is safe
        # here because this can only ADD minute-only credits: two callers racing
        # leave the minute at or above the limit, never below it.
        s = self.status()
        self.record(s["minute_limit"] - s["minute_used"], what, minute_only=True)


# ------------------------------------------------------------------ transport
def http_get(path: str, params: dict, key: str, timeout: float) -> dict:
    """One GET. The key rides in the Authorization header, never the URL, so it
    cannot land in a proxy log, a shell history or an exception message."""
    url = API_BASE + path + "?" + urllib.parse.urlencode(params, safe="/,")
    req = urllib.request.Request(url, headers={"Authorization": "apikey " + key, "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            headers = dict(resp.headers)
            raw = resp.read()
    except urllib.error.HTTPError as e:
        status, headers, raw = int(e.code), dict(e.headers or {}), e.read()
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        body = {}
    kept = {str(k).lower(): v for k, v in headers.items() if str(k).lower().startswith("api-credits")}
    return {"status": status, "headers": kept, "body": body}


# ----------------------------------------------------------------------- math
# The planner's arithmetic (temple_flow_wire.py), copied rather than imported:
# importing the wire would give this file a path to the order functions.
# test_temple_flow_eyes.py proves sma, sma_slope, atr, window_return and
# closes_of agree with the wire on the same candles.
#
# ONE DELIBERATE DIFFERENCE: this _f is stricter than the wire's. The wire lets
# True, "NaN" and "inf" through as 1.0, nan and inf. Text from a data vendor is
# less trusted than a broker field, so here those are None and the bar is
# dropped, instead of one bad close turning a whole moving average into NaN.
def _f(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def closes_of(candles: list) -> list:
    out = []
    for c in candles or []:
        v = _f((c or {}).get("close")) if isinstance(c, dict) else None
        if v is not None:
            out.append(v)
    return out


def sma(values: list, n: int) -> float | None:
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / float(n)


def sma_slope(values: list, n: int, lookback: int) -> float | None:
    if n <= 0 or lookback <= 0 or len(values) < n + lookback:
        return None
    now_sma = sma(values, n)
    then_sma = sma(values[: len(values) - lookback], n)
    if now_sma is None or then_sma is None:
        return None
    return (now_sma - then_sma) / float(lookback)


def atr(candles: list, n: int) -> float | None:
    """Simple n-period mean true range (not Wilder's), exactly as the planner."""
    if n <= 0 or len(candles or []) < n + 1:
        return None
    trs: list = []
    for i in range(len(candles) - n, len(candles)):
        cur = candles[i] if isinstance(candles[i], dict) else {}
        prev = candles[i - 1] if isinstance(candles[i - 1], dict) else {}
        hi, lo, prev_close = _f(cur.get("high")), _f(cur.get("low")), _f(prev.get("close"))
        if hi is None or lo is None or prev_close is None:
            return None
        trs.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))
    if len(trs) != n:
        return None
    return sum(trs) / float(n)


def window_return(values: list, n: int) -> float | None:
    if n <= 0 or len(values) < n + 1:
        return None
    base = values[-(n + 1)]
    if base == 0:
        return None
    return (values[-1] - base) / base


def atr_average(candles: list, n: int, sessions: int = 60) -> float | None:
    """Mean of the n-period ATR over the last `sessions` sessions.

    This is the eyes' reading of the constitution's "60-day average ATR". No
    code in this repo defines it, so treat `atr_filter` as a prompt to look,
    not as the Risk Manager's verdict. Needs n + sessions bars; None below that.
    """
    if len(candles or []) < n + sessions:
        return None
    vals = []
    for end in range(len(candles) - sessions + 1, len(candles) + 1):
        v = atr(candles[:end], n)
        if v is None:
            return None
        vals.append(v)
    return sum(vals) / float(len(vals))


def features(candles: list, last: float | None) -> dict:
    """The planner's feature names, plus the constitution's volatility filter.
    Every key is always present; None means "could not be computed"."""
    p = FEATURE_PARAMS
    candles = candles or []
    closes = closes_of(candles)
    fast, slow = sma(closes, p["sma_fast"]), sma(closes, p["sma_slow"])
    # atr() gets the list exactly as given, as the wire's would. Compacting it
    # first would measure a true range across a missing day and return a number
    # where atr() is right to say None.
    atr_now = atr(candles, p["atr_period"])
    atr_avg = atr_average(candles, p["atr_period"], 60)
    ratio = (atr_now / atr_avg) if (atr_now is not None and atr_avg not in (None, 0)) else None
    return {
        "bars": len(closes),
        "sma20": fast,
        "sma50": slow,
        "sma20_above_sma50": (fast > slow) if (fast is not None and slow is not None) else None,
        "sma20_slope": sma_slope(closes, p["sma_fast"], p["slope_lookback"]),
        "sma50_slope": sma_slope(closes, p["sma_slow"], p["slope_lookback"]),
        "atr14": atr_now,
        "atr_60d_avg": atr_avg,
        "atr_ratio": ratio,
        "atr_filter": (ratio > ATR_FILTER_MULTIPLE) if ratio is not None else None,
        "ret5d": window_return(closes, 5),
        "dist_to_sma20_pct": ((last - fast) / fast) if (last is not None and fast not in (None, 0)) else None,
    }


# ----------------------------------------------------------------------- eyes
class Eyes:
    """Looks when asked. Holds the key, the cache, the ledger and the clock."""

    def __init__(
        self,
        key: str | None,
        cache_dir: Path,
        now: Callable[[], dt.datetime] = _utcnow,
        transport: Callable[..., dict] | None = None,
        day_budget: int = DEFAULT_DAY_BUDGET,
        timeout: float = HTTP_TIMEOUT_S,
    ):
        self.key = key or None
        self.cache_dir = Path(cache_dir)
        self.now = now
        self.transport = transport
        self.timeout = float(timeout)
        self.ledger = Ledger(self.cache_dir / "ledger.json", now=now, day_budget=day_budget)

    # -- cache
    def _cache_path(self, kind: str, symbol: str, extra: str = "") -> Path:
        safe = provider_symbol(symbol).replace("/", "_")
        return self.cache_dir / ("%s_%s%s.json" % (kind, safe, extra))

    def _cache_get(self, kind: str, symbol: str, ttl: float, extra: str = "",
                   not_before: float | None = None) -> tuple[dict, int] | None:
        try:
            blob = json.loads(self._cache_path(kind, symbol, extra).read_text())
            fetched = float(blob["fetched_at"])
            age = self.now().timestamp() - fetched
            if not_before is not None and fetched < not_before:
                return None
            if 0 <= age <= ttl and isinstance(blob["data"], dict):
                return blob["data"], int(age)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _cache_put(self, kind: str, symbol: str, data: dict, extra: str = "") -> None:
        try:
            path = self._cache_path(kind, symbol, extra)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"fetched_at": self.now().timestamp(), "data": data}))
            os.replace(tmp, path)
        except OSError:
            pass  # an answer that cannot be cached is still an answer

    def _session_boundary(self, sym: str) -> float:
        """The last moment a new finished daily bar appeared for `sym`. History
        fetched before it is one session short and must not be served."""
        now = self.now()
        if is_pair(sym):
            return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        mark = now.astimezone(ET).replace(hour=EQUITY_CLOSE.hour, minute=EQUITY_CLOSE.minute, second=0, microsecond=0)
        if mark > now:
            mark -= dt.timedelta(days=1)
        while mark.weekday() >= 5:
            mark -= dt.timedelta(days=1)
        return mark.timestamp()

    def _ledger_status(self) -> dict:
        try:
            return self.ledger.status()
        except OSError as ex:
            return {"ledger_unavailable": True, "detail": "%s" % type(ex).__name__}

    # -- the shared look: cache first, then as much as the budget allows
    def _gather(self, kind, path, symbols, ttl, use_cache, params, normalize, extra="", boundary=False) -> dict:
        wanted: list = []
        for s in symbols:
            label = desk_symbol(s)
            if label and label not in wanted:
                wanted.append(label)
        found: dict = {}
        need: list = []
        for sym in wanted:
            not_before = self._session_boundary(sym) if boundary else None
            hit = self._cache_get(kind, sym, ttl, extra, not_before) if use_cache else None
            if hit:
                found[sym] = {"data": hit[0], "cache_age_s": hit[1], "from_cache": True}
            else:
                need.append(sym)

        errors: dict = {}
        deferred: list = []
        spent = 0
        provider_reported = None
        if need and not self.key:
            for sym in need:
                errors[sym] = {"reason": "no_api_key", "detail": "set %s (environment or an ignored .env)" % KEY_ENV}
            need = []
        if need:
            try:
                # Read, decide and charge in one locked step, BEFORE the request:
                # a call that dies on the way back may still have cost a credit,
                # and the pessimistic count is the one that cannot overrun.
                grant = self.ledger.reserve(len(need), "%s:%s" % (kind, ",".join(need)))
            except OSError as ex:
                for sym in need:
                    errors[sym] = {"reason": "ledger_unavailable",
                                   "detail": "cannot meter spend (%s), so nothing was spent" % type(ex).__name__}
                grant = None
            if grant is not None:
                go, wait = need[: grant["granted"]], need[grant["granted"]:]
                if go:
                    spent = len(go)
                    outcome, provider_reported = self._fetch(path, go, params, normalize)
                    self._reconcile(provider_reported)
                    for sym, res in outcome.items():
                        if "data" in res:
                            self._cache_put(kind, sym, res["data"], extra)
                            found[sym] = {"data": res["data"], "cache_age_s": 0, "from_cache": False}
                        else:
                            errors[sym] = res
                for sym in wait:
                    deferred.append({"symbol": sym, "reason": grant["reason"], "retry_after_s": grant["retry_after_s"]})
        return {
            "wanted": wanted, "found": found, "errors": errors, "deferred": deferred,
            "spent": spent, "provider_reported": provider_reported,
        }

    def _reconcile(self, reported: dict | None) -> None:
        """The key is shared (the Tape apps use it too), so this machine's
        ledger can undercount. Twelve Data reports the true per-minute figure;
        when it is higher, close the gap. It only ever tightens: a lower number
        from the provider never hands credits back. (Read-then-record is two
        locks; a race here can only over-tighten, which is the safe direction.)"""
        used = (reported or {}).get("used")
        if used is None:
            return
        try:
            gap = int(used) - self.ledger.status()["minute_used"]
            if gap > 0:
                self.ledger.record(gap, "provider_reported", minute_only=True)
        except OSError:
            pass

    def _fetch(self, path, symbols, params, normalize) -> tuple[dict, dict | None]:
        call = dict(params)
        call["symbol"] = ",".join(provider_symbol(s) for s in symbols)
        transport = self.transport or http_get
        try:
            resp = transport(path, call, self.key or "", self.timeout)
        except Exception as ex:  # noqa: BLE001 - any transport failure is one reason
            detail = redact("%s: %s" % (type(ex).__name__, ex), self.key)
            return {s: {"reason": "network_error", "detail": detail} for s in symbols}, None
        status = int(resp.get("status") or 0)
        body = resp.get("body")
        hdrs = resp.get("headers") or {}
        reported = None
        if "api-credits-used" in hdrs or "api-credits-left" in hdrs:
            reported = {"used": _f(hdrs.get("api-credits-used")), "left": _f(hdrs.get("api-credits-left"))}
        top_error = isinstance(body, dict) and body.get("status") == "error" and "code" in body
        code = int(_f(body.get("code")) or status) if isinstance(body, dict) else status
        if status == 429 or (top_error and code == 429):
            try:
                self.ledger.close_minute("rate_limited")
            except OSError:
                pass
            note = "provider said slow down; minute closed locally"
            return {s: {"reason": "rate_limited", "detail": note} for s in symbols}, reported
        if status >= 400 or top_error or not isinstance(body, dict):
            msg = redact(body.get("message") if isinstance(body, dict) else "unreadable body", self.key)
            return {s: {"reason": "provider_error", "code": code, "detail": msg} for s in symbols}, reported
        out: dict = {}
        for sym in symbols:
            obj = body if len(symbols) == 1 else body.get(provider_symbol(sym))
            if isinstance(obj, dict) and obj.get("status") == "error":
                out[sym] = {"reason": "provider_error", "code": obj.get("code"),
                            "detail": redact(obj.get("message"), self.key)}
                continue
            data = normalize(sym, obj) if isinstance(obj, dict) else None
            out[sym] = {"data": data} if data else {"reason": "bad_payload", "detail": "no usable data in the response"}
        return out, reported

    def _envelope(self, op: str, g: dict) -> dict:
        credits = {"spent_this_call": g["spent"]}
        credits.update(self._ledger_status())
        if g["provider_reported"]:
            credits["provider_reported"] = g["provider_reported"]
        return {
            "op": op,
            "source": PROVIDER,
            "evidence_only": True,
            "not_for_execution": True,
            # When the question was asked. Each symbol says when ITS data was
            # fetched (`fetched_at`) and how old the print is (`quote_age_s`).
            "as_of": self.now().astimezone(ET).isoformat(timespec="seconds"),
            "symbols": {},
            "deferred": g["deferred"],
            "complete": not g["deferred"] and not g["errors"],
            "credits": credits,
        }

    def _fetched_at(self, cache_age_s: int) -> str:
        return (self.now() - dt.timedelta(seconds=cache_age_s)).astimezone(ET).isoformat(timespec="seconds")

    # -- quotes
    @staticmethod
    def _normalize_quote(sym: str, obj: dict) -> dict | None:
        last = _f(obj.get("close"))
        if last is None:
            return None
        qt = _f(obj.get("last_quote_at"))
        is_open = obj.get("is_market_open")
        return {
            "symbol": sym,
            "provider_symbol": provider_symbol(sym),
            "last": last,
            "open": _f(obj.get("open")),
            "high": _f(obj.get("high")),
            "low": _f(obj.get("low")),
            "volume": _f(obj.get("volume")),
            "previous_close": _f(obj.get("previous_close")),
            "change_pct": _f(obj.get("percent_change")),
            "is_market_open": is_open if isinstance(is_open, bool) else None,
            "quote_time": int(qt) if qt is not None and qt > 0 else None,
            "venue": obj.get("exchange"),
            "currency": obj.get("currency"),
        }

    @staticmethod
    def _is_stale(age: int | None, market_state: str, cache_age_s: int) -> bool:
        if age is None:
            return True  # unmeasured is not fresh
        if cache_age_s > STALE_AFTER_S:
            return True  # what the market "was" when we cached it no longer counts
        if market_state == "closed":
            return age > CLOSED_STALE_AFTER_S  # a last-session price is quiet, not stale
        return age > STALE_AFTER_S  # open, or unknown and held to the open standard

    def quotes(self, symbols: Iterable[str], max_age_s: float | None = None, use_cache: bool = True) -> dict:
        ttl = QUOTE_TTL_S if max_age_s is None else float(max_age_s)
        g = self._gather("quote", "/quote", list(symbols), ttl, use_cache, {}, self._normalize_quote)
        out = self._envelope("quotes", g)
        now_ts = self.now().timestamp()
        for sym in g["wanted"]:
            if sym in g["found"]:
                hit = g["found"][sym]
                q = dict(hit["data"])
                age = max(0, int(now_ts - q["quote_time"])) if q.get("quote_time") else None
                state = {True: "open", False: "closed"}.get(q.get("is_market_open"), "unknown")  # type: ignore[arg-type]
                q.update({
                    "ok": True,
                    "market_state": state,
                    "quote_age_s": age,
                    "stale": self._is_stale(age, state, hit["cache_age_s"]),
                    "from_cache": hit["from_cache"],
                    "cache_age_s": hit["cache_age_s"],
                    "fetched_at": self._fetched_at(hit["cache_age_s"]),
                })
                out["symbols"][sym] = q
            elif sym in g["errors"]:
                out["symbols"][sym] = dict(g["errors"][sym], ok=False, symbol=sym)
            else:
                out["symbols"][sym] = {"ok": False, "symbol": sym, "reason": "deferred"}
        return out

    # -- daily history, in the wire's fetch_daily_history shape
    def _normalize_history(self, sym: str, obj: dict) -> dict | None:
        values = obj.get("values")
        if not isinstance(values, list):
            return None
        candles = []
        for v in reversed(values):  # Twelve Data sends newest first
            if not isinstance(v, dict) or _f(v.get("close")) is None:
                continue
            candles.append({
                "datetime": str(v.get("datetime") or "")[:10],
                "open": _f(v.get("open")), "high": _f(v.get("high")),
                "low": _f(v.get("low")), "close": _f(v.get("close")),
                "volume": _f(v.get("volume")),
            })
        if not candles:
            return None  # never cache an empty answer as if it were history
        partial = None
        now = self.now()
        last_day = candles[-1]["datetime"]
        if is_pair(sym):
            unfinished = last_day == now.astimezone(UTC).date().isoformat()
        else:
            now_et = now.astimezone(ET)
            unfinished = last_day == now_et.date().isoformat() and now_et.time() < EQUITY_CLOSE
        if unfinished:
            # The planner's features must be re-derivable hours later from the
            # same candles, so a bar that is still moving is set aside. The
            # cache is dropped at the next session boundary, so the finished
            # version of this bar is fetched rather than forgotten.
            partial = candles.pop()
            if not candles:
                return None  # nothing but today's moving bar: not history, not cacheable
        meta = obj.get("meta")
        return {
            "symbol": sym,
            "provider_symbol": provider_symbol(sym),
            "candles": candles,
            "partial_bar": partial,
            "venue": meta.get("exchange") if isinstance(meta, dict) else None,
        }

    def history(
        self, symbols: Iterable[str], days: int = HISTORY_DAYS,
        max_age_s: float | None = None, use_cache: bool = True,
    ) -> dict:
        days = max(1, min(int(days), MAX_HISTORY_DAYS))
        ttl = HISTORY_TTL_S if max_age_s is None else float(max_age_s)
        params = {"interval": "1day", "outputsize": days + 1}
        g = self._gather(
            "history", "/time_series", list(symbols), ttl, use_cache, params,
            self._normalize_history, extra="_%dd" % days, boundary=True,
        )
        out = self._envelope("history", g)
        as_of = out["as_of"]
        for sym in g["wanted"]:
            if sym in g["found"]:
                hit = g["found"][sym]
                h = dict(hit["data"])
                candles = h["candles"][-days:]
                h.update({
                    "candles": candles,
                    "history_ok": bool(candles),
                    "as_of": as_of,
                    "bars": len(candles),
                    "note": "" if candles else "only an unfinished bar came back",
                    "last_bar_at": candles[-1]["datetime"] if candles else None,
                    "source": PROVIDER,
                    "from_cache": hit["from_cache"],
                    "cache_age_s": hit["cache_age_s"],
                    "fetched_at": self._fetched_at(hit["cache_age_s"]),
                })
                out["symbols"][sym] = h
            else:
                err = g["errors"].get(sym) or {"reason": "deferred"}
                out["symbols"][sym] = {
                    "symbol": sym, "candles": [], "history_ok": False, "as_of": as_of, "bars": 0,
                    "note": "%s: %s" % (err.get("reason"), err.get("detail", "")),
                    "last_bar_at": None, "source": PROVIDER, "reason": err.get("reason"),
                }
        return out

    # -- the look: what an agent asks for when Schwab is dark
    def look(
        self, symbols: Iterable[str] | None = None, with_crypto: bool = False,
        rules_path: Path | None = None, snapshot_dir: Path | None = None,
        max_age_s: float | None = None, use_cache: bool = True,
    ) -> dict:
        """Prices, the planner's features, distance to the known stops, and the
        last Schwab snapshot labelled for what it is. Prices are bought first:
        when the minute is short, a price without a trend is still a look, and
        a trend without a price is not."""
        syms = [desk_symbol(s) for s in (symbols or DESK_SYMBOLS)]
        if with_crypto:
            syms += [c for c in CRYPTO_ANCHORS if c not in syms]
        q = self.quotes(syms, max_age_s=max_age_s, use_cache=use_cache)
        h = self.history(syms, use_cache=use_cache)
        rules, levels_note = _load_rules(rules_path)

        out_syms: dict = {}
        alerts: list = []
        for sym in q["symbols"]:
            quote = q["symbols"][sym]
            hist = h["symbols"].get(sym) or {}
            last = quote.get("last") if quote.get("ok") else None
            feats = features(hist.get("candles") or [], last)
            levels = _levels(rules, sym, last)
            out_syms[sym] = {
                "quote": quote,
                "features": feats,
                "levels": levels,
                "history": {k: hist.get(k) for k in (
                    "history_ok", "bars", "last_bar_at", "partial_bar", "venue", "from_cache", "fetched_at", "note")},
            }
            for code, hit in (
                ("quote_unavailable", not quote.get("ok")),
                ("quote_stale", bool(quote.get("ok") and quote.get("stale"))),
                ("market_closed_last_session_price", bool(quote.get("ok") and quote.get("market_state") == "closed")),
                ("history_unavailable", not hist.get("history_ok")),
                ("atr_filter", feats["atr_filter"] is True),
                ("at_or_below_protect_stop", levels["at_or_below_protect_stop"] is True),
                ("above_entry_cap", levels["above_entry_cap"] is True),
            ):
                if hit:
                    alerts.append({"symbol": sym, "code": code})

        deferred = [dict(d, what="quote") for d in q["deferred"]] + [dict(d, what="history") for d in h["deferred"]]
        credits = dict(h["credits"])
        credits["spent_this_call"] = q["credits"]["spent_this_call"] + h["credits"]["spent_this_call"]
        snapshot, snapshot_note = _load_snapshot(snapshot_dir, self.now(), q["symbols"])
        return {
            "op": "look",
            "source": PROVIDER,
            "evidence_only": True,
            "not_for_execution": True,
            "as_of": q["as_of"],
            "symbols": out_syms,
            "alerts": alerts,
            "levels_note": levels_note,
            "book_snapshot": snapshot,
            "book_snapshot_note": snapshot_note,
            "deferred": deferred,
            "complete": q["complete"] and h["complete"],
            "credits": credits,
        }


# ------------------------------------------------- local context for the look
def _load_rules(path: Path | None) -> tuple[dict, str]:
    """The human-written standing rules, if this machine has them. Never the
    example file: illustrative numbers must not pose as the desk's stops."""
    if path is None:
        return {}, "no standing rules path given; stops unknown"
    try:
        data = json.loads(Path(path).read_text())
        return (data if isinstance(data, dict) else {}), ""
    except OSError:
        return {}, "standing rules not found at %s; stops unknown on this machine" % path
    except ValueError:
        return {}, "standing rules at %s are not valid JSON; stops unknown" % path


def _section(rules: dict, name: str, sym: str) -> dict:
    block = rules.get(name)
    entry = block.get(sym) if isinstance(block, dict) else None
    return entry if isinstance(entry, dict) else {}


def _levels(rules: dict, sym: str, last: float | None) -> dict:
    protect, entry = _section(rules, "protect", sym), _section(rules, "entries", sym)
    stop, cap = _f(protect.get("stop")), _f(entry.get("cap"))
    return {
        "protect_stop": stop,
        "dist_to_protect_stop_pct": ((last - stop) / last) if (last not in (None, 0) and stop is not None) else None,
        "at_or_below_protect_stop": (last <= stop) if (last is not None and stop is not None) else None,
        "entry_enabled": entry.get("enabled") if isinstance(entry.get("enabled"), bool) else None,
        "entry_limit": _f(entry.get("limit")),
        "entry_stop": _f(entry.get("stop")),
        "entry_cap": cap,
        # RISK_CONSTITUTION law 4: through the cap, the idea is dead.
        "above_entry_cap": (last > cap) if (last is not None and cap is not None) else None,
    }


def _load_snapshot(directory: Path | None, now: dt.datetime, quotes: dict) -> tuple[dict | None, str]:
    """The newest readable committed Schwab snapshot, marked to the eyes' prices.
    It is ALWAYS stale: the eyes cannot see the account, only remember it."""
    if directory is None or not Path(directory).is_dir():
        return None, "no Schwab snapshot directory on this machine; the book is unknown"
    for path in sorted(Path(directory).glob("schwab_*.json"), reverse=True):
        try:
            snap = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        book = snap.get("book") if isinstance(snap, dict) else None
        if not isinstance(book, dict):
            continue
        age = None
        try:
            taken = dt.datetime.fromisoformat(str(snap.get("ts_utc")).replace("Z", "+00:00"))
            age = round((now - taken).total_seconds() / 3600.0, 2)
        except (TypeError, ValueError):
            pass
        positions = []
        raw_positions = book.get("positions")
        for p in raw_positions if isinstance(raw_positions, list) else []:
            if not isinstance(p, dict):
                continue
            sym = desk_symbol(p.get("symbol") or "")
            qty, avg = _f(p.get("qty")), _f(p.get("avg"))
            quote = quotes.get(sym) or {}
            last = quote.get("last") if quote.get("ok") else None
            positions.append({
                "symbol": sym, "qty": qty, "avg": avg, "est_last": last,
                "est_mv": (qty * last) if (qty is not None and last is not None) else None,
                "est_unrealized_pct": ((last - avg) / avg) if (last is not None and avg not in (None, 0)) else None,
            })
        return {
            "file": path.name, "ts_utc": snap.get("ts_utc"), "age_hours": age, "stale": True,
            "mv_session_then": snap.get("mv"), "equity": _f(book.get("equity")), "cash": _f(book.get("cash")),
            "positions": positions,
            "note": "remembered, not seen: orders may have filled since. Size only from live Schwab equity.",
        }, ""
    return None, "no readable Schwab snapshot in %s" % directory


# ------------------------------------------------------------------------ CLI
def _fmt(v: Any, spec: str = "%.2f") -> str:
    return (spec % v) if isinstance(v, (int, float)) and not isinstance(v, bool) else "-"


def _age_text(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return "-"
    if seconds < 120:
        return "%ds" % seconds
    if seconds < 7200:
        return "%dm" % (seconds // 60)
    return "%dh" % (seconds // 3600)


def render_text(out: dict) -> str:
    """A brief a person can read on a phone. Same facts as the JSON, fewer of them."""
    lines = ["TEMPLE FLOW EYES | Twelve Data | EVIDENCE ONLY, not for execution | asked %s" % out.get("as_of")]
    lines.append("%-8s %10s %7s %6s %7s %9s %9s %5s %5s %8s %7s" % (
        "SYMBOL", "LAST", "CHG%", "AGE", "MARKET", "SMA20", "SMA50", "20>50", "ATRx", "STOP", "DIST%"))
    for sym, s in (out.get("symbols") or {}).items():
        q, f, lv = s.get("quote") or {}, s.get("features") or {}, s.get("levels") or {}
        if not q.get("ok"):
            lines.append("%-8s %10s  (%s)" % (sym, "-", q.get("reason")))
            continue
        above = f.get("sma20_above_sma50")
        trend = "-" if above is None else ("yes" if above else "no")
        dist = lv.get("dist_to_protect_stop_pct")
        lines.append("%-8s %10s %7s %6s %7s %9s %9s %5s %5s %8s %7s" % (
            sym, _fmt(q.get("last")), _fmt(q.get("change_pct")), _age_text(q.get("quote_age_s")),
            q.get("market_state") or "-", _fmt(f.get("sma20")), _fmt(f.get("sma50")), trend,
            _fmt(f.get("atr_ratio")), _fmt(lv.get("protect_stop")),
            _fmt(dist * 100 if dist is not None else None, "%.1f")))
    alerts = out.get("alerts") or []
    lines.append("alerts: " + (", ".join("%s %s" % (a["symbol"], a["code"]) for a in alerts) or "none"))
    if out.get("levels_note"):
        lines.append("levels: " + out["levels_note"])
    snap = out.get("book_snapshot")
    if snap:
        held = ", ".join("%s x%s" % (p["symbol"], _fmt(p["qty"], "%g")) for p in snap["positions"]) or "flat"
        lines.append("book (STALE, %sh old, %s): equity %s cash %s | %s" % (
            _fmt(snap.get("age_hours"), "%.1f"), snap.get("file"), _fmt(snap.get("equity")), _fmt(snap.get("cash")), held))
    else:
        lines.append("book: " + str(out.get("book_snapshot_note")))
    for d in out.get("deferred") or []:
        lines.append("deferred: %s %s (%s, retry in %ss)" % (d.get("what", ""), d["symbol"], d["reason"], d["retry_after_s"]))
    c = out.get("credits") or {}
    lines.append("credits: spent %s | minute %s/%s | day %s/%s" % (
        c.get("spent_this_call"), c.get("minute_used"), c.get("minute_limit"), c.get("day_used"), c.get("day_budget")))
    return "\n".join(lines)


def default_eyes() -> Eyes:
    files = []
    if os.environ.get("TEMPLE_FLOW_ENV_FILE"):
        files.append(Path(os.environ["TEMPLE_FLOW_ENV_FILE"]))
    files.append(REPO_ROOT / ".env")
    files.append(Path(os.environ.get("SPIRAL_BROKER_ROOT") or (Path.home() / "spiral-broker")) / ".env")
    cache = safe_cache_dir(Path(os.environ.get("TEMPLE_FLOW_EYES_CACHE") or (REPO_ROOT / "data" / "cache" / "eyes")))
    return Eyes(key=load_key(os.environ, files), cache_dir=cache,
                day_budget=parse_day_budget(os.environ.get("TWELVE_DATA_DAY_BUDGET")))


def _exit_code(out: dict) -> int:
    blobs = list((out.get("symbols") or {}).values())
    reasons = {b.get("reason") or (b.get("quote") or {}).get("reason") for b in blobs if isinstance(b, dict)}
    if "no_api_key" in reasons:
        return 2
    return 0 if out.get("complete", True) else 3


class _UsageError(Exception):
    """A command line argparse would have answered with prose and exit 2."""


class _Parser(argparse.ArgumentParser):
    # argparse's default is to print usage to stderr and exit 2. Exit 2 already
    # means "no API key", and a bot reading stdout would get nothing at all.
    # Subparsers inherit this class, so every usage error takes this path.
    def error(self, message: str):  # type: ignore[override]
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    ap = _Parser(
        prog="temple_flow_eyes",
        description="On-demand, read-only Twelve Data eyes for the Temple Flow desk. "
                    "Spends credits only when called. Evidence only: never an execution data source.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--max-age", type=float, default=None, help="accept cached quotes up to this many seconds old")
        p.add_argument("--no-cache", action="store_true", help="always fetch (costs credits)")
        p.add_argument("--wait", action="store_true", help="if the minute budget defers something, sleep and finish")

    p_look = sub.add_parser("look", help="prices + planner features + distance to stops + the stale book")
    p_look.add_argument("--symbols", nargs="+", default=None)
    p_look.add_argument("--with-crypto", action="store_true", help="add BTC-USD and ETH-USD")
    p_look.add_argument("--rules", type=Path, default=REPO_ROOT / "config" / "standing_rules.json")
    p_look.add_argument("--snapshots", type=Path, default=REPO_ROOT / "logs" / "snapshots")
    p_look.add_argument("--text", action="store_true", help="a short human brief instead of JSON")
    common(p_look)
    p_quote = sub.add_parser("quote", help="last price for one or more symbols (1 credit each)")
    p_quote.add_argument("symbols", nargs="+")
    common(p_quote)
    p_hist = sub.add_parser("history", help="daily candles in the wire's fetch_daily_history shape (1 credit each)")
    p_hist.add_argument("symbols", nargs="+")
    p_hist.add_argument("--days", type=int, default=HISTORY_DAYS)
    common(p_hist)
    sub.add_parser("budget", help="credits spent and remaining (free)")
    sub.add_parser("status", help="configuration and whether a key is present (free)")
    return ap


def _run(args: argparse.Namespace, e: Eyes, sleep: Callable[[float], None]) -> tuple[str, int]:
    if args.cmd == "budget":
        st = e._ledger_status()  # the same guarded read a quote uses: one condition, one answer
        return json.dumps(st, indent=1), (3 if st.get("ledger_unavailable") else 0)
    if args.cmd == "status":
        return json.dumps({
            "provider": PROVIDER, "key_present": bool(e.key), "key_env": KEY_ENV,
            "cache_dir": str(e.cache_dir), "minute_limit": e.ledger.minute_limit,
            "day_budget": e.ledger.day_budget, "quote_ttl_s": QUOTE_TTL_S, "history_ttl_s": HISTORY_TTL_S,
            "desk_symbols": list(DESK_SYMBOLS), "crypto_anchors": list(CRYPTO_ANCHORS),
            "evidence_only": True,
        }, indent=1), 0

    def once() -> dict:
        use_cache = not args.no_cache
        if args.cmd == "quote":
            return e.quotes(args.symbols, max_age_s=args.max_age, use_cache=use_cache)
        if args.cmd == "history":
            return e.history(args.symbols, days=args.days, max_age_s=args.max_age, use_cache=use_cache)
        return e.look(symbols=args.symbols, with_crypto=args.with_crypto, rules_path=args.rules,
                      snapshot_dir=args.snapshots, max_age_s=args.max_age, use_cache=use_cache)

    out = once()
    rounds = 0
    while args.wait and rounds < 3 and out.get("deferred") and all(
        d.get("reason") == "minute_budget" for d in out["deferred"]
    ):
        sleep(min(61, max(d.get("retry_after_s") or 1 for d in out["deferred"]) + 1))
        args.no_cache = False  # the second pass must reuse what the first one bought
        out = once()
        rounds += 1
    text = render_text(out) if getattr(args, "text", False) else json.dumps(out, indent=1)
    return text, _exit_code(out)


def main(argv: list | None = None, eyes: Eyes | None = None, sleep: Callable[[float], None] = time.sleep) -> int:
    """Exit 0 complete, 2 no key, 3 partial, 4 internal error, 5 bad command line.
    Always prints one JSON document (or the text brief, or --help): an agent
    never has to parse a traceback or a usage message."""
    def failure(op: Any, reason: str, ex: Exception, key: str | None) -> str:
        return json.dumps({
            "op": op, "ok": False, "source": PROVIDER, "evidence_only": True,
            "not_for_execution": True, "reason": reason,
            "error_type": type(ex).__name__, "detail": redact(str(ex), key),
        }, indent=1)

    try:
        args = _build_parser().parse_args(argv)
    except _UsageError as ex:
        print(failure(None, "usage_error", ex, None))
        return 5
    key = None
    try:
        e = eyes or default_eyes()
        key = e.key
        text, code = _run(args, e, sleep)
    except Exception as ex:  # noqa: BLE001 - the contract is "always JSON"
        text, code = failure(args.cmd, "internal_error", ex, key), 4
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
