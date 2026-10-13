#!/usr/bin/env python3
"""Standalone live-vs-assumed spread check for the demo forward run.

    python check_spreads.py --dir "<path to MT5 Common/Files>"

Reads pa_snapshots.csv (hourly, written by PA_Forward.mq5) and, if present,
pa_signals.csv (per-signal). Prints per-symbol and per-hour-of-day tables and
a PASS/WARN/FAIL verdict per symbol.

Exit codes: 0 all PASS, 1 any WARN, 2 any FAIL, 3 no data.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

ASSUMED_SPREAD_PTS = {"EURUSD": 10, "GBPUSD": 13, "USDJPY": 10, "AUDUSD": 12}

RATIO_WARN = 1.25   # live median this much over assumed -> WARN
RATIO_FAIL = 1.50   # ... -> FAIL
MIN_SAMPLES = 30    # fewer live samples than this -> FAIL (not enough evidence either way)


def verdict(ratio, n):
    if n < MIN_SAMPLES or np.isnan(ratio):
        return "FAIL"
    if ratio >= RATIO_FAIL:
        return "FAIL"
    if ratio >= RATIO_WARN:
        return "WARN"
    return "PASS"


def load_snapshots(path):
    if not os.path.exists(path):
        return None
    sn = pd.read_csv(path)
    if len(sn) == 0:
        return None
    sn["ts"] = pd.to_datetime(sn["time_server"], errors="coerce")
    sn = sn.dropna(subset=["ts", "spread_pts"])
    sn["hour"] = sn["ts"].dt.hour
    return sn


def load_signals(path):
    if not os.path.exists(path):
        return None
    sig = pd.read_csv(path)
    if "spread_pts" not in sig.columns:
        return None
    sig = sig[sig.spread_pts > 0]
    return sig if len(sig) else None


def per_symbol(sn, sig, assumed):
    rows = []
    for s in sorted(assumed):
        n_snap = med_snap = p95_snap = max_snap = np.nan
        n_sig = med_sig = np.nan
        if sn is not None:
            g = sn[sn.symbol == s]
            if len(g):
                n_snap = len(g)
                med_snap = g.spread_pts.median()
                p95_snap = g.spread_pts.quantile(0.95)
                max_snap = g.spread_pts.max()
        if sig is not None:
            g = sig[sig.symbol == s]
            if len(g):
                n_sig = len(g)
                med_sig = g.spread_pts.median()
        med = med_snap if not np.isnan(med_snap) else med_sig
        ratio = (med / assumed[s]) if (not np.isnan(med) and assumed[s] > 0) else np.nan
        n_live = int((0 if np.isnan(n_snap) else n_snap) + (0 if np.isnan(n_sig) else n_sig))
        rows.append({
            "symbol": s, "assumed": assumed[s],
            "med_snap": med_snap, "p95_snap": p95_snap, "max_snap": max_snap,
            "med_sig": med_sig, "n_snap": int(0 if np.isnan(n_snap) else n_snap), "n_sig": int(0 if np.isnan(n_sig) else n_sig),
            "ratio_med": ratio, "verdict": verdict(ratio, n_live),
        })
    return pd.DataFrame(rows).set_index("symbol")


def per_hour(sn, assumed):
    if sn is None or len(sn) == 0:
        return None
    out = []
    for s in sorted(assumed):
        g = sn[sn.symbol == s]
        if len(g) == 0:
            continue
        h = g.groupby("hour").spread_pts.median().rename("med")
        h = h.to_frame()
        h["assumed"] = assumed[s]
        h["ratio"] = h["med"] / assumed[s]
        h["symbol"] = s
        out.append(h.reset_index())
    return pd.concat(out, ignore_index=True) if out else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    p = lambda f: os.path.join(a.dir, f)

    sn = load_snapshots(p("pa_snapshots.csv"))
    sig = load_signals(p("pa_signals.csv"))
    if sn is None and sig is None:
        sys.exit("no usable pa_snapshots.csv or pa_signals.csv in --dir (exit 3)")

    print("=== per symbol ===")
    tab = per_symbol(sn, sig, ASSUMED_SPREAD_PTS)
    print(tab.round(2).to_string())

    print("\n=== median spread by hour of day (server time) ===")
    ph = per_hour(sn, ASSUMED_SPREAD_PTS)
    if ph is not None and len(ph):
        pivot = ph.pivot_table(index="hour", columns="symbol", values="ratio", aggfunc="mean")
        print("ratio = live median / assumed, by hour:")
        print(pivot.round(2).to_string())
        worst = ph.loc[ph.groupby("symbol").ratio.idxmax()][["symbol", "hour", "med", "assumed", "ratio"]]
        print("\nworst hour per symbol:")
        print(worst.round(2).to_string(index=False))
    else:
        print("(no snapshots yet)")

    v = tab.verdict.value_counts().to_dict()
    print(f"\nverdict counts: {v}")
    if "FAIL" in v:
        sys.exit(2)
    if "WARN" in v:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()