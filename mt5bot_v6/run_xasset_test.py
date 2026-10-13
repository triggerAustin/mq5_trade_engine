#!/usr/bin/env python3
"""PRE-REGISTERED cross-asset trend test #3 (see PREREGISTRATION_cross_asset.md).  python run_xasset_test.py
Stage A (to 2021-12-31) runs freely. Stage B (2022-01-01 on) runs ONCE, only if the Stage A gate passes; a lock file
data/STAGE_B_DONE records that it has been used. No parameters are tuned here.
Needs: data/proxies_d1/*.csv (ETFs) and data/universe_daily/<PAIR>_D1.csv (FX daily, 22:00 UTC cut)."""
from __future__ import annotations
import argparse, os, sys, time
import numpy as np, pandas as pd
from mt5bot.xasset import Asset, XConfig, run_xasset, sharpe, xstats

ETF = {"equity": ["SPY", "EFA", "EEM"], "bond": ["TLT", "IEF", "LQD"], "commodity": ["GLD", "DBC", "USO"]}
ETF_BPS = {"SPY": 2, "EFA": 2, "TLT": 2, "IEF": 2, "LQD": 2, "GLD": 2, "EEM": 6, "DBC": 6, "USO": 6}
FX = {"EURUSD": (0.00010, 0.00001, False), "GBPUSD": (0.00013, 0.00001, False), "USDJPY": (0.010, 0.001, True),
      "AUDUSD": (0.00012, 0.00001, False), "USDCAD": (0.00015, 0.00002, True), "USDCHF": (0.00015, 0.00002, True),
      "NZDUSD": (0.00015, 0.00002, False)}
STAGE_A_END, LOCK = "2021-12-31", "data/STAGE_B_DONE"


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_assets(proxy_dir, fx_dir):
    out = []
    for cls, names in ETF.items():
        for n in names:
            d = pd.read_csv(os.path.join(proxy_dir, f"{n}.csv"), index_col=0, parse_dates=True).sort_index()
            f = d["adj_close"] / d["close"]                       # total-return adjustment applied to open and close
            out.append(Asset(n, cls, pd.DataFrame({"open": d["open"] * f, "close": d["close"] * f}), ETF_BPS[n] / 1e4))
    for n, (sp, sl, ub) in FX.items():
        p = os.path.join(fx_dir, f"{n}_D1.csv")
        if not os.path.exists(p):
            sys.exit(f"{p} missing - the pre-registered universe needs it")
        d = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
        d.index = (d.index + pd.Timedelta(hours=2)).normalize()
        d = d[~d.index.duplicated(keep="last")]
        o, c = d["open"], d["close"]
        if ub:
            o, c = 1.0 / o, 1.0 / c                                # USD-quote orientation
        out.append(Asset(n, "fx", pd.DataFrame({"open": o, "close": c}), (sp / 2 + sl) / float(d["close"].median())))
    return out


def window(assets, lo, hi):
    return [Asset(a.name, a.cls, a.df.loc[lo:hi], a.cost_side) for a in assets]


def start_after_252(assets):
    # an instrument enters 252 trading days after its first bar: the engine's 252d lookback enforces this
    return assets


def gate(res_real, res_harsh, hi):
    eq = res_real.equity
    mid = eq.index[len(eq) // 2]
    tot = res_real.class_pnl.iloc[-1]
    share = (tot.abs().max() / tot.sum()) if tot.sum() > 0 else float("inf")
    g = {"1 net Sharpe>=0.30": sharpe(eq) >= 0.30,
         "2 maxDD<=20%": -xstats(eq, 1)["max_dd_pct"] <= 20,
         "3 harsh Sharpe>=0.10": sharpe(res_harsh.equity) >= 0.10,
         "4 no class >60% of profit": bool(tot.sum() > 0 and tot.max() / tot.sum() <= 0.60),
         "5 both halves Sharpe>-0.10": sharpe(eq, None, mid) > -0.10 and sharpe(eq, mid, None) > -0.10}
    return g


def report(label, res):
    s = res.stats
    log(f"{label}: Sharpe {s['sharpe']:+.2f} CAGR {s['cagr_pct']:+.1f}% maxDD {abs(s['max_dd_pct']):.1f}% vol {s['ann_vol_pct']:.1f}% "
        f"| costs ${res.costs:,.0f} financing ${res.financing_paid:,.0f} turnover {res.turnover_per_year:.1f}x/yr")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy-dir", default="data/proxies_d1"); ap.add_argument("--fx-dir", default="data/universe_daily")
    ap.add_argument("--stage-b", action="store_true", help="run the sealed stage (only once, only if Stage A passed)")
    a = ap.parse_args()
    log("loading data"); assets = load_assets(a.proxy_dir, a.fx_dir)
    log(f"{len(assets)} instruments; Stage A ends {STAGE_A_END}")
    A = window(assets, None, STAGE_A_END)
    real = run_xasset(A, XConfig(financing=0.03, cost_mult=1.0))
    harsh = run_xasset(A, XConfig(financing=0.06, cost_mult=2.0))
    report("Stage A realistic", real); report("Stage A harsh    ", harsh)
    log("yearly returns (realistic): " + ", ".join(f"{y}:{r*100:+.1f}%" for y, r in
        real.equity.groupby(real.equity.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1).items()))
    log("class P&L ($): " + ", ".join(f"{c}:{v:,.0f}" for c, v in real.class_pnl.iloc[-1].items()))
    g = gate(real, harsh, STAGE_A_END)
    for k, v in g.items(): log(f"  gate {k}: {'PASS' if v else 'FAIL'}")
    passed = all(g.values()); log(f"STAGE A GATE: {'PASSED' if passed else 'FAILED'}")
    if not a.stage_b: log("Stage B not run."); return 0
    if not passed: log("Stage A failed - Stage B stays sealed."); return 0
    if os.path.exists(LOCK): sys.exit("Stage B was already run once; it cannot be rerun.")
    open(LOCK, "w").write(time.ctime())
    full = run_xasset(assets, XConfig(financing=0.03)); fullh = run_xasset(assets, XConfig(financing=0.06, cost_mult=2.0))
    for lab, r in (("realistic", full), ("harsh", fullh)):
        e = r.equity.loc["2022-01-01":]; log(f"Stage B {lab}: Sharpe {sharpe(e):+.2f} maxDD {abs((e/e.cummax()-1).min())*100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
