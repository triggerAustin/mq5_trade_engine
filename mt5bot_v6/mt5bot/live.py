"""Live-style daily signal logic (Phase A: no broker connection).

Design rules
  * ONE source of truth for signals: mt5bot.strategies.donchian_breakout, the same function the
    backtests use. This module only decides what to do at the NEXT open from CLOSED bars.
  * decide() never sees anything but bars that have closed (the caller must drop the partial bar).
  * Indicators are computed on the last WINDOW bars. ATR is an exponential average whose memory is
    ~(13/14)^800 ~ 1e-26 at that length, so this equals the full-history value to float precision
    (check_live.py proves it), and it keeps the daily run fast.
  * Stops are ALWAYS placed at the broker as real stop orders, never only inside this script.
  * The signal spec below is the pre-registered primary spec. Its backtest FAILED (see HANDOFF.md
    section 9.2); it is used here as a test harness for the execution plumbing, not as a proven edge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategies import donchian_breakout

SPEC = dict(entry_n=55, exit_n=20, atr_n=14, atr_stop=3.0)
WINDOW = 800

# contract size (units per 1.0 lot), whether the pair is USD-base, default lot limits.
# Lot limits and contract sizes are broker-specific: confirm them in the MT5 symbol specification.
MARKET_SPECS = {
    "EURUSD": dict(contract=100_000, usd_base=False), "GBPUSD": dict(contract=100_000, usd_base=False),
    "AUDUSD": dict(contract=100_000, usd_base=False), "NZDUSD": dict(contract=100_000, usd_base=False),
    "USDJPY": dict(contract=100_000, usd_base=True),  "USDCAD": dict(contract=100_000, usd_base=True),
    "USDCHF": dict(contract=100_000, usd_base=True),  "XAUUSD": dict(contract=100, usd_base=False),
}


@dataclass
class Position:
    side: int            # +1 long, -1 short
    entry: float         # effective entry price (what you were filled at)
    stop: float          # broker stop-loss price
    lots: float = 0.0
    opened: str = ""     # label of the bar the trade was opened on


@dataclass
class Decision:
    asof: pd.Timestamp   # label of the last CLOSED bar the decision is based on
    close_position: bool # exit signal for the open position (act at the next open)
    entry_side: int      # side signalled for the next open: +1, -1 or 0 (applies if flat at that open)
    stop_dist: float     # stop distance in price units (NaN if none)
    note: str


def closed_bars(d: pd.DataFrame, now_utc: pd.Timestamp | None = None) -> pd.DataFrame:
    """Drop the bar that is still forming. A bar is labelled with the date on which it closes
    (17:00 New York), so a bar is complete only once the 17:00-NY-shifted clock has passed its label."""
    now = pd.Timestamp.now(tz="UTC") if now_utc is None else pd.Timestamp(now_utc)
    now = now.tz_localize("UTC") if now.tzinfo is None else now
    ny_wall = now.tz_convert("America/New_York").tz_localize(None)
    current_label = (ny_wall + pd.Timedelta(hours=7)).normalize()   # label of the bar now forming
    return d[d.index < current_label]


def decide(df_closed: pd.DataFrame, pos: Position | None, spec: dict = SPEC) -> Decision:
    """What to do at the next open, given only closed bars and the current position (or None)."""
    w = df_closed.iloc[-WINDOW:]
    s = donchian_breakout(w, **spec)
    le, se, lx, sx = (bool(s[k][-1]) for k in ("long_entry", "short_entry", "long_exit", "short_exit"))
    sd = float(s["stop_dist"][-1])
    close = pos is not None and ((pos.side == 1 and lx) or (pos.side == -1 and sx))
    side = 1 if le else (-1 if se else 0)
    if not (math.isfinite(sd) and sd > 0):
        side, sd = 0, float("nan")
    parts = []
    if close:
        parts.append("exit signal")
    if side:
        parts.append(f"{'long' if side == 1 else 'short'} entry signal")
    return Decision(df_closed.index[-1], close, side, sd, ", ".join(parts) or "no signal")


def stop_hit(pos: Position, bar: pd.Series, spread: float) -> bool:
    """Was the broker stop touched during this closed bar? (long: bid low; short: ask = high + spread)"""
    return bar["low"] <= pos.stop if pos.side == 1 else bar["high"] + spread >= pos.stop


def lots_for(market: str, equity: float, risk_pct: float, stop_dist: float, price: float,
             spread: float = 0.0, slippage: float = 0.0, min_lot: float = 0.01, lot_step: float = 0.01,
             max_lot: float = 50.0) -> tuple[float, float]:
    """(lots, actual_risk_cash). Rounds DOWN; returns 0 lots if even the minimum lot would risk more
    than intended (we never over-risk just to get a trade on, same rule as the backtest)."""
    spec = MARKET_SPECS[market]
    dist = stop_dist + spread + slippage
    per_lot = dist * spec["contract"] / (price if spec["usd_base"] else 1.0)   # USD lost per 1.0 lot at the stop
    if per_lot <= 0:
        return 0.0, 0.0
    raw = min(risk_pct * equity / per_lot, max_lot)
    q = math.floor(raw / lot_step + 1e-9) * lot_step
    if q < min_lot:
        return 0.0, min_lot * per_lot       # second value: what the minimum lot WOULD risk
    return round(q, 8), q * per_lot
