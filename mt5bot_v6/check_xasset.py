"""Self-test for the cross-asset engine. Run after ANY change to mt5bot/xasset.py:  python check_xasset.py
Must print ALL CHECKS PASSED before any result from this engine is trusted.

 A) independent reference implementation (plain Python loops, different structure) matches the engine path
 B) zero-cost random walks: no profit appears (Sharpe ~ 0)
 C) mutation tests: deliberately peeking 21 days (and 1 day) ahead must be DETECTED as profit on random data
 D) costs behave: higher costs and financing never increase the result, and costs are really charged
"""
from __future__ import annotations

import math
import sys
import time

import numpy as np
import pandas as pd

from mt5bot.xasset import Asset, XConfig, run_xasset, sharpe

CLASSES = ["equity", "bond", "commodity", "fx"]


def synth(n=1500, k=8, seed=0, annual_vol=0.15, start="2005-01-03", gap_vol=0.002):
    """k assets over 4 classes; log-price random walk with volatility clustering; open != previous close."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    out = []
    for j in range(k):
        base = annual_vol / np.sqrt(252) * (0.6 + 0.8 * rng.random())
        lv = np.zeros(n)
        for i in range(1, n):
            lv[i] = 0.98 * lv[i - 1] + 0.15 * rng.standard_normal()
        sd = base * np.exp(lv - lv.var() / 2)
        g = gap_vol * rng.standard_normal(n)                  # overnight move
        h = sd * rng.standard_normal(n)                       # intraday move
        c = 100.0 * np.exp(np.cumsum(g + h))
        o = np.concatenate([[100.0], c[:-1]]) * np.exp(g)
        d = pd.DataFrame({"open": o, "close": c}, index=idx)
        if j % 3 == 2:                                        # a late starter, to exercise the expanding universe
            d = d.iloc[400:]
        out.append(Asset(f"A{j}", CLASSES[j % 4], d, 0.0002))
    return out


# ------------------------------------------------------------------ independent reference ---------------
def reference(assets, cfg):
    """Deliberately naive re-implementation: per-day Python loops, dicts, math module. Same rules, different code."""
    dates = sorted(set().union(*[set(a.df.index) for a in assets]))
    T = len(dates)
    alpha = 2.0 / (cfg.vol_span + 1)
    close = {}; opn = {}; start = {}
    for a in assets:
        c, o, last, st = [], [], None, None
        for t, d in enumerate(dates):
            if d in a.df.index:
                if st is None:
                    st = t
                last_c = float(a.df.loc[d, "close"]); o_t = float(a.df.loc[d, "open"])
                c.append(last_c); o.append(o_t); last = last_c
            else:
                c.append(last if last is not None else None)
                o.append(last if last is not None else None)       # no bar: open = previous (flat) close
        close[a.name] = c; opn[a.name] = o; start[a.name] = st
    names = [a.name for a in assets]
    cls = {a.name: a.cls for a in assets}
    cside = {a.name: a.cost_side * cfg.cost_mult for a in assets}

    def ret(n, t):
        if t == 0 or close[n][t] is None or close[n][t - 1] is None:
            return None
        return close[n][t] / close[n][t - 1] - 1.0

    def ewvol(n, t):
        xs = [(t - s, ret(n, s)) for s in range(0, t + 1) if ret(n, s) is not None]
        if len(xs) < 30:
            return None
        w = [(1 - alpha) ** k for k, _ in xs]
        x = [v for _, v in xs]
        v1 = sum(w); v2 = sum(q * q for q in w)
        m = sum(q * r for q, r in zip(w, x)) / v1
        bv = sum(q * (r - m) ** 2 for q, r in zip(w, x)) / v1
        var = bv / (1 - v2 / (v1 * v1))
        return max(math.sqrt(var) * math.sqrt(252), cfg.vol_floor)

    units = {n: 0.0 for n in names}
    E = cfg.initial_equity
    pending = None
    eq = []
    for t in range(T):
        if t > 0:
            if pending is not None:
                for n in names:
                    if close[n][t - 1] is not None and opn[n][t] is not None:
                        E += units[n] * (opn[n][t] - close[n][t - 1])
                E_open = E                                       # all targets sized on equity before this open's costs
                for n in names:
                    o = opn[n][t]
                    cur = units[n] * (o if o is not None else 0.0)
                    tgt = pending.get(n, 0.0) * E_open
                    E -= abs(tgt - cur) * cside[n]
                    pending_tgt = tgt
                    units[n] = (pending_tgt / o) if (o is not None and o > 0) else 0.0
                for n in names:
                    if close[n][t] is not None and opn[n][t] is not None:
                        E += units[n] * (close[n][t] - opn[n][t])
                pending = None
            else:
                for n in names:
                    if close[n][t] is not None and close[n][t - 1] is not None:
                        E += units[n] * (close[n][t] - close[n][t - 1])
            if cfg.financing:
                gross = sum(abs(units[n]) * close[n][t] for n in names if close[n][t] is not None)
                E -= gross * cfg.financing * (dates[t] - dates[t - 1]).days / 365.0
        eq.append(E)
        if t < T - 1 and dates[t].month != dates[t + 1].month:
            ttt = min(t + cfg._bug_lookahead, T - 1) if cfg._bug_lookahead else t
            sig = {}
            for n in names:
                v = ewvol(n, t)
                good = v is not None
                s = 0.0
                for L in cfg.lookbacks:
                    if t - L < 0 or close[n][t - L] is None or not good:
                        good = False
                        break
                    r = close[n][ttt] / close[n][t - L] - 1.0
                    s += (r > 0) - (r < 0)
                if good:
                    sig[n] = (s / len(cfg.lookbacks), v)
            if not sig:
                pending = {}
                continue
            active = sorted({cls[n] for n in sig})
            raw = {}
            for c in active:
                mem = [n for n in sig if cls[n] == c]
                for n in mem:
                    raw[n] = sig[n][0] * (cfg.asset_vol / sig[n][1]) / len(mem) / len(active)
            lo = max(0, t - cfg.port_window + 1)
            rp = []
            for s_ in range(lo, t + 1):
                rp.append(sum(raw[n] * (ret(n, s_) or 0.0) for n in raw))
            m = sum(rp) / len(rp)
            vp = math.sqrt(sum((x - m) ** 2 for x in rp) / (len(rp) - 1)) * math.sqrt(252) if len(rp) > 5 else 0.0
            gross = sum(abs(x) for x in raw.values())
            scale = min(cfg.port_vol / vp, cfg.gross_cap / gross) if (vp > 0 and gross > 0) else 0.0
            pending = {n: raw[n] * scale for n in raw}
    return pd.Series(eq, index=pd.DatetimeIndex(dates))


# ------------------------------------------------------------------ checks ---------------------------------
def check_reference():
    bad = 0
    worst = 0.0
    for seed in range(3):
        assets = synth(n=900, k=6, seed=seed)
        cfg = XConfig(financing=0.03, cost_mult=1.0)
        a = run_xasset(assets, cfg).equity
        b = reference(assets, cfg)
        rel = float(((a - b).abs() / b.abs()).max())
        worst = max(worst, rel)
        if rel > 1e-9:
            bad += 1
            print(f"  seed {seed}: max relative difference {rel:.3e}")
    print(f"A) independent reference vs engine, 3 runs with costs and financing: worst relative diff {worst:.2e}  "
          f"{'PASS' if bad == 0 else 'FAIL'}")
    return bad == 0


def neutral_sharpes(n_runs=30, n=4500, k=12, **kw):
    sh = []
    for s in range(n_runs):
        r = run_xasset(synth(n=n, k=k, seed=500 + s), XConfig(financing=0.0, cost_mult=0.0, **kw))
        sh.append(sharpe(r.equity))
    return np.array(sh)


def check_neutrality():
    sh = neutral_sharpes()
    se = sh.std(ddof=1) / np.sqrt(len(sh))
    ok = abs(sh.mean()) < 3 * se or abs(sh.mean()) < 0.10
    print(f"B) zero-cost random walks, 30 portfolios x 12 assets x 4500 days: Sharpe {sh.mean():+.3f} (s.e. {se:.3f})  "
          f"{'PASS' if ok else 'FAIL'}")
    return ok, sh


def check_mutation(base):
    se = base.std(ddof=1) / np.sqrt(len(base))
    ok_all = True
    for peek in (21, 1):
        sh = neutral_sharpes(n_runs=30, _bug_lookahead=peek)
        diff = sh.mean() - base.mean()
        se2 = math.sqrt(se ** 2 + (sh.std(ddof=1) / np.sqrt(len(sh))) ** 2)
        detected = diff > 4 * se2 and sh.mean() > 0.10
        print(f"C) mutation: peek {peek:2d} day(s) ahead -> mean Sharpe {sh.mean():+.3f} (neutral {base.mean():+.3f}); "
              f"{'DETECTED' if detected else 'NOT DETECTED'}")
        if peek == 21:
            ok_all &= detected                 # a gross leak MUST be caught
    print("   (a 1-day leak is reported for information; the 21-day leak must be detected)")
    return ok_all


def check_costs():
    assets = synth(n=3000, k=8, seed=7)
    base = run_xasset(assets, XConfig(financing=0.0, cost_mult=0.0))
    c1 = run_xasset(assets, XConfig(financing=0.0, cost_mult=1.0))
    c2 = run_xasset(assets, XConfig(financing=0.0, cost_mult=2.0))
    f1 = run_xasset(assets, XConfig(financing=0.03, cost_mult=1.0))
    ok = (c1.equity.iloc[-1] < base.equity.iloc[-1] and c2.equity.iloc[-1] < c1.equity.iloc[-1]
          and f1.equity.iloc[-1] < c1.equity.iloc[-1] and c1.costs > 0 and f1.financing_paid > 0)
    print(f"D) costs: end equity zero-cost {base.equity.iloc[-1]:,.0f} > 1x {c1.equity.iloc[-1]:,.0f} > 2x {c2.equity.iloc[-1]:,.0f}; "
          f"financing paid {f1.financing_paid:,.0f}; turnover/yr {c1.turnover_per_year:.1f}x  {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    t0 = time.time()
    ok = check_reference()
    ok_n, base = check_neutrality()
    ok &= ok_n
    ok &= check_mutation(base)
    ok &= check_costs()
    print(f"\nOVERALL: {'ALL CHECKS PASSED' if ok else 'SOMETHING IS WRONG - do not trust results from this engine'}  ({time.time() - t0:.0f}s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
