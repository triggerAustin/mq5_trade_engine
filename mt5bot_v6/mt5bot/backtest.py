"""Cost-aware bar-by-bar backtester.

Conventions (kept deliberately conservative):
  * Signals are computed on the CLOSE of bar i and executed at the OPEN of bar i+1
    (no look-ahead).
  * Prices in the data are BID prices. Buying costs the spread on entry; shorts pay
    the spread when they are closed (buy back at ask).
  * Stop losses are checked intrabar. If the stop is hit, we fill at the stop price,
    or at the open if the bar gapped through it (worse for us). Slippage is added.
  * If a stop and a signal exit both occur on the same bar, the stop wins.
  * Position size = risk_pct of current equity / stop distance, rounded DOWN to
    lot_step. If that is below min_lot the trade is skipped (we never risk more
    than intended just to get a trade on).
  * Account currency is assumed to be the quote currency (USD for EURUSD,
    GBPUSD, XAUUSD, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Instrument:
    name: str = "EURUSD"
    contract_size: float = 100_000      # units per 1.0 lot (XAUUSD = 100 oz)
    spread: float = 0.00012             # in price units (1.2 pips for EURUSD)
    slippage: float = 0.00002           # per fill, price units, applied against us
    commission_per_lot: float = 7.0     # USD per lot, ROUND TURN (0 if built into spread)
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 50.0


@dataclass
class Config:
    initial_equity: float = 1000.0
    risk_pct: float = 0.01              # fraction of equity risked per trade
    max_leverage: float = 30.0          # cap notional / equity
    daily_loss_limit: float | None = 0.03   # stop opening trades for the day after -3%
    max_drawdown_kill: float | None = 0.25  # stop trading entirely after -25% from peak


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.Series
    config: Config
    instrument: Instrument
    stats: dict = field(default_factory=dict)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def run_backtest(df: pd.DataFrame, signals: dict, inst: Instrument, cfg: Config) -> Result:
    """Run the backtest.

    signals: dict of equal-length arrays aligned to df
        'long_entry', 'short_entry', 'long_exit', 'short_exit': bool
        'stop_dist': float, stop distance in price units at signal time (NaN = no trade)
    """
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); c = df["close"].to_numpy()
    idx = df.index
    n = len(df)

    le = np.asarray(signals["long_entry"], bool); se = np.asarray(signals["short_entry"], bool)
    lx = np.asarray(signals["long_exit"], bool); sx = np.asarray(signals["short_exit"], bool)
    sd = np.asarray(signals["stop_dist"], float)

    equity = cfg.initial_equity
    peak = equity
    killed = False
    day_start_equity = equity
    cur_day = idx[0].date()

    pos = 0            # +1 long, -1 short, 0 flat
    lots = 0.0
    entry_px = 0.0     # effective entry price incl. spread/slippage
    stop_px = 0.0
    entry_i = 0
    risk_cash = 0.0
    trades = []
    eq_curve = np.full(n, np.nan)

    def close_trade(i, exit_px, reason):
        nonlocal equity, pos, lots
        pnl_px = (exit_px - entry_px) if pos == 1 else (entry_px - exit_px)
        gross = pnl_px * lots * inst.contract_size
        comm = inst.commission_per_lot * lots
        net = gross - comm
        equity += net
        trades.append({
            "entry_time": idx[entry_i], "exit_time": idx[i], "side": "long" if pos == 1 else "short",
            "lots": lots, "entry": entry_px, "exit": exit_px, "stop": stop_px,
            "pnl": net, "r": net / risk_cash if risk_cash else np.nan, "reason": reason,
            "bars": i - entry_i,
        })
        pos = 0; lots = 0.0

    for i in range(1, n):
        d = idx[i].date()
        if d != cur_day:
            cur_day = d
            day_start_equity = equity

        # ---- 1. manage open position on this bar --------------------------------
        n_before = len(trades)
        if pos != 0:
            if pos == 1:
                # long exits at bid
                if o[i] <= stop_px:
                    close_trade(i, o[i] - inst.slippage, "stop_gap")
                elif l[i] <= stop_px:
                    close_trade(i, stop_px - inst.slippage, "stop")
                elif lx[i - 1]:
                    close_trade(i, o[i] - inst.slippage, "signal")
            else:
                # short exits at ask = bid + spread
                if o[i] + inst.spread >= stop_px:
                    close_trade(i, o[i] + inst.spread + inst.slippage, "stop_gap")
                elif h[i] + inst.spread >= stop_px:
                    close_trade(i, stop_px + inst.slippage, "stop")
                elif sx[i - 1]:
                    close_trade(i, o[i] + inst.spread + inst.slippage, "signal")

        # A stop that fires MID-bar means the market has already moved away from this bar's open,
        # so we must not re-enter at that stale open price (that would be trading in the past).
        # We wait and use the next bar's open instead.
        stopped_bar = len(trades) > n_before and trades[-1]["reason"] == "stop"

        # ---- 2. risk switches ---------------------------------------------------
        peak = max(peak, equity)
        if cfg.max_drawdown_kill is not None and equity < peak * (1 - cfg.max_drawdown_kill):
            killed = True
        day_blocked = cfg.daily_loss_limit is not None and equity < day_start_equity * (1 - cfg.daily_loss_limit)

        # ---- 3. open new position from previous bar's signal --------------------
        if pos == 0 and not killed and not day_blocked and not stopped_bar and np.isfinite(sd[i - 1]) and sd[i - 1] > 0:
            side = 1 if le[i - 1] else (-1 if se[i - 1] else 0)
            if side != 0:
                dist = sd[i - 1] + inst.spread + inst.slippage  # real stop distance incl. costs
                risk_amt = cfg.risk_pct * equity
                raw = risk_amt / (dist * inst.contract_size)
                raw = min(raw, cfg.max_leverage * equity / (o[i] * inst.contract_size), inst.max_lot)
                q = np.floor(raw / inst.lot_step + 1e-9) * inst.lot_step
                if q >= inst.min_lot:
                    pos = side; lots = round(q, 8); entry_i = i; risk_cash = lots * dist * inst.contract_size
                    if side == 1:
                        entry_px = o[i] + inst.spread + inst.slippage    # buy at ask
                        stop_px = o[i] - sd[i - 1]                        # triggers on bid <= stop
                    else:
                        entry_px = o[i] - inst.slippage                   # sell at bid
                        stop_px = o[i] + sd[i - 1]                        # compared against ask below

        # ---- 4. same-bar stop check for a just-opened position ------------------
        if pos != 0 and entry_i == i:
            if pos == 1 and l[i] <= stop_px:
                close_trade(i, stop_px - inst.slippage, "stop")
            elif pos == -1 and h[i] + inst.spread >= stop_px:
                close_trade(i, stop_px + inst.slippage, "stop")

        # ---- 5. mark to market --------------------------------------------------
        if pos == 0:
            eq_curve[i] = equity
        elif pos == 1:
            eq_curve[i] = equity + (c[i] - entry_px) * lots * inst.contract_size
        else:
            eq_curve[i] = equity + (entry_px - (c[i] + inst.spread)) * lots * inst.contract_size

    if pos != 0:  # close at the last close
        px = c[-1] - inst.slippage if pos == 1 else c[-1] + inst.spread + inst.slippage
        close_trade(n - 1, px, "end")
        eq_curve[-1] = equity

    eq = pd.Series(eq_curve, index=idx).ffill().fillna(cfg.initial_equity)
    tdf = pd.DataFrame(trades)
    res = Result(tdf, eq, cfg, inst)
    res.stats = metrics(res)
    return res


def metrics(res: Result) -> dict:
    eq, t = res.equity, res.trades
    days = max((eq.index[-1] - eq.index[0]).days, 1)
    years = days / 365.25
    start, end = res.config.initial_equity, float(eq.iloc[-1])
    dd = (eq / eq.cummax() - 1).min()
    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if len(daily) > 2 and daily.std() > 0 else np.nan
    out = {
        "start_equity": start, "end_equity": end,
        "return_pct": (end / start - 1) * 100,
        "cagr_pct": ((end / start) ** (1 / years) - 1) * 100 if end > 0 else -100.0,
        "max_drawdown_pct": dd * 100,
        "sharpe": sharpe,
        "years": years,
        "trades": int(len(t)),
    }
    if len(t):
        wins, losses = t.loc[t.pnl > 0, "pnl"], t.loc[t.pnl <= 0, "pnl"]
        out.update({
            "win_rate_pct": len(wins) / len(t) * 100,
            "profit_factor": wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf,
            "avg_R": t["r"].mean(),
            "avg_win": wins.mean() if len(wins) else 0.0,
            "avg_loss": losses.mean() if len(losses) else 0.0,
            "avg_bars_held": t["bars"].mean(),
        })
    return out


def format_stats(s: dict) -> str:
    lines = []
    for k, v in s.items():
        lines.append(f"  {k:<18} {v:>12.2f}" if isinstance(v, (float, np.floating)) else f"  {k:<18} {v:>12}")
    return "\n".join(lines)

