"""Backtest + walk-forward check.

Usage:
  python run_backtest.py --synthetic                 # sanity test on random data
  python run_backtest.py --csv data/EURUSD_H1.csv    # real data
  python run_backtest.py --csv data/XAUUSD_H1.csv --instrument XAUUSD
"""
from __future__ import annotations

import argparse
import itertools

import numpy as np
import pandas as pd

from mt5bot.backtest import Config, Instrument, format_stats, run_backtest
from mt5bot.data import load_csv, resample, synthetic_prices
from mt5bot.strategies import donchian_breakout

INSTRUMENTS = {
    "EURUSD": Instrument("EURUSD", 100_000, 0.00012, 0.00002, 7.0),
    "GBPUSD": Instrument("GBPUSD", 100_000, 0.00015, 0.00002, 7.0),
    "XAUUSD": Instrument("XAUUSD", 100, 0.25, 0.05, 7.0),
}

GRID = {
    "entry_n": [20, 40, 55, 80],
    "exit_n": [10, 20],
    "atr_stop": [2.0, 3.0],
}


def evaluate(df, inst, cfg, **params):
    sig = donchian_breakout(df, **params)
    return run_backtest(df, sig, inst, cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--instrument", default="EURUSD")
    ap.add_argument("--timeframe", default=None, help="resample rule e.g. 1h, 4h")
    ap.add_argument("--train", type=float, default=0.6, help="fraction used for parameter search")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    inst = INSTRUMENTS[a.instrument]
    cfg = Config()
    if a.synthetic:
        df = synthetic_prices(seed=a.seed)
    elif a.csv:
        df = load_csv(a.csv)
    else:
        ap.error("give --csv FILE or --synthetic")
    if a.timeframe:
        df = resample(df, a.timeframe)

    split = int(len(df) * a.train)
    train, test = df.iloc[:split], df.iloc[split:]
    print(f"{len(df)} bars  {df.index[0]} -> {df.index[-1]}")
    print(f"train: {len(train)} bars | test (never seen during tuning): {len(test)} bars\n")

    # ---- parameter search on TRAIN only ----------------------------------------
    rows = []
    for combo in itertools.product(*GRID.values()):
        p = dict(zip(GRID.keys(), combo))
        if p["exit_n"] >= p["entry_n"]:
            continue
        r = evaluate(train, inst, cfg, **p)
        rows.append({**p, "ret%": r.stats["return_pct"], "dd%": r.stats["max_drawdown_pct"],
                     "trades": r.stats["trades"], "pf": r.stats.get("profit_factor", np.nan)})
    grid = pd.DataFrame(rows).sort_values("ret%", ascending=False)
    print("Top parameter sets on TRAIN data:")
    print(grid.head(5).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    pos = (grid["ret%"] > 0).mean() * 100
    print(f"\n{pos:.0f}% of parameter sets were profitable on train.")

    best = {k: (int(grid.iloc[0][k]) if k != "atr_stop" else float(grid.iloc[0][k])) for k in GRID}
    print(f"\nChosen params: {best}\n")

    r_tr = evaluate(train, inst, cfg, **best)
    r_te = evaluate(test, inst, cfg, **best)
    print("TRAIN (in-sample):");  print(format_stats(r_tr.stats))
    print("\nTEST (out-of-sample, the number that matters):"); print(format_stats(r_te.stats))
    print("\nOut-of-sample exit reasons:")
    if len(r_te.trades):
        print(r_te.trades["reason"].value_counts().to_string())


if __name__ == "__main__":
    main()
