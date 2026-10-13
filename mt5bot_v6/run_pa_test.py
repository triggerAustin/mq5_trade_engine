#!/usr/bin/env python3
"""PRE-REGISTERED test #6 (PREREGISTRATION_6_LOCKED.md): price-action trend + pullback + signal candle on H4.
    python run_pa_test.py
Needs hourly files in data/: EURUSD_H1_old.csv + EURUSD_H1.csv, GBPUSD_H1.csv, USDJPY_H1.csv, AUDUSD_H1.csv
(columns time,open,high,low,close,volume; time = UTC open time of the hour).
Gate = $10,000 simulation; $500 run = feasibility. Stage B (2019-01-01 on) only with --stage-b, only if the Stage A gate passed,
and only once (lock file data/STAGE_B6_DONE)."""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

from mt5bot.priceaction import PACfg, pa_stats, run_pa, to_h4
from mt5bot.pullback import Pair

# name: (spread, slippage, usd_base, swap_long_pts, swap_short_pts, tick_value)   same table as test #4
FX = {"EURUSD": (0.00010, 0.00001, False, -0.7, -1.0, 1.0), "GBPUSD": (0.00013, 0.00001, False, -0.2, -2.2, 1.0),
      "USDJPY": (0.010, 0.001, True, -0.1, -0.6, 0.63164), "AUDUSD": (0.00012, 0.00001, False, 6.3, -14.8, 1.0)}
A_END, B_START, LOCK = "2018-12-31", "2019-01-01", "data/STAGE_B6_DONE"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_pairs(data_dir, lo=None, hi=None):
    out = []
    for n, (sp, sl, ub, swl, sws, tv) in FX.items():
        paths = [os.path.join(data_dir, f"{n}_H1_old.csv"), os.path.join(data_dir, f"{n}_H1.csv")]
        found = [p for p in paths if os.path.exists(p)]
        if not found:
            sys.exit(f"no hourly file for {n} in {data_dir} (looked for {paths})")
        h1 = pd.concat([pd.read_csv(p, index_col=0, parse_dates=True) for p in found]).sort_index()
        h1 = h1[~h1.index.duplicated(keep="last")][["open", "high", "low", "close"]]
        h4 = to_h4(h1).loc[lo:hi]
        bad = int(((h4.high < h4[["open", "close"]].max(axis=1) - 1e-9) | (h4.low > h4[["open", "close"]].min(axis=1) + 1e-9)).sum())
        log(f"  {n}: {len(h1):,} hourly candles -> {len(h4):,} H4 candles, {h4.index[0]} -> {h4.index[-1]}"
            f"{'  WARNING: ' + str(bad) + ' inconsistent candles' if bad else ''}")
        out.append(Pair(n, h4, ub, sp, sl, swl, sws, tv))
    return out


def cfg(harsh, equity0=10_000.0):
    return PACfg(equity0=equity0, cost_mult=2.0 if harsh else 1.0, swap_mult=2.0 if harsh else 1.0, swap_credit=not harsh)


def show(label, res):
    s = pa_stats(res)
    log(f"{label}: trades {s['trades']} (skipped: min-lot {s['skipped_min_lot']}, slots {s['skipped_slots']}, beyond-stop {s['skipped_stop']}) | "
        f"mean R {s.get('mean_R', float('nan')):+.3f} (95% low {s.get('mean_R_lb95', float('nan')):+.3f}) | "
        f"PF {s.get('profit_factor', float('nan')):.2f} | win {s.get('win_rate', float('nan')) * 100:.0f}% | "
        f"maxDD {abs(s['max_dd_pct']):.1f}% | end ${s['end_equity']:,.0f} | Sharpe {s['sharpe']:+.2f} | "
        f"costs ${res.cost_usd:,.0f} swap ${res.swap_usd:,.0f}{' | HALTED ' + str(res.halted_on) if res.halted_on is not None else ''}")
    return s


def gate(real, sr, sh):
    tr = real.trades
    if len(tr) == 0:
        return {"no trades at all": False}
    mid = real.equity.index[len(real.equity) // 2]
    h1, h2 = tr[tr.entry_date <= mid].R.mean(), tr[tr.entry_date > mid].R.mean()
    pp = tr.groupby("pair").pnl_usd.sum()
    return {"1 at least 200 trades": sr["trades"] >= 200,
            "2 mean R >= +0.10 and 95% low > -0.05": sr.get("mean_R", -9) >= 0.10 and sr.get("mean_R_lb95", -9) > -0.05,
            "3 profit factor >= 1.20": sr.get("profit_factor", 0) >= 1.20,
            "4 maxDD <= 20% and no halt": abs(sr["max_dd_pct"]) <= 20 and real.halted_on is None,
            "5 harsh mean R >= 0": sh.get("mean_R", -9) >= 0,
            f"6 both halves mean R > 0 ({h1:+.3f}, {h2:+.3f})": bool(h1 > 0 and h2 > 0),
            "7 no pair > 40% of profit": bool(pp.sum() > 0 and pp.max() / pp.sum() <= 0.40)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--stage-b", action="store_true")
    a = ap.parse_args()
    log("loading hourly data and building H4 candles")
    A = load_pairs(a.data_dir, None, A_END)
    log(f"Stage A: up to {A_END}")
    real = run_pa(A, cfg(False), log=log)
    harsh = run_pa(A, cfg(True), log=log)
    sr = show("Stage A $10k realistic", real)
    sh = show("Stage A $10k harsh    ", harsh)
    tr = real.trades
    if len(tr):
        log("by pair  (n, mean R): " + ", ".join(f"{k}: {len(g)}, {g.R.mean():+.3f}" for k, g in tr.groupby("pair")))
        log("by pattern (n, mean R): " + ", ".join(f"{k}: {len(g)}, {g.R.mean():+.3f}" for k, g in tr.groupby("pat")))
        log("by direction (n, mean R): " + ", ".join(f"{'long' if k > 0 else 'short'}: {len(g)}, {g.R.mean():+.3f}" for k, g in tr.groupby("dir")))
        log("exits: " + str(tr.reason.value_counts().to_dict()))
        pp = tr.groupby("pair").pnl_usd.sum()
        log("pair P&L ($): " + ", ".join(f"{k}: {v:,.0f}" for k, v in pp.items()))
        daily = real.equity.ffill().resample("1D").last().dropna()
        yr = daily.groupby(daily.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
        log("yearly returns: " + ", ".join(f"{y}: {r * 100:+.1f}%" for y, r in yr.items()))
    show("Stage A $500 realistic (feasibility)", run_pa(A, cfg(False, 500.0), log=log))
    g = gate(real, sr, sh)
    for k, v in g.items():
        log(f"  gate {k}: {'PASS' if v else 'FAIL'}")
    passed = all(g.values())
    log(f"STAGE A GATE: {'PASSED' if passed else 'FAILED'}")
    if not a.stage_b:
        log("Stage B not run.")
        return 0
    if not passed:
        log("Stage A failed - Stage B stays sealed.")
        return 0
    if os.path.exists(LOCK):
        sys.exit("Stage B was already run once; it cannot be rerun.")
    open(LOCK, "w").write(time.ctime())
    B = load_pairs(a.data_dir, "2018-01-01", None)            # 2018 is indicator warm-up only; results counted from 2019
    for lab, hs in (("realistic", False), ("harsh", True)):
        r = run_pa(B, cfg(hs), log=log)
        t = r.trades[r.trades.entry_date >= B_START]
        e = r.equity.loc[B_START:]
        log(f"Stage B {lab}: trades {len(t)}, mean R {t.R.mean():+.3f}, maxDD {abs((e / e.cummax() - 1).min()) * 100:.1f}%, "
            f"end/start {e.iloc[-1] / e.iloc[0]:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
