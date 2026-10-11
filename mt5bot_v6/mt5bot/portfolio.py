"""Multi-market daily portfolio backtester with ONE shared USD equity pool.

Same execution conventions as backtest.py (kept identical on purpose, and verified against it
in check_portfolio.py):
  * signals are computed on the CLOSE of bar j-1 and executed at the OPEN of bar j
  * data are BID prices; longs buy at ask (open + spread + slippage) and sell at bid;
    shorts sell at bid and buy back at ask
  * stops are checked intrabar against high/low; fills at the stop price (or at the open if it
    gapped through) plus slippage against us
  * if a stop fires inside a bar we do NOT re-enter at that bar's (stale) open  <- the bug fixed earlier
  * one position per market, risk_pct of CURRENT portfolio equity risked per position

Differences from the single-market engine (needed for a multi-currency portfolio):
  * account currency is USD for every market. P&L formulas:
        USD-quote pairs (EURUSD, GBPUSD, AUDUSD, NZDUSD, XAUUSD):  side * N * (exit/entry - 1)
        USD-base  pairs (USDJPY, USDCAD, USDCHF):                  side * N * (exit - entry) / exit
    where N is the position's notional in USD at entry.
  * sizing uses equity marked to market (cash + unrealised P&L), not just realised equity
  * optional financing drag (annual % of notional, accrued per calendar day while a position is held)
    as a crude stand-in for swap/rollover, which the data do not contain.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Market:
    name: str
    df: pd.DataFrame            # daily OHLC (bid), DatetimeIndex
    sig: dict                   # arrays aligned to df: long_entry, short_entry, long_exit, short_exit, stop_dist
    spread: float               # price units, paid once per round trip
    slippage: float             # price units, per fill, against us
    usd_base: bool = False      # True for USDJPY / USDCAD / USDCHF


@dataclass
class PConfig:
    initial_equity: float = 100_000.0
    risk_pct: float = 0.005           # fraction of equity risked per position
    max_gross_leverage: float = 10.0  # cap on total notional / equity (rarely binds)
    financing_rate: float = 0.0       # per year, on notional held (stress scenario only)


@dataclass
class PResult:
    equity: pd.Series
    trades: pd.DataFrame
    config: PConfig
    stats: dict = field(default_factory=dict)


def _pnl_usd(n: float, entry: float, exit_: float, side: int, usd_base: bool) -> float:
    if usd_base:
        return side * n * (exit_ - entry) / exit_
    return side * n * (exit_ / entry - 1.0)


def run_portfolio(markets: list[Market], cfg: PConfig) -> PResult:
    idx = markets[0].df.index
    for mk in markets[1:]:
        idx = idx.union(mk.df.index)
    idx = idx.sort_values()
    T, M = len(idx), len(markets)

    own = [mk.df.index.get_indexer(idx) for mk in markets]          # -1 where the market has no bar that day
    O = [mk.df["open"].to_numpy() for mk in markets]
    H = [mk.df["high"].to_numpy() for mk in markets]
    L = [mk.df["low"].to_numpy() for mk in markets]
    C = [mk.df["close"].to_numpy() for mk in markets]
    le = [np.asarray(mk.sig["long_entry"], bool) for mk in markets]
    se = [np.asarray(mk.sig["short_entry"], bool) for mk in markets]
    lx = [np.asarray(mk.sig["long_exit"], bool) for mk in markets]
    sx = [np.asarray(mk.sig["short_exit"], bool) for mk in markets]
    sd = [np.asarray(mk.sig["stop_dist"], float) for mk in markets]

    cash = cfg.initial_equity
    pos = [0] * M
    notional = [0.0] * M
    epx = [0.0] * M
    spx = [0.0] * M
    ebar = [0] * M
    etime = [None] * M
    riskc = [0.0] * M
    last_close = [np.nan] * M
    trades: list[dict] = []
    eq = np.full(T, np.nan)

    def mtm(m: int) -> float:
        if pos[m] == 0 or not np.isfinite(last_close[m]):
            return 0.0
        mk = markets[m]
        px = last_close[m] if pos[m] == 1 else last_close[m] + mk.spread   # shorts are marked at the ask
        return _pnl_usd(notional[m], epx[m], px, pos[m], mk.usd_base)

    def equity_now() -> float:
        return cash + sum(mtm(m) for m in range(M) if pos[m] != 0)

    def close_trade(m: int, i: int, px: float, reason: str) -> None:
        nonlocal cash
        mk = markets[m]
        pnl = _pnl_usd(notional[m], epx[m], px, pos[m], mk.usd_base)
        cash += pnl
        trades.append({
            "market": mk.name, "side": "long" if pos[m] == 1 else "short",
            "entry_time": etime[m], "exit_time": idx[i], "notional": notional[m],
            "entry": epx[m], "exit": px, "stop": spx[m], "pnl": pnl,
            "r": pnl / riskc[m] if riskc[m] else np.nan, "reason": reason, "bars": i - ebar[m],
        })
        pos[m] = 0
        notional[m] = 0.0

    for i in range(T):
        ts = idx[i]
        for m in range(M):
            j = own[m][i]
            if j < 0:
                continue                      # market closed / no data today
            mk = markets[m]
            o, h, l, c = O[m][j], H[m][j], L[m][j], C[m][j]
            if j >= 1:
                n_before = len(trades)
                if pos[m] == 1:
                    if o <= spx[m]:
                        close_trade(m, i, o - mk.slippage, "stop_gap")
                    elif l <= spx[m]:
                        close_trade(m, i, spx[m] - mk.slippage, "stop")
                    elif lx[m][j - 1]:
                        close_trade(m, i, o - mk.slippage, "signal")
                elif pos[m] == -1:
                    if o + mk.spread >= spx[m]:
                        close_trade(m, i, o + mk.spread + mk.slippage, "stop_gap")
                    elif h + mk.spread >= spx[m]:
                        close_trade(m, i, spx[m] + mk.slippage, "stop")
                    elif sx[m][j - 1]:
                        close_trade(m, i, o + mk.spread + mk.slippage, "signal")
                stopped_bar = len(trades) > n_before and trades[-1]["reason"] == "stop"

                if pos[m] == 0 and not stopped_bar and np.isfinite(sd[m][j - 1]) and sd[m][j - 1] > 0:
                    side = 1 if le[m][j - 1] else (-1 if se[m][j - 1] else 0)
                    if side != 0:
                        dist = sd[m][j - 1] + mk.spread + mk.slippage
                        eq_now = equity_now()
                        n_new = cfg.risk_pct * eq_now * o / dist
                        gross = sum(notional[k] for k in range(M) if pos[k] != 0)
                        n_new = min(n_new, max(0.0, cfg.max_gross_leverage * eq_now - gross))
                        if n_new > 1e-9 and eq_now > 0:
                            pos[m], notional[m], ebar[m], etime[m] = side, n_new, i, ts
                            riskc[m] = n_new * dist / o
                            if side == 1:
                                epx[m] = o + mk.spread + mk.slippage
                                spx[m] = o - sd[m][j - 1]
                                if l <= spx[m]:
                                    close_trade(m, i, spx[m] - mk.slippage, "stop")
                            else:
                                epx[m] = o - mk.slippage
                                spx[m] = o + sd[m][j - 1]
                                if h + mk.spread >= spx[m]:
                                    close_trade(m, i, spx[m] + mk.slippage, "stop")
            last_close[m] = c

        if cfg.financing_rate and i > 0:
            days = (ts - idx[i - 1]).days
            drag = sum(notional[m] for m in range(M) if pos[m] != 0) * cfg.financing_rate * days / 365.0
            cash -= drag
        eq[i] = equity_now()

    for m in range(M):                         # close whatever is still open at the last close
        if pos[m] != 0:
            mk = markets[m]
            j_last = int(np.max(np.nonzero(own[m] >= 0)[0]))
            c = last_close[m]
            px = c - mk.slippage if pos[m] == 1 else c + mk.spread + mk.slippage
            close_trade(m, j_last, px, "end")
    eq[-1] = cash if all(p == 0 for p in pos) else eq[-1]

    equity = pd.Series(eq, index=idx).ffill()
    tdf = pd.DataFrame(trades)
    res = PResult(equity, tdf, cfg)
    res.stats = portfolio_stats(res)
    return res


def sharpe_of(equity: pd.Series, start=None, end=None) -> float:
    e = equity.loc[start:end]
    r = e.pct_change().dropna()
    if len(r) < 20 or r.std() == 0:
        return float("nan")
    return float(r.mean() / r.std() * np.sqrt(252))


def portfolio_stats(res: PResult) -> dict:
    eq, t, init = res.equity, res.trades, res.config.initial_equity
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    end = float(eq.iloc[-1])
    out = {
        "end_equity": end,
        "return_pct": (end / init - 1) * 100,
        "cagr_pct": ((end / init) ** (1 / years) - 1) * 100 if end > 0 else -100.0,
        "max_drawdown_pct": float((eq / eq.cummax() - 1).min() * 100),
        "sharpe": sharpe_of(eq),
        "years": years,
        "trades": int(len(t)),
    }
    if len(t):
        w, lo = t.loc[t.pnl > 0, "pnl"], t.loc[t.pnl <= 0, "pnl"]
        out["profit_factor"] = float(w.sum() / abs(lo.sum())) if len(lo) and lo.sum() != 0 else float("inf")
        out["win_rate_pct"] = float(len(w) / len(t) * 100)
        out["avg_R"] = float(t["r"].mean())
    return out

