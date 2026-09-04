#!/usr/bin/env python3
"""Default off-hours strategy for the Temple Flow planner. THE REPLACEABLE SEAM.

Anthony, 2026-09-03 07:49 EDT:
    "on market off hours, there should be more strategy being defined and
     planning on the trends"

THIS FILE IS THE SEAM. It is written to be thrown away: when Grok's spec lands,
`evaluate()` below is replaced wholesale and nothing in `temple_flow_wire.py`
should have to change. The contract is therefore stated here, in full, and it
is a contract in BOTH directions.

======================================================================
THE CONTRACT
======================================================================

REQUIRED of any replacement:

    evaluate(symbol: str, features: dict, rules: dict) -> dict | None

  Returns a CANDIDATE dict, or None to decline. Pure: no network, no clock,
  no filesystem, no globals, no randomness. Same inputs, same output, forever
  — the planner writes the result to a file a human reads hours later, and a
  candidate that cannot be re-derived is not a plan, it is a rumour.

  A candidate MUST carry:
      symbol     str   — echo of the argument
      limit      float — proposed BUY limit, already rounded to the tick
      stop       float — proposed protective stop, strictly BELOW limit
      rationale  str   — one legible sentence a human can act on
  and MAY carry:
      qty_hint   int   — an UPPER bound the wire may shrink, never a floor
      checks     dict  — the named conditions and their booleans
      strategy   str   — an identifier for the ruleset that fired

OPTIONAL of any replacement:

    check_conditions(symbol, features, rules) -> dict[str, bool]

  Every named condition and whether it held. The planner uses it ONLY to write
  down WHY a symbol produced no candidate — `evaluate` returning None cannot
  say. A replacement that omits it is legal; the plan file then records the
  decision as `strategy_declined` with no breakdown, which is a worse plan but
  not a broken one.

======================================================================
WHAT THIS FILE MAY NOT DO — the half that protects the account
======================================================================

**A strategy PROPOSES. It never SIZES, and it can never widen a risk cap.**
Position size is computed in the wire from live equity, `risk_pct`, `clip_qty`
and the notional cap, and the resulting ticket is then re-gated by
`gate_outbox_ticket` like any other. `qty_hint` can only make a position
SMALLER. A replacement strategy that returns `qty_hint: 10_000`, a stop above
the limit, or a limit above the entry cap gets a refused or shrunken ticket,
not a bigger trade. That is deliberate: the seam is open so the IDEA can be
replaced, not so the risk law can be.

**And nothing here places an order.** This module has no broker, no HTTP, no
outbox write. Its entire output is a proposal written to `config/plans/`, which
a human must approve with `--approve-plan` before it can reach `config/outbox/`.

======================================================================
DEFINITIONS — a replacement must compute the same numbers or say it doesn't
======================================================================

The wire computes the features; these are the definitions it uses, restated
here because a replacement strategy is entitled to know exactly what it is
being handed:

  sma20 / sma50     simple mean of the last N daily CLOSES.
  *_slope           per-day change of that SMA over `slope_lookback` (5)
                    sessions: (sma[-1] - sma[-1-5]) / 5. Positive = rising.
                    Units are dollars per day, not a percentage.
  atr14             the SIMPLE 14-period mean of the true range,
                    TR = max(high-low, |high-prev_close|, |low-prev_close|).
                    NOT Wilder's smoothing — this is the plainer number and
                    runs about the same on 14 bars; say which one you use.
  ret5d             (close[-1] - close[-6]) / close[-6], from CLOSES only.
                    Deliberately does not move within a session.
  dist_to_sma20_pct (last - sma20) / sma20, using the live quote's `last`.
  last_vs_cap       last - cap, in dollars. Negative means under the cap.

Parameters all come from `rules["strategy"]` with the defaults in `PARAMS`.
Read them through `params(rules)` so a replacement inherits the same handling
of a missing or unparseable value (fall back to the default; never raise).
"""
from __future__ import annotations

import math
from typing import Any

#: Equity tick. Everything a strategy proposes is a whole cent.
TICK = 0.01

#: Defaults for `rules["strategy"]`. Every one is overridable in
#: config/standing_rules.json; none of them may loosen a risk cap, because no
#: risk cap is read from here.
PARAMS = {
    # trend definition
    "sma_fast": 20,
    "sma_slow": 50,
    "slope_lookback": 5,
    "atr_period": 14,
    # how far above the fast SMA an entry may still be taken. The band is the
    # whole no-chase idea expressed as a number: buying 6% over the 20-day is
    # chasing whatever the trend says.
    "max_extension_pct": 0.04,
    # protective stop distance, in ATRs, floored by any stop in the rules file
    "atr_stop_mult": 2.0,
    # how far the market may drift above the planned price before the idea is
    # no longer the idea that was approved (validity.max_last)
    "max_drift_pct": 0.01,
    # how old the quote behind a re-evaluation may be, in minutes. Also the
    # unit the approve CLI multiplies to bound how stale a PLAN may be.
    "max_data_age_minutes": 60,
}


def params(rules: dict) -> dict:
    """`rules["strategy"]` merged over PARAMS. Never raises, never widens risk.

    An unparseable value falls back to the default rather than propagating a
    string into arithmetic. The ints stay ints (SMA windows index a list).
    """
    out = dict(PARAMS)
    cfg = rules.get("strategy") if isinstance(rules, dict) else None
    if not isinstance(cfg, dict):
        return out
    for key, default in PARAMS.items():
        if key not in cfg:
            continue
        raw = cfg.get(key)
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            out[key] = int(raw) if isinstance(default, int) else float(raw)
        except (TypeError, ValueError):
            continue
    return out


def round_to_tick(px: Any) -> float:
    """Nearest whole cent."""
    return round(round(float(px) / TICK) * TICK, 2)


def floor_to_tick(px: Any) -> float:
    """Whole cent AT OR BELOW px. Used wherever rounding up would cross a cap."""
    return round(math.floor(float(px) / TICK + 1e-9) * TICK, 2)


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def check_conditions(symbol: str, features: dict, rules: dict) -> dict:
    """Every named condition and whether it held. Optional in the contract.

    A missing feature makes its condition FALSE, never True: an unknown is not
    a pass. The keys are stable strings — the plan file prints the False ones
    as the reason a symbol produced nothing, and a human reads them.
    """
    p = params(rules)
    last = _num(features.get("last"))
    cap = _num(features.get("cap"))
    sma_fast = _num(features.get("sma20"))
    sma_slow = _num(features.get("sma50"))
    slope_fast = _num(features.get("sma20_slope"))
    slope_slow = _num(features.get("sma50_slope"))
    atr = _num(features.get("atr14"))
    dist = _num(features.get("dist_to_sma20_pct"))
    pos = _num(features.get("position_qty")) or 0.0

    band = float(p["max_extension_pct"])
    return {
        "last_known": last is not None,
        "atr_known": atr is not None and atr > 0,
        "cap_known": cap is not None,
        "last_at_or_under_cap": last is not None and cap is not None and last <= cap,
        "trend_stack_fast_over_slow": (
            sma_fast is not None and sma_slow is not None and sma_fast > sma_slow
        ),
        "fast_sma_rising": slope_fast is not None and slope_fast > 0,
        "slow_sma_rising": slope_slow is not None and slope_slow > 0,
        "at_or_above_fast_sma": dist is not None and dist >= 0,
        "inside_extension_band": dist is not None and dist <= band,
        "no_open_exposure": pos <= 0 and not bool(features.get("has_working_entry")),
    }


def evaluate(symbol: str, features: dict, rules: dict) -> dict | None:
    """The default trend-continuation idea. Returns a candidate, or None.

    Fires only when EVERY condition in check_conditions holds:

      * the live `last` is at or under the standing entry cap (the 2026-08-28
        no-chase law, applied at the idea stage rather than at the gate),
      * the 20-day SMA is above the 50-day SMA and BOTH are rising, measured
        as a per-day slope over 5 sessions,
      * `last` sits in a bounded band ABOVE the 20-day SMA — at or above it, so
        this is continuation and not a falling-knife bid, and no further above
        it than `max_extension_pct`, so it is not a chase,
      * nothing is already open on the symbol: no position, no working entry.

    Prices:
      limit = last, rounded to the tick, then floored to the cap. Never above.
      stop  = the WIDER-protecting of (rules entry stop, last - 2*ATR), i.e.
              max() — a rules stop is a floor under the ATR stop, never a
              ceiling on it — floored to the tick, and refused if it does not
              land strictly below the limit.

    Sizing is NOT computed here. See THE CONTRACT above.
    """
    checks = check_conditions(symbol, features, rules)
    if not all(checks.values()):
        return None

    p = params(rules)
    last = float(features["last"])
    cap = float(features["cap"])
    atr = float(features["atr14"])

    limit = min(round_to_tick(last), floor_to_tick(cap))
    atr_stop = last - float(p["atr_stop_mult"]) * atr
    rules_stop = _num(((rules.get("entries") or {}).get(symbol) or {}).get("stop"))
    stop = atr_stop if rules_stop is None else max(rules_stop, atr_stop)
    stop = floor_to_tick(stop)

    if not (stop > 0 and stop < limit):
        # Not a refusal the caller has to interpret: an idea whose stop cannot
        # sit under its limit is simply not an idea.
        return None

    return {
        "symbol": symbol,
        "limit": limit,
        "stop": stop,
        "qty_hint": None,
        "strategy": "default_trend_continuation_v1",
        "checks": checks,
        "rationale": (
            "{sym}: sma20 {f:.4f} > sma50 {s:.4f}, both rising "
            "({sf:+.4f}/{ss:+.4f} per day); last {l:.2f} is {d:+.2%} vs sma20, "
            "inside the {b:.2%} band and at/under the {c:.2f} cap; "
            "stop {st:.2f} = max(rules, last - {m:g}*ATR {a:.4f})."
        ).format(
            sym=symbol,
            f=float(features["sma20"]),
            s=float(features["sma50"]),
            sf=float(features["sma20_slope"]),
            ss=float(features["sma50_slope"]),
            l=last,
            d=float(features["dist_to_sma20_pct"]),
            b=float(p["max_extension_pct"]),
            c=cap,
            st=stop,
            m=float(p["atr_stop_mult"]),
            a=atr,
        ),
    }
