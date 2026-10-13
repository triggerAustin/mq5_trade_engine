#!/usr/bin/env python3
"""POST-HOC, INFORMATION ONLY (test #6). The locked Stage A result is FAILED and stays FAILED whatever this prints.

The pre-registered 20% drawdown halt ended trading on 2004-04-07, so the locked Stage A saw only ~10 months. This script reruns the
SAME rules on the SAME Stage A window (data up to 2018-12-31 only; 2019 onward stays sealed) with the halt switched off, to show whether
the weak result was an unlucky start or a property of the rules. Nothing here is used for the pass/fail decision.
    python run_pa_posthoc.py
"""
from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np

from mt5bot.priceaction import pa_stats, run_pa
from run_pa_test import A_END, cfg, load_pairs, log, show


def main():
    log("POST-HOC (information only): Stage A window, drawdown halt switched off, 2019 onward NOT loaded")
    A = load_pairs("data", None, A_END)
    runs = {}
    for lab, harsh in (("realistic", False), ("harsh", True)):
        c = replace(cfg(harsh), dd_stop=0.99)
        runs[lab] = run_pa(A, c, log=log)
        show(f"[post-hoc] $10k {lab}, no halt", runs[lab])
    tr = runs["realistic"].trades
    if len(tr):
        log("by pair  (n, mean R): " + ", ".join(f"{k}: {len(g)}, {g.R.mean():+.3f}" for k, g in tr.groupby("pair")))
        log("by pattern (n, mean R): " + ", ".join(f"{k}: {len(g)}, {g.R.mean():+.3f}" for k, g in tr.groupby("pat")))
        log("by direction (n, mean R): " + ", ".join(f"{'long' if k > 0 else 'short'}: {len(g)}, {g.R.mean():+.3f}" for k, g in tr.groupby("dir")))
        log("exits: " + str(tr.reason.value_counts().to_dict()))
        by_year = tr.groupby(tr.exit_date.dt.year).R.agg(["count", "mean"])
        log("trades and mean R by exit year: " + ", ".join(f"{y}: {int(r['count'])}, {r['mean']:+.2f}" for y, r in by_year.iterrows()))
        mid = tr.exit_date.sort_values().iloc[len(tr) // 2]
        log(f"first-half mean R {tr[tr.exit_date <= mid].R.mean():+.3f}, second-half mean R {tr[tr.exit_date > mid].R.mean():+.3f}")
        daily = runs["realistic"].equity.ffill().resample("1D").last().dropna()
        yr = daily.groupby(daily.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
        log("yearly returns: " + ", ".join(f"{y}: {r * 100:+.1f}%" for y, r in yr.items()))
    log("Reminder: the locked Stage A gate result (FAILED) and the sealed Stage B are unchanged by this run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
