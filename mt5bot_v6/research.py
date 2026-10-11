"""Experiment 1: breakout vs mean-reversion x timeframe x filters, realistic costs.

Rules that keep this honest:
  * one fixed split date; every config is evaluated on BOTH halves, nothing is picked using the test half
  * signals are computed on the full history then cut (no indicator warm-up artefacts)
  * risk limits are switched off so we see the raw signal quality (they are a live-trading safety, not an edge)
"""
from __future__ import annotations
import itertools, sys, time
import numpy as np, pandas as pd
from mt5bot.backtest import Config, Instrument, run_backtest
from mt5bot.data import load_csv, resample, to_daily
from mt5bot.strategies import donchian_breakout, mean_reversion, with_session, with_trend

CSV = sys.argv[1] if len(sys.argv) > 1 else "data/EURUSD_H1.csv"
# Standard retail account: 1.0 pip spread, 0.1 pip slippage per fill, no commission  (~1.2 pips round trip)
STD = Instrument("EURUSD", 100_000, 0.00010, 0.00001, 0.0)
# What my first run used (~2.3 pips round trip): stress test only
HARSH = Instrument("EURUSD", 100_000, 0.00012, 0.00002, 7.0)
CFG = Config(max_drawdown_kill=None, daily_loss_limit=None)

h1 = load_csv(CSV)
SPLIT = h1.index[int(len(h1) * 0.6)]
# Daily bars on the 17:00 New York FX roll (v6 fix; the old fixed 22:00 UTC cut created spurious Sunday stub bars)
D1 = to_daily(h1)
FRAMES = {"H1": h1, "H4": resample(h1, "4h"), "D1": D1}

def seg(sig, a, b): return {k: v[a:b] for k, v in sig.items()}

def stats(df, sig, inst, a, b):
    r = run_backtest(df.iloc[a:b], seg(sig, a, b), inst, CFG)
    s, t = r.stats, r.trades
    n = s["trades"]
    tstat = np.nan
    if n >= 5 and t["r"].std() > 0:
        tstat = t["r"].mean() / (t["r"].std() / np.sqrt(n))
    return dict(ret=s["return_pct"], n=n, pf=s.get("profit_factor", np.nan), avgR=s.get("avg_R", np.nan),
                dd=s["max_drawdown_pct"], t=tstat)

def grid(d): return [dict(zip(d, v)) for v in itertools.product(*d.values())]

DON = grid({"entry_n": [20, 40, 55, 80], "exit_n": [10, 20], "atr_stop": [2.0, 3.0]})
DON = [p for p in DON if p["exit_n"] < p["entry_n"]]
MR = grid({"n": [20, 50, 100], "k": [1.5, 2.0, 2.5, 3.0], "atr_stop": [2.0, 3.0, 4.0]})

def families():
    for tf in ("H1", "H4", "D1"):
        for filt in ("none", "session", "trend"):
            if filt == "session" and tf == "D1": continue
            yield "donchian", tf, filt, DON
            yield "meanrev", tf, filt, MR

def build(name, df, p, filt):
    sig = donchian_breakout(df, **p) if name == "donchian" else mean_reversion(df, **p)
    if filt == "session": sig = with_session(sig, df)
    if filt == "trend": sig = with_trend(sig, df)
    return sig

if __name__ == "__main__":
    rows, t0 = [], time.time()
    for name, tf, filt, G in families():
        if name == "meanrev" and filt == "trend": continue  # trend filter fights mean reversion by design
        df = FRAMES[tf]; a = df.index.searchsorted(SPLIT); n = len(df)
        for p in G:
            sig = build(name, df, p, filt)
            tr, te = stats(df, sig, STD, 0, a), stats(df, sig, STD, a, n)
            rows.append(dict(strategy=name, tf=tf, filt=filt, params=str(p),
                             **{f"tr_{k}": v for k, v in tr.items()}, **{f"te_{k}": v for k, v in te.items()}))
        print(f"{name:9s} {tf} {filt:8s} done ({time.time()-t0:.0f}s)", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv("results_exp1.csv", index=False)
    print("split date:", SPLIT, "| configs:", len(res))
