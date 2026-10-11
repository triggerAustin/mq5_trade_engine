"""Portfolio-simulator self-test.  Run after ANY change to mt5bot/portfolio.py:  python check_portfolio.py

A) trade-for-trade equivalence with the already-verified single-market engine (backtest.py)
B) zero-cost random walks across 8 markets: no edge may appear (Sharpe ~ 0, avg R ~ 0)
C) (if the data files exist) real EURUSD daily: same trades as the single-market engine
"""
from __future__ import annotations
import os
import numpy as np, pandas as pd
from mt5bot.backtest import Config, Instrument, run_backtest
from mt5bot.portfolio import Market, PConfig, run_portfolio, sharpe_of
from mt5bot.strategies import donchian_breakout


def true_path_daily(n=6000, m=24, seed=0, start=1.10, annual_vol=0.08):
    """Daily candles from a genuine m-step random walk with volatility clustering."""
    rng = np.random.default_rng(seed)
    base = annual_vol / np.sqrt(252)
    lv = np.zeros(n)
    for i in range(1, n):
        lv[i] = 0.98 * lv[i - 1] + 0.15 * rng.standard_normal()
    vol = base * np.exp(lv - lv.var() / 2)
    steps = rng.standard_normal((n, m)) * (vol[:, None] / np.sqrt(m))
    logp = np.log(start) + np.cumsum(steps.ravel()).reshape(n, m)
    prev_end = np.concatenate([[np.log(start)], logp[:-1, -1]])
    p = np.exp(np.concatenate([prev_end[:, None], logp], axis=1))
    return pd.DataFrame({"open": p[:, 0], "high": p.max(1), "low": p.min(1), "close": p[:, -1]},
                        index=pd.date_range("2003-06-02", periods=n, freq="D"))


def sig_for(df):
    return donchian_breakout(df, 55, 20, 14, 3.0)


def check_equivalence():
    """Single market, USD-quote, nonzero costs, huge equity (so lot rounding can't matter)."""
    bad = 0; n_tr = 0
    for seed in range(6):
        df = true_path_daily(n=4000, seed=seed)
        sig = sig_for(df)
        inst = Instrument("X", 100_000, 0.0002, 0.00003, 0.0, min_lot=1e-9, lot_step=1e-9, max_lot=1e12)
        a = run_backtest(df, sig, inst, Config(initial_equity=1e9, risk_pct=0.005, max_leverage=1e9,
                                               daily_loss_limit=None, max_drawdown_kill=None)).trades
        b = run_portfolio([Market("X", df, sig, 0.0002, 0.00003)], PConfig(initial_equity=1e9)).trades
        n_tr += len(a)
        if len(a) != len(b):
            bad += 1; print(f"  seed {seed}: trade count {len(a)} vs {len(b)}"); continue
        same = (a.entry_time.values == b.entry_time.values).all() and (a.exit_time.values == b.exit_time.values).all() \
            and np.allclose(a.exit.values, b.exit.values, atol=1e-12) and (a.side.values == b.side.values).all() \
            and (a.reason.values == b.reason.values).all()
        if not same:
            bad += 1; print(f"  seed {seed}: trades differ")
    print(f"A) equivalence with single-market engine: {n_tr} trades over 6 runs, {bad} runs differ")
    return bad == 0


def check_neutrality():
    zero = [(0.0, 0.0, False), (0.0, 0.0, True)]
    sharpes, rs = [], []
    for s in range(30):
        mk = []
        for k in range(8):
            df = true_path_daily(n=6000, seed=1000 + 10 * s + k, start=1.1 if k % 4 else 110.0)
            mk.append(Market(f"M{k}", df, sig_for(df), 0.0, 0.0, usd_base=(k % 4 == 3)))
        r = run_portfolio(mk, PConfig(initial_equity=100_000, risk_pct=0.005))
        sharpes.append(r.stats["sharpe"]); rs.append(r.stats["avg_R"])
    sh, rr = np.array(sharpes), np.array(rs)
    sh_se, r_se = sh.std() / np.sqrt(len(sh)), rr.std() / np.sqrt(len(rr))
    ok1 = abs(sh.mean()) < 3 * sh_se or abs(sh.mean()) < 0.10
    ok2 = abs(rr.mean()) < 3 * r_se or abs(rr.mean()) < 0.03
    print(f"B) zero-cost random walks, 30 portfolios x 8 markets x 6000 days: "
          f"Sharpe {sh.mean():+.3f} (s.e. {sh_se:.3f}) | avg R {rr.mean():+.3f} (s.e. {r_se:.3f})  "
          f"{'PASS' if ok1 and ok2 else 'FAIL'}")
    return ok1 and ok2


def check_real_eurusd():
    f1, f2 = "data/EURUSD_H1_old.csv", "data/EURUSD_H1.csv"
    if not (os.path.exists(f1) and os.path.exists(f2)):
        print("C) real EURUSD cross-check skipped (data files not found)"); return True
    from mt5bot.data import load_csv, to_daily
    h = pd.concat([load_csv(f1), load_csv(f2)]); h = h[~h.index.duplicated()].sort_index()
    d = to_daily(h)
    sig = sig_for(d)
    inst = Instrument("EURUSD", 100_000, 0.00010, 0.00001, 0.0, min_lot=1e-9, lot_step=1e-9, max_lot=1e12)
    a = run_backtest(d, sig, inst, Config(initial_equity=1e9, risk_pct=0.005, max_leverage=1e9,
                                          daily_loss_limit=None, max_drawdown_kill=None)).trades
    b = run_portfolio([Market("EURUSD", d, sig, 0.00010, 0.00001)], PConfig(initial_equity=1e9)).trades
    ok = len(a) == len(b) and (a.exit_time.values == b.exit_time.values).all() and np.allclose(a.exit.values, b.exit.values, atol=1e-12)
    print(f"C) real EURUSD daily, 2003-2026: {len(a)} vs {len(b)} trades, identical timing and prices: {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    ok = True
    r = check_equivalence(); print("   PASS" if r else "   FAIL"); ok &= r
    ok &= check_neutrality()
    ok &= check_real_eurusd()
    print("\nOVERALL:", "ALL CHECKS PASSED" if ok else "SOMETHING IS WRONG - do not trust portfolio results")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

