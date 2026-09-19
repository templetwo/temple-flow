#!/usr/bin/env python3
"""Tests for temple_flow_eyes — the on-demand, read-only Twelve Data eyes.

Run:  python3 scripts/test_temple_flow_eyes.py

Nothing here touches the network. Every Eyes is built with an injected
transport, an injected clock and a temp cache dir, and setUp arms a tripwire on
urllib so a test that reaches for the real internet fails loudly instead of
quietly spending a credit.
"""
from __future__ import annotations

import ast
import datetime as dt
import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

# Same offline pin the wire's suite uses: force-set, not setdefault, and BEFORE
# the wire is imported for the parity tests, so no broker root is ever live here.
os.environ["SPIRAL_BROKER_ROOT"] = "/nonexistent"

sys.path.insert(0, str(Path(__file__).resolve().parent))

import temple_flow_eyes as eyes_mod  # noqa: E402

KEY = "k3y" + "A1b2C3d4" * 4  # 35 chars, shaped like a real key, never a real one
UTC = dt.timezone.utc


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, start: dt.datetime):
        self.t = start

    def __call__(self) -> dt.datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + dt.timedelta(seconds=seconds)


class OfflineCase(unittest.TestCase):
    """Temp dirs + the no-internet tripwire, shared by every test class."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._real_urlopen = urllib.request.urlopen

        def tripwire(*_a, **_k):
            raise AssertionError("test reached the real network")

        urllib.request.urlopen = tripwire
        # Tuesday 2026-09-15 14:00:00 UTC = 10:00 ET, inside regular hours.
        self.clock = Clock(dt.datetime(2026, 9, 15, 14, 0, 0, tzinfo=UTC))

    def tearDown(self) -> None:
        urllib.request.urlopen = self._real_urlopen
        self._tmp.cleanup()


# --------------------------------------------------------------------------
# Round A: key handling, redaction, symbols, the credit ledger
# --------------------------------------------------------------------------
class TestKeyLoading(OfflineCase):
    def test_environment_variable_wins(self):
        envfile = self.tmp / ".env"
        envfile.write_text("TWELVE_DATA_API_KEY=from_file_value_123456\n")
        got = eyes_mod.load_key({"TWELVE_DATA_API_KEY": KEY}, [envfile])
        self.assertEqual(got, KEY)

    def test_falls_back_to_an_env_file_and_strips_quotes(self):
        envfile = self.tmp / ".env"
        envfile.write_text('# comment\nOTHER=1\nTWELVE_DATA_API_KEY="%s"\n' % KEY)
        self.assertEqual(eyes_mod.load_key({}, [envfile]), KEY)

    def test_missing_everywhere_is_none_not_an_exception(self):
        self.assertIsNone(eyes_mod.load_key({}, [self.tmp / "absent.env"]))

    def test_blank_value_counts_as_missing(self):
        self.assertIsNone(eyes_mod.load_key({"TWELVE_DATA_API_KEY": "  "}, []))

    def test_loading_a_key_never_exports_it_into_the_process_environment(self):
        envfile = self.tmp / ".env"
        envfile.write_text("TWELVE_DATA_API_KEY=%s\n" % KEY)
        before = os.environ.get("TWELVE_DATA_API_KEY")
        eyes_mod.load_key({}, [envfile])
        self.assertEqual(os.environ.get("TWELVE_DATA_API_KEY"), before)


class TestRedaction(unittest.TestCase):
    def test_the_key_is_removed_from_any_text(self):
        msg = "The '%s' API key is only used for initial familiarity." % KEY
        out = eyes_mod.redact(msg, KEY)
        self.assertNotIn(KEY, out)
        self.assertIn("[redacted]", out)

    def test_redact_with_no_key_returns_text_unchanged(self):
        self.assertEqual(eyes_mod.redact("hello", None), "hello")


class TestSymbols(unittest.TestCase):
    def test_desk_crypto_label_maps_to_provider_pair(self):
        self.assertEqual(eyes_mod.provider_symbol("BTC-USD"), "BTC/USD")
        self.assertEqual(eyes_mod.provider_symbol("eth-usd"), "ETH/USD")

    def test_equity_symbols_pass_through_uppercased(self):
        self.assertEqual(eyes_mod.provider_symbol("etha"), "ETHA")

    def test_provider_pair_maps_back_to_the_desk_label(self):
        self.assertEqual(eyes_mod.desk_symbol("BTC/USD"), "BTC-USD")
        self.assertEqual(eyes_mod.desk_symbol("IBIT"), "IBIT")

    def test_pairs_are_recognised_as_always_open_markets(self):
        self.assertTrue(eyes_mod.is_pair("BTC-USD"))
        self.assertFalse(eyes_mod.is_pair("IBIT"))


class TestLedger(OfflineCase):
    def ledger(self, day_budget=400):
        return eyes_mod.Ledger(self.tmp / "ledger.json", now=self.clock, day_budget=day_budget)

    def test_a_fresh_ledger_has_the_whole_minute_available(self):
        self.assertEqual(self.ledger().allowance(), 8)

    def test_spending_reduces_the_minute_allowance(self):
        led = self.ledger()
        led.record(5, "quote:ETHA,IBIT,NVO,NOK,BTC/USD")
        self.assertEqual(led.allowance(), 3)

    def test_the_minute_window_rolls_forward(self):
        led = self.ledger()
        led.record(8, "quote")
        self.assertEqual(led.allowance(), 0)
        self.clock.advance(61)
        self.assertEqual(led.allowance(), 8)

    def test_retry_after_says_when_credits_come_back(self):
        led = self.ledger()
        led.record(8, "quote")
        self.clock.advance(20)
        self.assertEqual(led.retry_after(1), 40)

    def test_the_day_budget_caps_the_allowance(self):
        led = self.ledger(day_budget=10)
        led.record(8, "a")
        self.clock.advance(120)
        self.assertEqual(led.allowance(), 2)

    def test_the_day_resets_at_midnight_utc(self):
        led = self.ledger(day_budget=8)
        led.record(8, "a")
        self.clock.advance(120)
        self.assertEqual(led.allowance(), 0)
        self.clock.t = dt.datetime(2026, 9, 16, 0, 0, 5, tzinfo=UTC)
        self.assertEqual(led.allowance(), 8)

    def test_spending_survives_a_new_ledger_object(self):
        self.ledger().record(6, "a")
        self.assertEqual(self.ledger().allowance(), 2)

    def test_a_corrupt_ledger_file_is_treated_as_fully_spent_for_the_minute(self):
        # Fail closed: if we cannot read what was spent, assume the worst for
        # this minute rather than handing out eight fresh credits.
        (self.tmp / "ledger.json").write_text("{not json")
        self.assertEqual(self.ledger().allowance(), 0)

    def test_status_reports_the_numbers_an_agent_needs(self):
        led = self.ledger(day_budget=400)
        led.record(3, "quote")
        s = led.status()
        self.assertEqual(s["minute_used"], 3)
        self.assertEqual(s["minute_limit"], 8)
        self.assertEqual(s["day_used"], 3)
        self.assertEqual(s["day_budget"], 400)
        self.assertEqual(s["day_remaining"], 397)


    def test_a_corrupt_ledger_heals_once_the_minute_has_passed(self):
        # Fail closed must not mean stuck forever: nothing rewrites the file
        # while the allowance is zero, so the read itself has to quarantine it.
        (self.tmp / "ledger.json").write_text("{not json")
        led = self.ledger()
        self.assertEqual(led.allowance(), 0)
        self.clock.advance(61)
        self.assertEqual(self.ledger().allowance(), 8)
        self.assertTrue(list(self.tmp.glob("ledger.json.corrupt*")))


# --------------------------------------------------------------------------
# Round B: transport, quotes, cache, history, features
# --------------------------------------------------------------------------
class FakeTransport:
    """Stands in for the HTTP layer. Records every call it receives."""

    def __init__(self):
        self.calls: list = []
        self.routes: dict = {}

    def __call__(self, path, params, key, timeout):
        self.calls.append({"path": path, "params": dict(params), "key": key, "timeout": timeout})
        handler = self.routes[path]
        resp = handler(dict(params)) if callable(handler) else handler
        if isinstance(resp, BaseException):
            raise resp
        return resp

    def symbols_asked(self, path):
        out = []
        for c in self.calls:
            if c["path"] == path:
                out.extend(c["params"]["symbol"].split(","))
        return out


def ok(body, headers=None):
    return {"status": 200, "headers": headers or {}, "body": body}


def quote_obj(sym, close, last_quote_at, is_open=True, exchange="NASDAQ", prev="100.00"):
    return {
        "symbol": sym, "name": sym + " Inc", "exchange": exchange, "currency": "USD",
        "datetime": "2026-09-15", "timestamp": 1789470000, "last_quote_at": last_quote_at,
        "open": "99.50", "high": "101.25", "low": "98.75", "close": close,
        "volume": "12345", "previous_close": prev, "change": "1.00",
        "percent_change": "1.0", "is_market_open": is_open,
    }


def quote_route(table):
    """A /quote handler: flat body for one symbol, keyed body for several."""

    def handler(params):
        syms = params["symbol"].split(",")
        if len(syms) == 1:
            return ok(table[syms[0]])
        return ok({s: table[s] for s in syms})

    return handler


def series_values(n, end=dt.date(2026, 9, 14), start=100.0, step=0.5, spread=1.0, volume=True):
    """n daily bars, NEWEST FIRST and all strings, exactly as Twelve Data sends them."""
    out = []
    day = end
    for i in range(n):
        close = start + step * (n - 1 - i)
        bar = {
            "datetime": day.isoformat(), "open": "%.4f" % (close - 0.1),
            "high": "%.4f" % (close + spread), "low": "%.4f" % (close - spread),
            "close": "%.4f" % close,
        }
        if volume:
            bar["volume"] = str(1000 + i)
        out.append(bar)
        day = day - dt.timedelta(days=1)
    return out


def series_obj(sym, values, exchange="NASDAQ"):
    return {"meta": {"symbol": sym, "interval": "1day", "exchange": exchange}, "values": values, "status": "ok"}


def series_route(table):
    def handler(params):
        syms = params["symbol"].split(",")
        if len(syms) == 1:
            return ok(table[syms[0]])
        return ok({s: table[s] for s in syms})

    return handler


class EyesCase(OfflineCase):
    def make(self, key=KEY, day_budget=400, transport=None):
        self.tx = transport or FakeTransport()
        return eyes_mod.Eyes(
            key=key, cache_dir=self.tmp / "cache", now=self.clock,
            transport=self.tx, day_budget=day_budget,
        )

    def now_ts(self):
        return int(self.clock().timestamp())


class TestDefaultTransport(OfflineCase):
    def test_the_key_travels_in_a_header_and_never_in_the_url(self):
        seen = {}

        class Resp:
            status = 200
            headers = {"api-credits-used": "3", "api-credits-left": "5", "X-Other": "1"}

            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["timeout"] = timeout
            return Resp()

        urllib.request.urlopen = fake_urlopen
        out = eyes_mod.http_get("/quote", {"symbol": "BTC/USD,ETHA"}, KEY, 7.0)
        self.assertEqual(seen["auth"], "apikey " + KEY)
        self.assertNotIn(KEY, seen["url"])
        self.assertNotIn("apikey", seen["url"].lower())
        self.assertTrue(seen["url"].startswith("https://api.twelvedata.com/quote?"))
        self.assertEqual(seen["timeout"], 7.0)
        self.assertEqual(out["status"], 200)
        self.assertEqual(out["body"], {"ok": True})
        self.assertEqual(out["headers"].get("api-credits-used"), "3")

    def test_an_http_error_comes_back_as_a_status_with_its_json_body(self):
        import urllib.error

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"code":401,"message":"bad key","status":"error"}')
            )

        urllib.request.urlopen = fake_urlopen
        out = eyes_mod.http_get("/quote", {"symbol": "ETHA"}, KEY, 5.0)
        self.assertEqual(out["status"], 401)
        self.assertEqual(out["body"]["message"], "bad key")


class TestQuotes(EyesCase):
    def table(self, **over):
        t = {
            "ETHA": quote_obj("ETHA", "18.6500", self.now_ts() - 30),
            "IBIT": quote_obj("IBIT", "43.5300", self.now_ts() - 45),
            "BTC/USD": quote_obj("BTC/USD", "81246.77", self.now_ts() - 5, exchange="Binance"),
        }
        t.update(over)
        return t

    def test_several_symbols_cost_one_http_call_and_one_credit_each(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        out = e.quotes(["ETHA", "IBIT", "BTC-USD"])
        self.assertEqual(len(self.tx.calls), 1)
        self.assertEqual(self.tx.calls[0]["params"]["symbol"], "ETHA,IBIT,BTC/USD")
        self.assertEqual(out["credits"]["spent_this_call"], 3)
        self.assertEqual(e.ledger.allowance(), 5)

    def test_prices_arrive_as_numbers_under_the_desk_label(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        q = e.quotes(["BTC-USD"])["symbols"]["BTC-USD"]
        self.assertTrue(q["ok"])
        self.assertEqual(q["last"], 81246.77)
        self.assertEqual(q["previous_close"], 100.0)
        self.assertEqual(q["provider_symbol"], "BTC/USD")
        self.assertEqual(q["venue"], "Binance")
        self.assertEqual(q["quote_age_s"], 5)
        self.assertFalse(q["from_cache"])

    def test_every_answer_is_stamped_as_evidence_not_execution_data(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        out = e.quotes(["ETHA"])
        self.assertEqual(out["source"], "twelve_data")
        self.assertIs(out["evidence_only"], True)
        self.assertIs(out["not_for_execution"], True)
        self.assertTrue(out["complete"])

    def test_a_second_look_inside_the_ttl_is_free(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        e.quotes(["ETHA", "IBIT"])
        self.clock.advance(60)
        out = e.quotes(["ETHA", "IBIT"])
        self.assertEqual(len(self.tx.calls), 1)
        self.assertEqual(out["credits"]["spent_this_call"], 0)
        self.assertTrue(out["symbols"]["ETHA"]["from_cache"])
        self.assertEqual(out["symbols"]["ETHA"]["cache_age_s"], 60)
        self.assertEqual(out["symbols"]["ETHA"]["quote_age_s"], 90)

    def test_an_expired_cache_entry_is_refetched(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        e.quotes(["ETHA"])
        self.clock.advance(eyes_mod.QUOTE_TTL_S + 1)
        e.quotes(["ETHA"])
        self.assertEqual(len(self.tx.calls), 2)

    def test_only_the_stale_symbols_are_fetched(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        e.quotes(["ETHA"])
        e.quotes(["ETHA", "IBIT"])
        self.assertEqual(self.tx.calls[1]["params"]["symbol"], "IBIT")

    def test_no_cache_forces_a_fetch(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        e.quotes(["ETHA"])
        e.quotes(["ETHA"], use_cache=False)
        self.assertEqual(len(self.tx.calls), 2)

    def test_what_does_not_fit_the_minute_is_deferred_not_silently_dropped(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        e.ledger.record(6, "earlier")
        out = e.quotes(["ETHA", "IBIT", "BTC-USD"])
        self.assertEqual(self.tx.calls[0]["params"]["symbol"], "ETHA,IBIT")
        self.assertFalse(out["complete"])
        self.assertEqual([d["symbol"] for d in out["deferred"]], ["BTC-USD"])
        self.assertEqual(out["deferred"][0]["reason"], "minute_budget")
        self.assertGreater(out["deferred"][0]["retry_after_s"], 0)

    def test_an_exhausted_day_budget_makes_no_http_call_at_all(self):
        e = self.make(day_budget=2)
        self.tx.routes["/quote"] = quote_route(self.table())
        e.ledger.record(2, "earlier")
        self.clock.advance(120)
        out = e.quotes(["ETHA"])
        self.assertEqual(self.tx.calls, [])
        self.assertEqual(out["deferred"][0]["reason"], "day_budget")

    def test_one_bad_symbol_does_not_spoil_the_batch(self):
        e = self.make()
        bad = {"code": 404, "message": "symbol not found for key %s" % KEY, "status": "error"}
        self.tx.routes["/quote"] = quote_route(self.table(NOPE=bad))
        out = e.quotes(["ETHA", "NOPE"])
        self.assertTrue(out["symbols"]["ETHA"]["ok"])
        self.assertFalse(out["symbols"]["NOPE"]["ok"])
        self.assertEqual(out["symbols"]["NOPE"]["reason"], "provider_error")
        self.assertNotIn(KEY, json.dumps(out))

    def test_a_429_is_reported_and_closes_the_minute_locally(self):
        e = self.make()
        self.tx.routes["/quote"] = {"status": 429, "headers": {}, "body": {"code": 429, "message": "slow down", "status": "error"}}
        out = e.quotes(["ETHA"])
        self.assertEqual(out["symbols"]["ETHA"]["reason"], "rate_limited")
        self.assertEqual(e.ledger.allowance(), 0)

    def test_a_rejected_key_is_reported_without_echoing_the_key(self):
        e = self.make()
        body = {"code": 401, "message": "The '%s' API key is wrong" % KEY, "status": "error"}
        self.tx.routes["/quote"] = {"status": 401, "headers": {}, "body": body}
        out = e.quotes(["ETHA", "IBIT"])
        self.assertEqual(out["symbols"]["ETHA"]["reason"], "provider_error")
        self.assertEqual(out["symbols"]["IBIT"]["reason"], "provider_error")
        self.assertNotIn(KEY, json.dumps(out))

    def test_no_key_and_nothing_cached_is_a_plain_refusal_with_no_http(self):
        e = self.make(key=None)
        out = e.quotes(["ETHA"])
        self.assertEqual(self.tx.calls, [])
        self.assertEqual(out["symbols"]["ETHA"]["reason"], "no_api_key")
        self.assertFalse(out["complete"])

    def test_a_fresh_cache_still_answers_when_the_key_is_gone(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        e.quotes(["ETHA"])
        keyless = eyes_mod.Eyes(key=None, cache_dir=self.tmp / "cache", now=self.clock, transport=self.tx)
        out = keyless.quotes(["ETHA"])
        self.assertTrue(out["symbols"]["ETHA"]["ok"])
        self.assertTrue(out["symbols"]["ETHA"]["from_cache"])

    def test_an_unparseable_price_is_a_bad_payload_not_a_crash(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table(ETHA=quote_obj("ETHA", "n/a", self.now_ts())))
        out = e.quotes(["ETHA"])
        self.assertFalse(out["symbols"]["ETHA"]["ok"])
        self.assertEqual(out["symbols"]["ETHA"]["reason"], "bad_payload")

    def test_a_dead_network_is_reported_and_still_charged(self):
        e = self.make()
        self.tx.routes["/quote"] = OSError("no route to host")
        out = e.quotes(["ETHA"])
        self.assertEqual(out["symbols"]["ETHA"]["reason"], "network_error")
        self.assertEqual(out["credits"]["spent_this_call"], 1)

    def test_an_old_quote_in_an_open_market_is_flagged_stale(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table(ETHA=quote_obj("ETHA", "18.65", self.now_ts() - 3600)))
        self.assertTrue(e.quotes(["ETHA"])["symbols"]["ETHA"]["stale"])

    def test_a_quote_with_no_timestamp_is_unmeasured_so_it_is_stale(self):
        e = self.make()
        obj = quote_obj("ETHA", "18.65", None)
        self.tx.routes["/quote"] = quote_route(self.table(ETHA=obj))
        q = e.quotes(["ETHA"])["symbols"]["ETHA"]
        self.assertIsNone(q["quote_age_s"])
        self.assertTrue(q["stale"])

    def test_a_closed_market_quote_is_not_called_stale(self):
        e = self.make()
        obj = quote_obj("ETHA", "18.65", self.now_ts() - 50000, is_open=False)
        self.tx.routes["/quote"] = quote_route(self.table(ETHA=obj))
        q = e.quotes(["ETHA"])["symbols"]["ETHA"]
        self.assertFalse(q["stale"])
        self.assertIs(q["is_market_open"], False)

    def test_the_key_is_never_written_to_the_cache_directory(self):
        e = self.make()
        self.tx.routes["/quote"] = quote_route(self.table())
        e.quotes(["ETHA", "IBIT"])
        blob = "".join(p.read_text() for p in (self.tmp / "cache").rglob("*") if p.is_file())
        self.assertNotIn(KEY, blob)


class TestHistory(EyesCase):
    def test_candles_come_back_oldest_first_as_numbers_in_the_wire_shape(self):
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", series_values(60))})
        h = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertTrue(h["history_ok"])
        for k in ("symbol", "candles", "history_ok", "as_of", "bars", "note", "last_bar_at"):
            self.assertIn(k, h)
        self.assertEqual(h["bars"], 60)
        dates = [c["datetime"] for c in h["candles"]]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(h["last_bar_at"], "2026-09-14")
        last = h["candles"][-1]
        self.assertIsInstance(last["close"], float)
        self.assertEqual(last["close"], 129.5)
        self.assertEqual(last["volume"], 1000.0)
        self.assertEqual(h["source"], "twelve_data")

    def test_it_asks_for_daily_bars_with_one_spare_for_the_partial_day(self):
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", series_values(10))})
        e.history(["ETHA"], days=260)
        p = self.tx.calls[0]["params"]
        self.assertEqual(p["interval"], "1day")
        self.assertEqual(int(p["outputsize"]), 261)

    def test_todays_unfinished_equity_bar_is_set_aside(self):
        # Clock is 10:00 ET on 2026-09-15: a bar dated today is still forming.
        e = self.make()
        vals = series_values(30, end=dt.date(2026, 9, 15))
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", vals)})
        h = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertEqual(h["last_bar_at"], "2026-09-14")
        self.assertEqual(h["bars"], 29)
        self.assertEqual(h["partial_bar"]["datetime"], "2026-09-15")

    def test_after_the_close_todays_equity_bar_counts(self):
        self.clock.t = dt.datetime(2026, 9, 15, 20, 30, 0, tzinfo=UTC)  # 16:30 ET
        e = self.make()
        vals = series_values(30, end=dt.date(2026, 9, 15))
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", vals)})
        h = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertEqual(h["last_bar_at"], "2026-09-15")
        self.assertIsNone(h["partial_bar"])

    def test_a_crypto_bar_for_the_current_utc_day_is_always_unfinished(self):
        self.clock.t = dt.datetime(2026, 9, 15, 23, 50, 0, tzinfo=UTC)
        e = self.make()
        vals = series_values(30, end=dt.date(2026, 9, 15), volume=False)
        self.tx.routes["/time_series"] = series_route({"BTC/USD": series_obj("BTC/USD", vals, "Binance")})
        h = e.history(["BTC-USD"], days=60)["symbols"]["BTC-USD"]
        self.assertEqual(h["last_bar_at"], "2026-09-14")
        self.assertIsNone(h["candles"][-1]["volume"])
        self.assertEqual(h["venue"], "Binance")

    def test_a_bar_without_a_usable_close_is_left_out(self):
        e = self.make()
        vals = series_values(20)
        vals[3]["close"] = ""
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", vals)})
        h = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertEqual(h["bars"], 19)

    def test_history_is_cached_for_hours_and_a_repeat_costs_nothing(self):
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", series_values(60))})
        e.history(["ETHA"], days=60)
        self.clock.advance(3600)
        out = e.history(["ETHA"], days=60)
        self.assertEqual(len(self.tx.calls), 1)
        self.assertEqual(out["credits"]["spent_this_call"], 0)
        self.assertTrue(out["symbols"]["ETHA"]["from_cache"])

    def test_an_empty_series_is_history_not_ok_with_a_reason(self):
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", [])})
        h = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertFalse(h["history_ok"])
        self.assertEqual(h["candles"], [])
        self.assertTrue(h["note"])


def synth_candles(n, start=50.0, step=0.25, spread=0.6):
    out = []
    for i in range(n):
        close = start + step * i + (0.4 if i % 3 == 0 else -0.2)
        out.append({"datetime": "d%03d" % i, "open": close - 0.1, "high": close + spread,
                    "low": close - spread, "close": close, "volume": 1.0})
    return out


class TestFeatureMathMatchesThePlanner(unittest.TestCase):
    """The eyes carry their own copy of the math so they never import the wire
    at runtime. These tests are what stop that copy drifting."""

    @classmethod
    def setUpClass(cls):
        import temple_flow_strategy
        import temple_flow_wire

        cls.wire = temple_flow_wire
        cls.strategy = temple_flow_strategy

    def test_sma_slope_atr_and_window_return_agree_with_the_wire(self):
        candles = synth_candles(90)
        closes = self.wire.closes_of(candles)
        self.assertEqual(eyes_mod.closes_of(candles), closes)
        for n in (5, 20, 50, 89, 90, 91):
            self.assertEqual(eyes_mod.sma(closes, n), self.wire.sma(closes, n))
            self.assertEqual(eyes_mod.atr(candles, n), self.wire.atr(candles, n))
            self.assertEqual(eyes_mod.window_return(closes, n), self.wire.window_return(closes, n))
        for n, lb in ((20, 5), (50, 5), (50, 45)):
            self.assertEqual(eyes_mod.sma_slope(closes, n, lb), self.wire.sma_slope(closes, n, lb))

    def test_a_candle_missing_a_high_makes_atr_none_in_both(self):
        candles = synth_candles(30)
        candles[-2]["high"] = None
        self.assertIsNone(self.wire.atr(candles, 14))
        self.assertIsNone(eyes_mod.atr(candles, 14))

    def test_the_default_periods_are_the_strategys_own(self):
        for k in ("sma_fast", "sma_slow", "slope_lookback", "atr_period"):
            self.assertEqual(eyes_mod.FEATURE_PARAMS[k], self.strategy.PARAMS[k])


class TestFeatures(unittest.TestCase):
    def test_a_full_history_fills_every_feature(self):
        f = eyes_mod.features(synth_candles(120), last=80.0)
        for k in ("bars", "sma20", "sma50", "sma20_slope", "sma50_slope", "atr14",
                  "atr_60d_avg", "atr_ratio", "atr_filter", "ret5d",
                  "dist_to_sma20_pct", "sma20_above_sma50"):
            self.assertIn(k, f)
            self.assertIsNotNone(f[k], k)
        self.assertEqual(f["bars"], 120)
        self.assertTrue(f["sma20_above_sma50"])
        self.assertFalse(f["atr_filter"])

    def test_a_thin_history_gives_nones_not_exceptions(self):
        f = eyes_mod.features(synth_candles(10), last=None)
        self.assertIsNone(f["sma20"])
        self.assertIsNone(f["atr_ratio"])
        self.assertIsNone(f["atr_filter"])
        self.assertIsNone(f["dist_to_sma20_pct"])

    def test_the_constitutions_volatility_filter_trips_above_1_8x(self):
        candles = synth_candles(120)
        for c in candles[-14:]:
            c["high"] = c["close"] + 3.0
            c["low"] = c["close"] - 3.0
        f = eyes_mod.features(candles, last=80.0)
        self.assertGreater(f["atr_ratio"], 1.8)
        self.assertTrue(f["atr_filter"])


# --------------------------------------------------------------------------
# Round C: the look, levels, the stale book, provider reconcile, CLI, isolation
# --------------------------------------------------------------------------
DESK = ("ETHA", "IBIT", "NVO", "NOK")


class LookCase(EyesCase):
    def wire_routes(self, last=None):
        last = dict({"ETHA": "18.65", "IBIT": "43.53", "NVO": "43.17", "NOK": "9.96",
                     "BTC/USD": "81246.77", "ETH/USD": "2515.80"}, **(last or {}))
        qt = {s: quote_obj(s, px, self.now_ts() - 20, exchange="Binance" if "/" in s else "NASDAQ")
              for s, px in last.items()}
        st = {s: series_obj(s, series_values(120, start=float(px) * 0.8, step=float(px) * 0.002,
                                             spread=float(px) * 0.01, volume="/" not in s))
              for s, px in last.items()}
        self.tx.routes["/quote"] = quote_route(qt)
        self.tx.routes["/time_series"] = series_route(st)

    def rules_file(self, **protect):
        p = self.tmp / "standing_rules.json"
        p.write_text(json.dumps({
            "protect": {k: {"stop": v, "duration": "GTC"} for k, v in protect.items()},
            "entries": {"ETHA": {"enabled": False, "qty": 5, "limit": 18.7, "stop": 17.7, "cap": 18.9}},
        }))
        return p

    def snapshot_dir(self):
        d = self.tmp / "snapshots"
        d.mkdir()
        (d / "schwab_2026-09-14_0741ET.json").write_text(json.dumps({"ts_utc": "2026-09-14T11:41:00+00:00", "book": {"equity": 1.0}}))
        (d / "schwab_2026-09-15_0640ET.json").write_text(json.dumps({
            "ts_utc": "2026-09-15T10:40:34+00:00", "mv": "DISARMED",
            "book": {"equity": 592.32, "cash": 433.47, "positions": [
                {"symbol": "IBIT", "qty": 2.0, "avg": 43.9}, {"symbol": "NVO", "qty": 1.0, "avg": 38.92}]},
        }))
        return d


class TestLook(LookCase):
    def test_a_cold_look_at_the_desk_names_fits_one_minute_exactly(self):
        e = self.make()
        self.wire_routes()
        out = e.look()
        self.assertEqual(list(out["symbols"]), list(DESK))
        self.assertEqual(out["credits"]["spent_this_call"], 8)
        self.assertTrue(out["complete"])
        self.assertEqual([c["path"] for c in self.tx.calls], ["/quote", "/time_series"])

    def test_a_warm_look_costs_only_the_quotes_and_then_nothing(self):
        e = self.make()
        self.wire_routes()
        e.look()
        self.clock.advance(eyes_mod.QUOTE_TTL_S + 5)
        self.assertEqual(e.look()["credits"]["spent_this_call"], 4)
        self.clock.advance(10)
        self.assertEqual(e.look()["credits"]["spent_this_call"], 0)

    def test_when_the_minute_is_short_prices_win_over_history(self):
        e = self.make()
        self.wire_routes()
        out = e.look(with_crypto=True)
        self.assertEqual(self.tx.symbols_asked("/quote"), ["ETHA", "IBIT", "NVO", "NOK", "BTC/USD", "ETH/USD"])
        self.assertEqual(self.tx.symbols_asked("/time_series"), ["ETHA", "IBIT"])
        self.assertFalse(out["complete"])
        self.assertEqual({d["what"] for d in out["deferred"]}, {"history"})
        self.assertTrue(all(out["symbols"][s]["quote"]["ok"] for s in out["symbols"]))

    def test_each_symbol_carries_quote_features_and_a_history_summary_not_the_candles(self):
        e = self.make()
        self.wire_routes()
        s = e.look()["symbols"]["IBIT"]
        self.assertEqual(s["quote"]["last"], 43.53)
        self.assertIsNotNone(s["features"]["sma20"])
        self.assertIsNotNone(s["features"]["dist_to_sma20_pct"])
        self.assertEqual(s["history"]["bars"], 120)
        self.assertTrue(s["history"]["history_ok"])
        self.assertNotIn("candles", s["history"])

    def test_protect_stops_come_from_standing_rules_with_the_distance_to_them(self):
        e = self.make()
        self.wire_routes()
        out = e.look(rules_path=self.rules_file(NVO=42.5, NOK=9.45))
        nvo = out["symbols"]["NVO"]
        self.assertEqual(nvo["levels"]["protect_stop"], 42.5)
        self.assertAlmostEqual(nvo["levels"]["dist_to_protect_stop_pct"], (43.17 - 42.5) / 43.17)
        self.assertFalse(nvo["levels"]["at_or_below_protect_stop"])
        etha = out["symbols"]["ETHA"]["levels"]
        self.assertEqual(etha["entry_cap"], 18.9)
        self.assertFalse(etha["above_entry_cap"])

    def test_a_price_through_its_stop_raises_an_alert(self):
        e = self.make()
        self.wire_routes(last={"NVO": "42.10"})
        out = e.look(rules_path=self.rules_file(NVO=42.5))
        self.assertTrue(out["symbols"]["NVO"]["levels"]["at_or_below_protect_stop"])
        self.assertIn({"symbol": "NVO", "code": "at_or_below_protect_stop"}, out["alerts"])

    def test_a_price_above_the_entry_cap_raises_an_alert(self):
        e = self.make()
        self.wire_routes(last={"ETHA": "19.40"})
        out = e.look(rules_path=self.rules_file())
        self.assertIn({"symbol": "ETHA", "code": "above_entry_cap"}, out["alerts"])

    def test_no_rules_file_on_this_machine_is_a_note_not_a_crash(self):
        e = self.make()
        self.wire_routes()
        out = e.look(rules_path=self.tmp / "absent.json")
        self.assertIsNone(out["symbols"]["NVO"]["levels"]["protect_stop"])
        self.assertIn("not found", out["levels_note"])

    def test_the_last_schwab_snapshot_is_shown_and_always_labelled_stale(self):
        e = self.make()
        self.wire_routes()
        snap = e.look(snapshot_dir=self.snapshot_dir())["book_snapshot"]
        self.assertEqual(snap["file"], "schwab_2026-09-15_0640ET.json")
        self.assertIs(snap["stale"], True)
        self.assertAlmostEqual(snap["age_hours"], 3.32, places=1)
        self.assertEqual(snap["equity"], 592.32)
        ibit = [p for p in snap["positions"] if p["symbol"] == "IBIT"][0]
        self.assertAlmostEqual(ibit["est_mv"], 2 * 43.53)
        self.assertAlmostEqual(ibit["est_unrealized_pct"], (43.53 - 43.9) / 43.9)
        self.assertIn("live Schwab equity", snap["note"])

    def test_no_snapshot_directory_is_reported_plainly(self):
        e = self.make()
        self.wire_routes()
        out = e.look(snapshot_dir=self.tmp / "none")
        self.assertIsNone(out["book_snapshot"])
        self.assertTrue(out["book_snapshot_note"])

    def test_a_stale_quote_raises_an_alert(self):
        e = self.make()
        self.wire_routes()
        table = {s: quote_obj(s, "10.00", self.now_ts() - 7200) for s in DESK}
        self.tx.routes["/quote"] = quote_route(table)
        self.assertIn({"symbol": "ETHA", "code": "quote_stale"}, e.look()["alerts"])

    def test_the_look_is_stamped_evidence_only(self):
        e = self.make()
        self.wire_routes()
        out = e.look()
        self.assertIs(out["evidence_only"], True)
        self.assertIs(out["not_for_execution"], True)
        self.assertEqual(out["op"], "look")


class TestProviderReconcile(EyesCase):
    def test_credits_another_app_spent_on_the_same_key_tighten_the_minute(self):
        # The Tape apps share this key. Twelve Data reports the true per-minute
        # count in a header; when it is higher than ours, theirs wins.
        e = self.make()
        table = {"ETHA": quote_obj("ETHA", "18.65", self.now_ts() - 5)}

        def handler(params):
            return ok(table[params["symbol"]], headers={"api-credits-used": "6", "api-credits-left": "2"})

        self.tx.routes["/quote"] = handler
        out = e.quotes(["ETHA"])
        self.assertEqual(out["credits"]["provider_reported"], {"used": 6.0, "left": 2.0})
        self.assertEqual(e.ledger.allowance(), 2)

    def test_a_lower_provider_count_never_loosens_the_local_ledger(self):
        e = self.make()
        e.ledger.record(5, "earlier")
        table = {"ETHA": quote_obj("ETHA", "18.65", self.now_ts() - 5)}
        self.tx.routes["/quote"] = lambda p: ok(table[p["symbol"]], headers={"api-credits-used": "1"})
        e.quotes(["ETHA"])
        self.assertEqual(e.ledger.allowance(), 2)


class TestCli(LookCase):
    def run_cli(self, argv, e, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = eyes_mod.main(argv, eyes=e, **kw)
        return code, buf.getvalue()

    def test_budget_costs_nothing_and_prints_json(self):
        e = self.make()
        code, text = self.run_cli(["budget"], e)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["minute_limit"], 8)
        self.assertEqual(self.tx.calls, [])

    def test_status_says_whether_a_key_is_present_and_never_prints_it(self):
        e = self.make()
        code, text = self.run_cli(["status"], e)
        self.assertEqual(code, 0)
        self.assertIs(json.loads(text)["key_present"], True)
        self.assertNotIn(KEY, text)

    def test_quote_prints_one_json_document(self):
        e = self.make()
        self.wire_routes()
        code, text = self.run_cli(["quote", "ETHA", "BTC-USD"], e)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["symbols"]["BTC-USD"]["last"], 81246.77)

    def test_history_prints_the_candles(self):
        e = self.make()
        self.wire_routes()
        code, text = self.run_cli(["history", "ETHA", "--days", "30"], e)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["symbols"]["ETHA"]["bars"], 30)

    def test_an_incomplete_answer_exits_3(self):
        e = self.make()
        self.wire_routes()
        e.ledger.record(7, "earlier")
        code, _ = self.run_cli(["quote", "ETHA", "IBIT"], e)
        self.assertEqual(code, 3)

    def test_no_key_exits_2(self):
        e = self.make(key=None)
        code, text = self.run_cli(["quote", "ETHA"], e)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)["symbols"]["ETHA"]["reason"], "no_api_key")

    def test_wait_sleeps_out_the_minute_and_finishes_the_look(self):
        e = self.make()
        self.wire_routes()
        naps = []

        def nap(seconds):
            naps.append(seconds)
            self.clock.advance(seconds)

        code, text = self.run_cli(["look", "--with-crypto", "--wait"], e, sleep=nap)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(text)["complete"])
        self.assertTrue(naps and all(0 < n <= 61 for n in naps))

    def test_text_mode_is_a_brief_a_human_can_read(self):
        e = self.make()
        self.wire_routes()
        code, text = self.run_cli(["look", "--text"], e)
        self.assertEqual(code, 0)
        self.assertIn("IBIT", text)
        self.assertIn("43.53", text)
        self.assertIn("evidence only", text.lower())
        self.assertNotIn(KEY, text)


ALLOWED_IMPORTS = {
    "__future__", "argparse", "datetime", "fcntl", "json", "math", "os", "re", "sys",
    "time", "urllib", "pathlib", "typing", "zoneinfo",
}
ALLOWED_ALIASES = {("datetime", "dt")}  # `import os as _o` hides every os.* check
ALLOWED_FROM = {"__future__": None, "typing": None, "pathlib": {"Path"}, "zoneinfo": {"ZoneInfo"}}
ALLOWED_OS_ATTRS = {"environ", "replace"}
ALLOWED_URLLIB = {
    "urllib.request.Request", "urllib.request.urlopen", "urllib.error.HTTPError",
    "urllib.parse.urlencode", "urllib.parse.quote", "urllib.parse.quote_plus",
}
BANNED_CALLS = {"__import__", "exec", "eval", "compile"}
BANNED_NAMES = {"globals", "locals", "vars", "__builtins__", "__import__"}
REFLECTED_MODULES = {"os", "sys", "urllib"}  # getattr(os, "sys" + "tem") is still os.system
REQUEST_MUTATIONS = {"data", "method", "get_method", "full_url", "selector"}
PATH_WRITERS = {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir", "rename",
                "symlink_to", "hardlink_to", "chmod", "open"}
# The only places allowed to write a file, by exact Class.method. Every one of
# them writes under the cache directory and nowhere else. A bare name would let
# any new function called `_write` inherit the permission.
ALLOWED_WRITERS = {"Ledger._write", "Ledger._locked", "Ledger._heal_unlocked", "Eyes._cache_put"}
_URLISH = re.compile(r"^\s*(https?:|//)|://")


def _is_write_call(node: ast.Call) -> str | None:
    """The name of the filesystem write this call performs, or None.

    `os.replace` counts; `"text".replace(...)` and `datetime.replace(...)` do not.
    Any `.open(...)` counts: Path.open and an opener's open both reach outward.
    """
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return "open"
    if isinstance(func, ast.Attribute):
        if func.attr in PATH_WRITERS:
            return func.attr
        if func.attr == "replace" and isinstance(func.value, ast.Name) and func.value.id == "os":
            return "os.replace"
    return None


def _dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def structural_violations(source: str) -> list:
    """Every way `source` breaks the eyes' isolation rules, as readable strings.

    Imports, `from` imports, aliases, `os` attributes, `urllib` attributes and
    file-writing functions are WHITELISTS: anything not named is a violation.
    The rest (banned builtins, reflection on os/sys/urllib, URL-like strings,
    mutating a request after building it) are pattern checks, and a pattern
    check passes whatever nobody thought of. So this is a guard against the
    file drifting toward having hands, not a proof against someone determined
    to hide them. Review still matters.
    """
    tree = ast.parse(source)
    out: list = []
    parent: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))

    def owner(node) -> str:
        """`Class.method` for the OUTERMOST function around `node`, else where it runs."""
        funcs, cls = [], None
        cur = parent.get(id(node))
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append(cur.name)
            elif isinstance(cur, ast.ClassDef) and cls is None:
                cls = cur.name
            cur = parent.get(id(cur))
        if not funcs:
            return "class body" if cls else "module level"
        return ("%s.%s" % (cls, funcs[-1])) if cls else funcs[-1]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    out.append("import %s" % a.name)
                if a.asname and (a.name, a.asname) not in ALLOWED_ALIASES:
                    out.append("import %s as %s" % (a.name, a.asname))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod not in ALLOWED_FROM:
                out.append("from %s import ..." % mod)
            elif ALLOWED_FROM[mod] is not None:
                for a in node.names:
                    if a.name not in ALLOWED_FROM[mod] or a.asname:
                        out.append("from %s import %s" % (mod, a.name))
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted and dotted.startswith("os.") and dotted.split(".")[1] not in ALLOWED_OS_ATTRS:
                out.append(dotted)
            if dotted and dotted.startswith("urllib.") and dotted.count(".") >= 2:
                head = ".".join(dotted.split(".")[:3])
                if head not in ALLOWED_URLLIB:
                    out.append(dotted)
            if isinstance(node.ctx, ast.Store) and node.attr in REQUEST_MUTATIONS:
                out.append("assignment to .%s (mutating a request after building it)" % node.attr)
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            out.append("name %s" % node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if _URLISH.search(node.value) and not node.value.startswith("https://api.twelvedata.com"):
                out.append("url-like constant %r" % node.value[:40])

        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            # Builtins are banned by bare name (so re.compile is fine, compile()
            # is not); import_module is banned however it is reached.
            if (isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS) or name == "import_module":
                out.append("call %s()" % name)
            if isinstance(node.func, ast.Name) and node.func.id in ("getattr", "setattr", "delattr"):
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Name) and first.id in REFLECTED_MODULES:
                    out.append("%s(%s, ...)" % (node.func.id, first.id))
            if name == "Request":
                if len(node.args) != 1 or {k.arg for k in node.keywords} - {"headers"}:
                    out.append("Request() must be Request(url, headers=...): a body or method makes it not a GET")
            if name == "urlopen":
                if len(node.args) != 1 or {k.arg for k in node.keywords} - {"timeout"}:
                    out.append("urlopen() must be urlopen(req, timeout=...): a second argument is a POST body")
            write = _is_write_call(node)
            if write and owner(node) not in ALLOWED_WRITERS:
                out.append("%s writes via %s()" % (owner(node), write))
    return out


class TestTheEyesCannotReachTheOrderPath(unittest.TestCase):
    """Structural, in the spirit of the wire's own AST tripwires: these read the
    source, so an edit that gives this file hands fails the suite. The second
    test is the one that proves the first can fail."""

    @classmethod
    def setUpClass(cls):
        cls.path = Path(eyes_mod.__file__)
        cls.source = cls.path.read_text()

    def test_the_source_as_written_breaks_no_isolation_rule(self):
        self.assertEqual(structural_violations(self.source), [])

    def test_the_tripwire_catches_every_bypass_the_review_found(self):
        # These snippets are hostile ON PURPOSE and are never executed: they are
        # appended to the source as text and only ast.parse()d, to prove the
        # tripwire trips on each of them.
        hostile = {
            "shell out": "def h():\n    os.system('python3 scripts/temple_flow_wire.py')\n",
            "popen": "def h():\n    os.popen('x')\n",
            "lazy import of the wire": "def h():\n    import importlib\n    importlib.import_module('temple_flow_wire')\n",
            "dunder import": "def h():\n    __import__('temple_flow_wire')\n",
            "direct import": "import temple_flow_wire\n",
            "subprocess": "import subprocess\n",
            "http.client": "import http.client\n",
            "post via urlopen": "def h(req):\n    urllib.request.urlopen(req, b'body')\n",
            "post via Request data": "def h(u):\n    urllib.request.Request(u, b'body')\n",
            "post via method kw": "def h(u):\n    urllib.request.Request(u, headers={}, method='POST')\n",
            "assembled broker url": "def h():\n    return '%s://%s' % ('htt' + 'ps', 'api.schwabapi.com')\n",
            "plain broker url": "B = 'https://api.schwabapi.com/trader/v1'\n",
            "write into the outbox": "def h():\n    Path('config/outbox/x.json').write_text('{}')\n",
            "open for writing": "def h():\n    open('config/LIVE_OK', 'w')\n",
            "exec": "def h(s):\n    exec(s)\n",
            # Second review round: the ways the first hardening still leaked.
            "aliased os": "import os as _o\ndef h():\n    _o.system('x')\n",
            "from os import": "from os import system\ndef h():\n    system('x')\n",
            "reflection on os": "def h():\n    getattr(os, 'sys' + 'tem')('x')\n",
            "url built from halves": "B = 'https:' + '//api.schwabapi.com/trader/v1'\n",
            "scheme-less url": "def h():\n    urllib.request.Request('//api.schwabapi.com/x', headers={})\n",
            "Path.open for writing": "def h():\n    Path('config/outbox/x.json').open('w').write('{}')\n",
            "impostor function named _write": "def _write():\n    Path('config/LIVE_OK').write_text('')\n",
            "impostor method named _write": "class X:\n    def _write(self):\n        Path('config/LIVE_OK').write_text('')\n",
            "write in a class body": "class K:\n    Path('config/LIVE_OK').write_text('')\n",
            "opener instead of urlopen": "def h(u):\n    urllib.request.build_opener().open(u, b'x')\n",
            "body added after the fact": "def h(u):\n    r = urllib.request.Request(u, headers={})\n    r.data = b'{}'\n",
            "method swapped after the fact": "def h(u):\n    r = urllib.request.Request(u, headers={})\n    r.get_method = lambda: 'DELETE'\n",
            "import through globals": "def h():\n    globals()['__builtins__']['__import__']('temple_flow_wire')\n",
        }
        for label, snippet in hostile.items():
            with self.subTest(label):
                found = structural_violations(self.source + "\n\n" + snippet)
                self.assertTrue(found, "tripwire missed: %s" % label)

    def test_importing_the_eyes_does_not_load_the_wire(self):
        import subprocess

        probe = ("import sys; sys.path.insert(0, %r); import temple_flow_eyes; "
                 "print('temple_flow_wire' in sys.modules)") % str(self.path.parent)
        out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


class TestALookOnlyWritesInsideItsCache(LookCase):
    def test_nothing_outside_the_cache_directory_changes(self):
        repo = self.tmp / "repo"
        (repo / "config" / "outbox").mkdir(parents=True)
        rules = repo / "config" / "standing_rules.json"
        rules.write_text(json.dumps({"protect": {"NVO": {"stop": 42.5}}}))
        snaps = repo / "logs" / "snapshots"
        snaps.mkdir(parents=True)
        (snaps / "schwab_2026-09-15_0640ET.json").write_text(json.dumps({"ts_utc": "2026-09-15T10:40:34+00:00", "book": {}}))

        def tree():
            return {str(p.relative_to(self.tmp)): p.stat().st_mtime_ns
                    for p in self.tmp.rglob("*") if p.is_file()}

        before = tree()
        e = self.make()
        self.wire_routes()
        e.look(with_crypto=True, rules_path=rules, snapshot_dir=snaps)
        after = tree()
        changed = {k for k in after if before.get(k) != after[k]}
        self.assertTrue(changed)
        self.assertTrue(all(k.startswith("cache/") for k in changed), sorted(changed))


# --------------------------------------------------------------------------
# Round D: what the independent review found
# --------------------------------------------------------------------------
class TestSpendingIsAtomic(OfflineCase):
    def ledger(self, **kw):
        return eyes_mod.Ledger(self.tmp / "ledger.json", now=self.clock, **kw)

    def test_reserve_grants_only_what_fits_and_charges_it(self):
        led = self.ledger()
        led.record(6, "earlier")
        got = led.reserve(5, "quote")
        self.assertEqual(got["granted"], 2)
        self.assertEqual(got["reason"], "minute_budget")
        self.assertEqual(led.allowance(), 0)

    def test_a_tie_between_the_two_budgets_blames_the_minute_not_the_day(self):
        led = self.ledger(day_budget=8)
        led.record(5, "earlier")
        got = led.reserve(5, "quote")
        self.assertEqual(got["granted"], 3)
        self.assertEqual(got["reason"], "minute_budget")

    def test_a_day_that_is_the_tighter_limit_is_named_as_such(self):
        led = self.ledger(day_budget=3)
        got = led.reserve(5, "quote")
        self.assertEqual(got["granted"], 3)
        self.assertEqual(got["reason"], "day_budget")

    def race(self, ledger_cls, tag: str) -> int:
        """Four processes each try to reserve the whole minute at once. Returns
        the total granted between them; anything above 8 is an overrun."""
        path = self.tmp / ("race-" + tag) / "ledger.json"
        go = self.tmp / ("go-" + tag)
        kids = []
        for i in range(4):
            pid = os.fork()
            if pid == 0:
                # Child. It must ALWAYS leave via os._exit, and must never wait
                # forever: if the parent dies first the start file never comes.
                code = 1
                try:
                    import time as _t
                    deadline = _t.monotonic() + 10.0
                    while not go.exists() and _t.monotonic() < deadline:
                        _t.sleep(0.001)
                    if go.exists():
                        got = ledger_cls(path).reserve(8, "racer%d" % i)
                        (self.tmp / ("granted-%s-%d" % (tag, i))).write_text(str(got["granted"]))
                        code = 0
                except BaseException:
                    code = 1
                finally:
                    os._exit(code)
            kids.append(pid)
        go.write_text("go")
        # Reap every child BEFORE asserting anything: a failed assertion runs
        # tearDown, which deletes the directory the other children are reading.
        statuses = [os.waitpid(pid, 0)[1] for pid in kids]
        self.assertEqual(statuses, [0, 0, 0, 0])
        return sum(int((self.tmp / ("granted-%s-%d" % (tag, i))).read_text()) for i in range(4))

    def test_processes_racing_cannot_spend_more_than_the_minute(self):
        # Repeated, because a race is a probability: one clean run proves little.
        totals = [self.race(eyes_mod.Ledger, "ok%d" % k) for k in range(8)]
        self.assertEqual(totals, [8] * 8)

    def test_the_race_test_really_does_catch_a_non_atomic_ledger(self):
        """The detector's own self-test. This is the first version's bug, kept on
        purpose: read, decide and charge under SEPARATE locks. If the race above
        cannot catch this, it cannot be trusted to guard the real one."""

        class NonAtomicLedger(eyes_mod.Ledger):
            def reserve(self, n, what):
                import time as _t
                room = self.allowance()          # lock taken and released
                _t.sleep(0.02)                   # the window the real bug had, made wide
                granted = max(0, min(int(n), room))
                self.record(granted, what)       # a second, separate lock
                return {"granted": granted, "reason": None, "retry_after_s": 0}

        totals = [self.race(NonAtomicLedger, "bad%d" % k) for k in range(3)]
        self.assertTrue(any(t > 8 for t in totals), "the race test failed to detect an overrun: %s" % totals)

    def test_a_ledger_that_cannot_be_written_refuses_the_spend(self):
        blocker = self.tmp / "afile"
        blocker.write_text("not a directory")
        tx = FakeTransport()
        tx.routes["/quote"] = quote_route({"ETHA": quote_obj("ETHA", "18.65", 1)})
        e = eyes_mod.Eyes(key=KEY, cache_dir=blocker / "cache", now=self.clock, transport=tx)
        out = e.quotes(["ETHA"])
        self.assertEqual(tx.calls, [])
        self.assertEqual(out["symbols"]["ETHA"]["reason"], "ledger_unavailable")
        self.assertFalse(out["complete"])

    def test_status_reports_an_overrun_rather_than_hiding_it(self):
        led = self.ledger()
        led.record(8, "a")
        led.record(8, "b")
        self.assertEqual(led.status()["minute_used"], 16)
        self.assertEqual(led.allowance(), 0)


class TestHealKeepsTheDay(OfflineCase):
    def test_a_truncated_ledger_keeps_the_spend_it_can_still_read(self):
        led = eyes_mod.Ledger(self.tmp / "ledger.json", now=self.clock, day_budget=400)
        for _ in range(40):
            led.record(8, "quote")
            self.clock.advance(61)
        path = self.tmp / "ledger.json"
        path.write_text(path.read_text()[:-25])  # a torn tail
        s = eyes_mod.Ledger(path, now=self.clock, day_budget=400).status()
        self.assertTrue(s["ledger_healed"])
        self.assertGreaterEqual(s["day_used"], 300)

    def test_an_unreadable_ledger_with_nothing_to_salvage_assumes_half_the_day_is_gone(self):
        (self.tmp / "ledger.json").write_text("\x00\x00 garbage")
        s = eyes_mod.Ledger(self.tmp / "ledger.json", now=self.clock, day_budget=400).status()
        self.assertEqual(s["day_used"], 200)


class TestFreshnessHonesty(EyesCase):
    def one(self, obj, **kw):
        e = self.make()
        self.tx.routes["/quote"] = quote_route({"ETHA": obj})
        return e, e.quotes(["ETHA"], **kw)["symbols"]["ETHA"]

    def test_a_weekend_old_close_is_labelled_closed_not_stale(self):
        _, q = self.one(quote_obj("ETHA", "18.65", self.now_ts() - 65 * 3600, is_open=False))
        self.assertEqual(q["market_state"], "closed")
        self.assertFalse(q["stale"])

    def test_a_closed_market_price_older_than_a_long_weekend_is_stale(self):
        _, q = self.one(quote_obj("ETHA", "18.65", self.now_ts() - 6 * 86400, is_open=False))
        self.assertTrue(q["stale"])

    def test_an_unknown_market_state_is_held_to_the_open_market_standard(self):
        obj = quote_obj("ETHA", "18.65", self.now_ts() - 3600)
        del obj["is_market_open"]
        _, q = self.one(obj)
        self.assertEqual(q["market_state"], "unknown")
        self.assertTrue(q["stale"])

    def test_a_quote_served_from_an_old_cache_is_stale_whatever_the_market_said_then(self):
        e, _ = self.one(quote_obj("ETHA", "18.65", self.now_ts() - 60, is_open=False))
        self.clock.advance(3600)
        q = e.quotes(["ETHA"], max_age_s=10**6)["symbols"]["ETHA"]
        self.assertTrue(q["from_cache"])
        self.assertTrue(q["stale"])

    def test_every_answer_says_when_its_data_was_fetched(self):
        _, q = self.one(quote_obj("ETHA", "18.65", self.now_ts() - 5))
        self.assertTrue(q["fetched_at"].startswith("2026-09-15T10:00:00"))

    def test_a_closed_market_shows_up_in_the_look_alerts(self):
        e = self.make()
        table = {s: quote_obj(s, "10.00", self.now_ts() - 3600, is_open=False) for s in DESK}
        self.tx.routes["/quote"] = quote_route(table)
        self.tx.routes["/time_series"] = series_route({s: series_obj(s, series_values(80)) for s in DESK})
        self.assertIn({"symbol": "IBIT", "code": "market_closed_last_session_price"}, e.look()["alerts"])


class TestHistoryCacheRespectsTheSessionBoundary(EyesCase):
    def test_history_fetched_before_the_close_is_refetched_after_it(self):
        self.clock.t = dt.datetime(2026, 9, 15, 19, 0, 0, tzinfo=UTC)  # 15:00 ET
        e = self.make()
        table = {"ETHA": series_obj("ETHA", series_values(30, end=dt.date(2026, 9, 15)))}
        self.tx.routes["/time_series"] = series_route(table)
        self.assertEqual(e.history(["ETHA"], days=60)["symbols"]["ETHA"]["last_bar_at"], "2026-09-14")
        self.clock.t = dt.datetime(2026, 9, 16, 0, 30, 0, tzinfo=UTC)  # 20:30 ET, same session date
        h = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertEqual(len(self.tx.calls), 2)
        self.assertEqual(h["last_bar_at"], "2026-09-15")

    def test_history_fetched_after_the_close_is_reused_all_evening(self):
        self.clock.t = dt.datetime(2026, 9, 15, 20, 30, 0, tzinfo=UTC)  # 16:30 ET
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", series_values(30, end=dt.date(2026, 9, 15)))})
        e.history(["ETHA"], days=60)
        self.clock.advance(4 * 3600)
        e.history(["ETHA"], days=60)
        self.assertEqual(len(self.tx.calls), 1)

    def test_a_weekend_does_not_force_a_refetch(self):
        self.clock.t = dt.datetime(2026, 9, 18, 21, 0, 0, tzinfo=UTC)  # Friday 17:00 ET
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", series_values(30, end=dt.date(2026, 9, 18)))})
        e.history(["ETHA"], days=60)
        self.clock.advance(5 * 3600)  # still Friday night ET
        e.history(["ETHA"], days=60)
        self.assertEqual(len(self.tx.calls), 1)

    def test_crypto_history_is_refetched_after_utc_midnight(self):
        self.clock.t = dt.datetime(2026, 9, 15, 23, 0, 0, tzinfo=UTC)
        e = self.make()
        self.tx.routes["/time_series"] = series_route(
            {"BTC/USD": series_obj("BTC/USD", series_values(30, end=dt.date(2026, 9, 15), volume=False), "Binance")})
        e.history(["BTC-USD"], days=60)
        self.clock.t = dt.datetime(2026, 9, 16, 0, 10, 0, tzinfo=UTC)
        e.history(["BTC-USD"], days=60)
        self.assertEqual(len(self.tx.calls), 2)

    def test_a_malformed_series_is_not_cached_as_if_it_were_an_answer(self):
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": {"meta": {}, "values": "oops", "status": "ok"}})
        first = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertFalse(first["history_ok"])
        self.clock.advance(120)
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", series_values(30))})
        second = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertTrue(second["history_ok"])
        self.assertEqual(len(self.tx.calls), 2)

    def test_a_series_that_is_nothing_but_todays_unfinished_bar_is_not_cached(self):
        e = self.make()  # 10:00 ET on 2026-09-15
        only_today = series_obj("ETHA", series_values(1, end=dt.date(2026, 9, 15)))
        self.tx.routes["/time_series"] = series_route({"ETHA": only_today})
        h = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertFalse(h["history_ok"])
        self.assertFalse(list((self.tmp / "cache").glob("history_ETHA*")))

    def test_the_first_minutes_after_the_bell_still_count_as_unfinished(self):
        # The provider's daily bar is provisional right after 16:00. A bar taken
        # then would be cached as finished and served for hours with the wrong close.
        self.clock.t = dt.datetime(2026, 9, 15, 20, 10, 0, tzinfo=UTC)  # 16:10 ET
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", series_values(30, end=dt.date(2026, 9, 15)))})
        h = e.history(["ETHA"], days=60)["symbols"]["ETHA"]
        self.assertEqual(h["last_bar_at"], "2026-09-14")
        self.assertEqual(h["partial_bar"]["datetime"], "2026-09-15")

    def test_the_request_never_asks_for_more_than_the_provider_allows(self):
        e = self.make()
        self.tx.routes["/time_series"] = series_route({"ETHA": series_obj("ETHA", series_values(5))})
        e.history(["ETHA"], days=10**9)
        self.assertLessEqual(int(self.tx.calls[0]["params"]["outputsize"]), 5000)
        self.assertFalse(list((self.tmp / "cache").glob("*1000000000*")))


class TestNumberParsingAgainstTheWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import temple_flow_wire
        cls.wire = temple_flow_wire

    def test_the_two_parsers_agree_on_every_finite_input(self):
        for v in (None, "", 0, 1, -3, 2.5, "12.5", " 7 ", "1e3", "-0.25", "abc", [], {}):
            with self.subTest(repr(v)):
                self.assertEqual(eyes_mod._f(v), self.wire._f(v))

    def test_the_eyes_are_deliberately_stricter_about_non_numbers(self):
        # The wire's _f lets these through as 1.0 / nan / inf. Provider text is
        # less trusted than a broker field, so the eyes drop the bar instead.
        for v in (True, False, "NaN", float("nan"), "inf", float("inf"), "-inf", "1e400"):
            with self.subTest(repr(v)):
                self.assertIsNone(eyes_mod._f(v))

    def test_features_never_bridge_a_missing_day_to_invent_an_atr(self):
        # features() must hand atr() the SAME list the wire would see. Compacting
        # the list first would compute a true range across a hole and return a
        # number where both copies of atr() say None.
        candles = synth_candles(40)
        candles[-3]["close"] = None
        self.assertIsNone(self.wire.atr(candles, 14))
        self.assertIsNone(eyes_mod.atr(candles, 14))
        self.assertIsNone(eyes_mod.features(candles, last=60.0)["atr14"])

    def test_features_survive_a_nan_close_without_poisoning_the_average(self):
        candles = synth_candles(60)
        candles[30]["close"] = "NaN"
        f = eyes_mod.features(candles, last=60.0)
        self.assertIsNotNone(f["sma20"])
        self.assertEqual(f["sma20"], f["sma20"])  # not NaN


class TestConfigurationParsing(OfflineCase):
    def test_a_day_budget_of_zero_means_zero(self):
        self.assertEqual(eyes_mod.parse_day_budget("0"), 0)

    def test_nonsense_falls_back_to_the_default(self):
        for raw in (None, "", "abc", "-5"):
            with self.subTest(repr(raw)):
                self.assertEqual(eyes_mod.parse_day_budget(raw), eyes_mod.DEFAULT_DAY_BUDGET)

    def test_a_budget_above_the_plan_is_clamped_to_the_plan(self):
        self.assertEqual(eyes_mod.parse_day_budget("10000"), 800)

    def test_a_key_with_whitespace_or_control_characters_is_rejected(self):
        self.assertIsNone(eyes_mod.load_key({"TWELVE_DATA_API_KEY": "abc\ndef"}, []))
        self.assertIsNone(eyes_mod.load_key({"TWELVE_DATA_API_KEY": "abc def"}, []))

    def test_redaction_also_covers_encoded_and_escaped_forms_of_the_key(self):
        key = "ab+c/d=e"
        for text in ("x ab+c/d=e y", "x ab%2Bc%2Fd%3De y", "x %r y" % key):
            with self.subTest(text):
                self.assertNotIn("ab", eyes_mod.redact(text, key).replace("[redacted]", ""))

    def test_a_cache_directory_inside_config_or_logs_is_refused(self):
        for bad in ("config/outbox", "config", "logs/tickets"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    eyes_mod.safe_cache_dir(eyes_mod.REPO_ROOT / bad)
        ok_dir = eyes_mod.REPO_ROOT / "data" / "cache" / "eyes"
        self.assertEqual(eyes_mod.safe_cache_dir(ok_dir), ok_dir)


class TestTheCliAlwaysAnswersInJson(LookCase):
    def run_cli(self, argv, e):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = eyes_mod.main(argv, eyes=e)
        return code, buf.getvalue()

    def test_an_unexpected_exception_becomes_a_json_error_with_its_own_exit_code(self):
        e = self.make()

        def boom(*a, **k):
            raise RuntimeError("kaput " + KEY)

        e.look = boom
        code, text = self.run_cli(["look"], e)
        doc = json.loads(text)
        self.assertEqual(code, 4)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["reason"], "internal_error")
        self.assertEqual(doc["error_type"], "RuntimeError")
        self.assertNotIn(KEY, text)

    def test_a_snapshot_whose_book_is_not_an_object_is_skipped_not_fatal(self):
        d = self.tmp / "snaps"
        d.mkdir()
        (d / "schwab_2026-09-15_0640ET.json").write_text(json.dumps({"ts_utc": "x", "book": ["not", "a", "dict"]}))
        (d / "schwab_2026-09-14_0741ET.json").write_text(json.dumps({"ts_utc": "2026-09-14T11:41:00+00:00", "book": {"equity": 5.0}}))
        e = self.make()
        self.wire_routes()
        snap = e.look(snapshot_dir=d)["book_snapshot"]
        self.assertEqual(snap["file"], "schwab_2026-09-14_0741ET.json")

    def test_a_mistyped_command_line_is_json_with_its_own_exit_code(self):
        # argparse would exit 2 with prose on stderr, and 2 already means "no API
        # key": a bot could not tell "I typed it wrong" from "this box has no key".
        e = self.make()
        for argv in (["quote"], ["history", "IBIT", "--days", "abc"], ["nosuchcmd"], []):
            with self.subTest(argv=argv):
                code, text = self.run_cli(argv, e)
                doc = json.loads(text)
                self.assertEqual(code, 5)
                self.assertFalse(doc["ok"])
                self.assertEqual(doc["reason"], "usage_error")
                self.assertTrue(doc["detail"])
        self.assertEqual(self.tx.calls, [])

    def test_budget_on_an_unwritable_ledger_says_so_the_same_way_a_quote_does(self):
        blocker = self.tmp / "afile"
        blocker.write_text("not a directory")
        e = eyes_mod.Eyes(key=KEY, cache_dir=blocker / "cache", now=self.clock, transport=FakeTransport())
        code, text = self.run_cli(["budget"], e)
        self.assertEqual(code, 3)
        self.assertIs(json.loads(text)["ledger_unavailable"], True)

    def test_a_snapshot_that_is_not_an_object_at_all_is_skipped(self):
        d = self.tmp / "snaps"
        d.mkdir()
        (d / "schwab_2026-09-15_0640ET.json").write_text("[1, 2, 3]")
        e = self.make()
        self.wire_routes()
        out = e.look(snapshot_dir=d)
        self.assertIsNone(out["book_snapshot"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
