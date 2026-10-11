#!/usr/bin/env python3
"""PRE-REGISTERED multi-market daily trend-following test.  python run_portfolio_test.py

The specification below was fixed BEFORE any multi-market data was looked at. Do not edit it after
seeing results - if you want to explore variants, add them to the clearly-labelled post-hoc section.

PRIMARY SPEC
  markets   : EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD XAUUSD  (daily bars on the 17:00 New York FX roll, v6 data)
  signal    : Donchian breakout, enter on a close beyond the prior 55-day high/low (long and short),
              exit on a close beyond the prior 20-day opposite extreme, ATR(14) x 3.0 stop
  execution : next bar's open; costs below; one position per market
  sizing    : 0.5% of portfolio equity risked per position (stop distance), shared equity pool
  costs     : "realistic" = typical modern retail spread + 10% slippage per fill
              "harsh"     = 2x spread and slippage + 2%/yr financing drag on notional (stand-in for swap)
PASS RULE (all three must hold)
  1. realistic-cost full-period Sharpe >= 0.50
  2. realistic-cost Sharpe >= 0.20 in EACH half (2003-2014 and 2015-2026)
  3. harsh-cost full-period Sharpe >= 0.30
"""
from __future__ import annotations
import argparse, os, sys
import numpy as np, pandas as pd
from mt5bot.portfolio import Market, PConfig, run_portfolio, sharpe_of
from mt5bot.data import validate_daily
from mt5bot.strategies import donchian_breakout

# name: (spread, slippage, usd_base)   prices in quote units; spread is paid once per round trip
COSTS = {
    "EURUSD": (0.00010, 0.00001, False), "GBPUSD": (0.00013, 0.00001, False),
    "USDJPY": (0.010, 0.001, True),      "AUDUSD": (0.00012, 0.00001, False),
    "USDCAD": (0.00015, 0.00002, True),  "USDCHF": (0.00015, 0.00002, True),
    "NZDUSD": (0.00015, 0.00002, False), "XAUUSD": (0.30, 0.05, False),
}
HALF_SPLIT = "2014-12-31"


def load(data_dir: str) -> dict:
    out = {}
    for name in COSTS:
        p = os.path.join(data_dir, f"{name}_D1.csv")
        if os.path.exists(p):
            d = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
            if not d.index.is_monotonic_increasing or d.index[-1] > pd.Timestamp.now() + pd.Timedelta(days=2):
                sys.exit(f"{name}: dates look wrong - refusing to run")
            issues = validate_daily(d, name)
            if issues:
                sys.exit("DATA PROBLEM - refusing to run:\n  " + "\n  ".join(issues) +
                         "\nRebuild the daily files with:  python download_universe.py   (v6 to_daily)")
            out[name] = d
        else:
            print(f"WARNING: {p} not found - {name} skipped")
    return out


def build(data: dict, entry_n=55, exit_n=20, atr_stop=3.0, cost_mult=1.0):
    mk = []
    for name, d in data.items():
        sp, sl, ub = COSTS[name]
        mk.append(Market(name, d, donchian_breakout(d, entry_n, exit_n, 14, atr_stop), sp * cost_mult, sl * cost_mult, ub))
    return mk


def describe(label, r):
    s = r.stats
    print(f"{label:34s} Sharpe {s['sharpe']:+.2f} | CAGR {s['cagr_pct']:+.1f}% | maxDD {s['max_drawdown_pct']:.1f}% | "
          f"trades {s['trades']} | PF {s.get('profit_factor', float('nan')):.2f} | avg R {s.get('avg_R', float('nan')):+.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/universe_daily")
    ap.add_argument("--risk", type=float, default=0.005)
    a = ap.parse_args()
    data = load(a.data_dir)
    if not data:
        sys.exit("no data files found")
    print(f"markets: {', '.join(data)}")
    if len(data) < len(COSTS):
        print(f"NOTE: the pre-registered universe has {len(COSTS)} markets; with only {len(data)} the verdict below is NOT the official one.")
    print(f"period : {min(d.index[0] for d in data.values()).date()} -> {max(d.index[-1] for d in data.values()).date()}\n")

    cfg_real = PConfig(initial_equity=100_000, risk_pct=a.risk)
    cfg_harsh = PConfig(initial_equity=100_000, risk_pct=a.risk, financing_rate=0.02)
    real = run_portfolio(build(data), cfg_real)
    harsh = run_portfolio(build(data, cost_mult=2.0), cfg_harsh)

    print("=== PRIMARY SPEC (pre-registered) ===")
    describe("realistic costs, 2003-2026", real)
    describe("harsh costs + financing, 2003-2026", harsh)
    s_full = real.stats["sharpe"]
    s1, s2 = sharpe_of(real.equity, None, HALF_SPLIT), sharpe_of(real.equity, "2015-01-01", None)
    s_h = harsh.stats["sharpe"]
    print(f"realistic Sharpe by half: 2003-2014 {s1:+.2f} | 2015-2026 {s2:+.2f}")

    yr = real.equity.resample("YE").last().pct_change() * 100
    yr.iloc[0] = (real.equity.resample("YE").last().iloc[0] / cfg_real.initial_equity - 1) * 100
    print("\nreturn by year (%):", {int(i.year): round(v, 1) for i, v in yr.items()})

    t = real.trades
    if len(t):
        g = t.groupby("market").agg(trades=("pnl", "size"), pnl_usd=("pnl", "sum"), avg_R=("r", "mean"),
                                    win_pct=("pnl", lambda x: 100 * (x > 0).mean()))
        print("\nper-market contribution (realistic):"); print(g.round(2).to_string())
        top = g.pnl_usd.sort_values(ascending=False)
        total = t.pnl.sum()
        if total > 0:
            print(f"share of total profit from the single best market: {100 * top.iloc[0] / total:.0f}% ({top.index[0]})")
        else:
            print(f"total P&L is not positive, so no profit to attribute (best single market: {top.index[0]})")

    ok1, ok2, ok3 = s_full >= 0.50, (s1 >= 0.20 and s2 >= 0.20), s_h >= 0.30
    print("\n=== PRE-REGISTERED VERDICT ===")
    print(f"1. realistic full-period Sharpe >= 0.50 : {s_full:+.2f}  {'ok' if ok1 else 'NO'}")
    print(f"2. Sharpe >= 0.20 in each half          : {s1:+.2f} / {s2:+.2f}  {'ok' if ok2 else 'NO'}")
    print(f"3. harsh-cost Sharpe >= 0.30            : {s_h:+.2f}  {'ok' if ok3 else 'NO'}")
    print("RESULT:", "PASS" if (ok1 and ok2 and ok3) else "FAIL")

    print("\n=== POST-HOC ROBUSTNESS (NOT used for the verdict; for information only) ===")
    print("realistic costs, Sharpe full / 2003-2014 / 2015-2026:")
    for en, ex in ((20, 10), (40, 20), (55, 20), (80, 40), (100, 50)):
        r = run_portfolio(build(data, en, ex), cfg_real)
        print(f"  Donchian {en}/{ex}, stop x3: {r.stats['sharpe']:+.2f} / {sharpe_of(r.equity, None, HALF_SPLIT):+.2f} / "
              f"{sharpe_of(r.equity, '2015-01-01', None):+.2f}   maxDD {r.stats['max_drawdown_pct']:.0f}%")

    real.equity.to_csv("portfolio_equity.csv"); real.trades.to_csv("portfolio_trades.csv", index=False)
    print("\nsaved portfolio_equity.csv and portfolio_trades.csv")


if __name__ == "__main__":
    main()

