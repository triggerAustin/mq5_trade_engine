#!/usr/bin/env python3
"""PRE-REGISTERED DRIVER AUDIT (test #7, see PREREGISTRATION_7_AUDIT_LOCKED.md).
Question: does any outside driver (VIX, S&P 500, US yields, real yields, oil, dollar momentum) predict the NEXT 5 trading days of a
market, using data up to 2018-12-31 only? 2019 onward is cut off at load time and is never touched here.
    python run_driver_audit.py
Needs: data/universe_daily/{PAIR}_D1.csv, data/proxies_d1/SPY.csv, data/fred_drivers.json (browser snippet in the instructions).
Prints a table and writes data/driver_audit_results.csv."""
from __future__ import annotations

import io
import json
import os
import sys
import time
from statistics import NormalDist

import numpy as np
import pandas as pd

DEV_END = "2018-12-31"
H = 5          # forward horizon in trading days
LB = 20        # lookback for change/momentum features
ZWIN = 252     # trailing window used to standardise every feature (no look-ahead)
HAC_L = 5      # Newey-West lags (5-day returns overlap)
MARKETS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"]
USD_SIGN = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDJPY": 1, "USDCAD": 1, "USDCHF": 1}  # +1: pair up = USD stronger
FRED_IDS = ["VIXCLS", "DGS2", "DFII10", "DCOILWTICO"]
# PRE-REGISTERED primary tests (market -> drivers). Everything else is exploratory and cannot pass.
PRIMARY = {"EURUSD": ["USD_mom", "US2Y_chg", "REAL_chg"], "GBPUSD": ["USD_mom", "US2Y_chg", "REAL_chg"],
           "AUDUSD": ["VIX_lvl", "VIX_chg", "SPY_mom"], "NZDUSD": ["VIX_lvl", "VIX_chg", "SPY_mom"],
           "USDJPY": ["VIX_lvl", "VIX_chg", "SPY_mom"], "USDCHF": ["VIX_lvl", "VIX_chg", "SPY_mom"],
           "USDCAD": ["OIL_mom"], "XAUUSD": ["REAL_chg", "US2Y_chg", "USD_mom"]}
N_PRIMARY = sum(len(v) for v in PRIMARY.values())
Z_CRIT = NormalDist().inv_cdf(1 - 0.05 / N_PRIMARY / 2)     # Bonferroni, two-sided, family alpha 5%


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def hac_t(x, L=HAC_L):
    """mean and Newey-West t-statistic of a series (Bartlett weights)."""
    x = np.asarray(x, float)
    n = len(x)
    m = x.mean()
    e = x - m
    v = e @ e / n
    for k in range(1, L + 1):
        v += 2 * (1 - k / (L + 1)) * (e[k:] @ e[:-k]) / n
    return m, m / np.sqrt(v / n)


def tz(s, win=ZWIN):
    """trailing z-score, clipped to +-3; uses only data up to each date."""
    m = s.rolling(win, min_periods=120).mean()
    sd = s.rolling(win, min_periods=120).std()
    return ((s - m) / sd).clip(-3, 3)


def build_xy(close, feat, h=H, dev_end=DEV_END):
    """feature known through the PREVIOUS row (1-row lag) vs log return close[t] -> close[t+h]."""
    close = close.loc[:dev_end]
    f = feat.reindex(close.index.union(feat.index)).ffill().reindex(close.index).shift(1)
    fwd = np.log(close.shift(-h) / close)
    return pd.concat([f, fwd], axis=1, keys=["s", "r"]).dropna()


def evaluate(close, feat_z):
    d = build_xy(close, feat_z)
    if len(d) < 500:
        return None
    p = (d.s * d.r).values
    m, t = hac_t(p)
    beta = (d.s * d.r).mean() / (d.s ** 2).mean()          # 5-day log return per +1 sd of the driver
    mid = len(d) // 2
    _, t1 = hac_t(p[:mid])
    _, t2 = hac_t(p[mid:])
    big = d[d.s.abs() >= 1]
    hit = float((np.sign(big.s) == np.sign(big.r)).mean()) if len(big) else float("nan")
    return {"n": len(d), "beta_bps": beta * 1e4, "t": t, "t_h1": t1, "t_h2": t2, "hit_|s|>=1": hit,
            "start": d.index[0].date(), "end": d.index[-1].date()}


def load_csv_series(path, col):
    df = pd.read_csv(path)
    df.iloc[:, 0] = pd.to_datetime(df.iloc[:, 0], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize()
    df = df.dropna(subset=[df.columns[0]]).set_index(df.columns[0]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[col].astype(float).loc[:DEV_END]


def load_fred(path):
    raw = json.load(open(path))
    out = {}
    for k in FRED_IDS:
        if k not in raw:
            sys.exit(f"{path} has no {k}; rerun the browser snippet")
        df = pd.read_csv(io.StringIO(raw[k]))
        s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").values, index=pd.to_datetime(df.iloc[:, 0]))
        out[k] = s.dropna().sort_index().loc[:DEV_END]
        log(f"  {k}: {len(out[k]):,} obs, {out[k].index[0].date()} -> {out[k].index[-1].date()}")
    return out


def driver_features(fx, spy, fred):
    """native-calendar standardised features (non-market-specific)."""
    vix = np.log(fred["VIXCLS"].clip(lower=1))
    oil = fred["DCOILWTICO"].where(fred["DCOILWTICO"] > 0).dropna()
    return {"VIX_lvl": tz(vix), "VIX_chg": tz(vix.diff(5)), "SPY_mom": tz(np.log(spy).diff(LB)),
            "US2Y_chg": tz(fred["DGS2"].diff(LB)), "REAL_chg": tz(fred["DFII10"].diff(LB)),
            "OIL_mom": tz(np.log(oil).diff(LB))}


def usd_mom(fx, exclude):
    cols = [c for c in USD_SIGN if c != exclude]
    lr = np.log(fx[cols]).diff()
    for c in cols:
        lr[c] = lr[c] * USD_SIGN[c]
    return tz(lr.mean(axis=1).rolling(LB).sum())


def main():
    log(f"driver audit: development window up to {DEV_END}; forward horizon {H} days; "
        f"{N_PRIMARY} primary tests -> Bonferroni |t| >= {Z_CRIT:.2f}")
    fx = {}
    for m in MARKETS:
        p = f"data/universe_daily/{m}_D1.csv"
        if not os.path.exists(p):
            sys.exit(f"missing {p}")
        fx[m] = load_csv_series(p, "close")
        log(f"  {m}: {len(fx[m]):,} daily candles, {fx[m].index[0].date()} -> {fx[m].index[-1].date()}")
    spy = load_csv_series("data/proxies_d1/SPY.csv", "adj_close")
    log(f"  SPY: {len(spy):,} days, {spy.index[0].date()} -> {spy.index[-1].date()}")
    fred = load_fred("data/fred_drivers.json")
    fxdf = pd.DataFrame({k: v for k, v in fx.items() if k != "XAUUSD"}).sort_index().ffill()
    base = driver_features(fx, spy, fred)
    own = {m: tz(np.log(fx[m]).diff(LB)) for m in MARKETS}
    rows = []
    for m in MARKETS:
        feats = dict(base)
        feats["USD_mom"] = usd_mom(fxdf, m)
        feats["OWN_mom"] = own[m]
        for name, f in feats.items():
            r = evaluate(fx[m], f)
            if r is None:
                log(f"  {m} x {name}: too few observations, skipped")
                continue
            prim = name in PRIMARY.get(m, [])
            same = np.sign(r["t"]) == np.sign(r["t_h1"]) == np.sign(r["t_h2"])
            ok = bool(prim and abs(r["t"]) >= Z_CRIT and same and abs(r["t_h1"]) >= 1 and abs(r["t_h2"]) >= 1)
            rows.append({"market": m, "driver": name, "primary": prim, "PASS": ok, **r})
            log(f"  {m} x {name}: t {r['t']:+.2f} (halves {r['t_h1']:+.2f}, {r['t_h2']:+.2f}) beta {r['beta_bps']:+.1f} bps/sd "
                f"{'PRIMARY' if prim else 'exploratory'}{'  <-- PASS' if ok else ''}")
    df = pd.DataFrame(rows)
    df.to_csv("data/driver_audit_results.csv", index=False)
    log("=" * 70)
    log(f"PRIMARY TESTS ({N_PRIMARY}); pass = |t| >= {Z_CRIT:.2f} and same sign and |t| >= 1 in both halves")
    pr = df[df.primary].sort_values("t", key=lambda s: -s.abs())
    for _, r in pr.iterrows():
        log(f"  {r.market:7s} {r.driver:9s} t {r.t:+6.2f}  halves {r.t_h1:+5.2f} {r.t_h2:+5.2f}  beta {r.beta_bps:+6.1f} bps/sd  "
            f"{'PASS' if r.PASS else 'fail'}")
    log(f"VERDICT: {int(pr.PASS.sum())} of {len(pr)} primary tests passed")
    log("expected by pure luck at Bonferroni 5%: about 0.05 passes. Exploratory rows are information only and cannot pass.")
    log("Send me this whole output. Nothing from 2019 onward was loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
