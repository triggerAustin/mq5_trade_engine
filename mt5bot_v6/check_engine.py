"""Engine self-test. Run after ANY change to mt5bot/backtest.py:   python check_engine.py

On random-walk data with ZERO costs no strategy can have an edge, so every strategy's
average result must be statistically indistinguishable from zero. We also compare the
engine against an independent bare-bones simulator that watches every price step.
Prints PASS/FAIL per check; any FAIL means do not trust backtest results.
"""
from __future__ import annotations
import numpy as np, pandas as pd
from mt5bot.backtest import Config, Instrument, run_backtest
from mt5bot.strategies import donchian_breakout, mean_reversion

ZERO = Instrument("EURUSD", 100_000, 0.0, 0.0, 0.0)
CFG = Config(initial_equity=10_000, max_drawdown_kill=None, daily_loss_limit=None)


def true_path(n=30_000, m=30, seed=0, start=1.10, annual_vol=0.07):
    """Hourly candles built from a genuine m-step-per-hour random walk with volatility
    clustering: every high/low is a price the path really visited."""
    rng = np.random.default_rng(seed)
    base = annual_vol / np.sqrt(24 * 252)
    lv = np.zeros(n)
    for i in range(1, n):
        lv[i] = 0.98 * lv[i - 1] + 0.15 * rng.standard_normal()
    vol = base * np.exp(lv - lv.var() / 2)
    steps = rng.standard_normal((n, m)) * (vol[:, None] / np.sqrt(m))
    logp = np.log(start) + np.cumsum(steps.ravel()).reshape(n, m)
    prev_end = np.concatenate([[np.log(start)], logp[:-1, -1]])
    p = np.exp(np.concatenate([prev_end[:, None], logp], axis=1))
    df = pd.DataFrame({"open": p[:, 0], "high": p.max(1), "low": p.min(1), "close": p[:, -1]},
                      index=pd.date_range("2018-01-01", periods=n, freq="1h"))
    return df, p


def reference_long_only(p, sig):
    """Independent simulator (long only): walks every sub-step, exits on stop or on the exit
    signal at the bar close, never re-enters inside the bar in which it was stopped."""
    n = p.shape[0]
    le, lx, sd = sig["long_entry"], sig["long_exit"], sig["stop_dist"]
    out, pos, entry, stop = [], False, 0.0, 0.0
    for h in range(1, n):
        if not pos and le[h - 1] and np.isfinite(sd[h - 1]):
            pos, entry, stop = True, p[h, 0], p[h, 0] - sd[h - 1]
        if pos:
            if (p[h] <= stop).any():
                out.append((stop - entry) * 1e4); pos = False; continue
            if lx[h]:
                out.append((p[h, -1] - entry) * 1e4); pos = False
    return np.array(out)


def main():
    ok = True
    # 1) engine vs independent reference
    ref, eng = [], []
    for s in range(8):
        df, p = true_path(seed=900 + s)
        sig = mean_reversion(df, 50, 2.0, 14, 3.0, allow_short=False)
        ref.append(reference_long_only(p, sig))
        t = run_backtest(df, sig, ZERO, CFG).trades
        eng.append(((t.exit - t.entry) * 1e4).to_numpy())
    ref, eng = np.concatenate(ref), np.concatenate(eng)
    print(f"engine vs reference (mean-reversion, long only): trades {len(eng)} vs {len(ref)}, "
          f"mean pips {eng.mean():+.2f} vs {ref.mean():+.2f}")
    good = abs(len(eng) - len(ref)) / len(ref) < 0.03 and abs(eng.mean() - ref.mean()) < 3 * max(eng.std(), ref.std()) / np.sqrt(len(ref))
    print("  PASS" if good else "  FAIL"); ok &= good

    # 2) zero-cost random walk: average R must be ~0 for every strategy
    res = {"donchian": [], "meanrev": [], "random-entries": []}
    for s in range(40):
        df, _ = true_path(n=20_000, seed=500 + s)
        for name, sg in (("donchian", donchian_breakout(df, 40, 20, 14, 2.0)),
                         ("meanrev", mean_reversion(df, 50, 2.0, 14, 3.0))):
            r = run_backtest(df, sg, ZERO, CFG); res[name].append((r.stats["avg_R"], r.stats["profit_factor"]))
        rng = np.random.default_rng(s); u = rng.random(len(df)); sg = dict(donchian_breakout(df, 40, 20, 14, 2.0))
        sg["long_entry"], sg["short_entry"] = u < 0.01, u > 0.99
        sg["long_exit"], sg["short_exit"] = rng.random(len(df)) < 0.05, rng.random(len(df)) < 0.05
        r = run_backtest(df, sg, ZERO, CFG); res["random-entries"].append((r.stats["avg_R"], r.stats["profit_factor"]))
    print("\nzero-cost random walk, 40 runs each (want avg R ~ 0: within 3 s.e. or within +/-0.02R;")
    print("a real engine bug shows up as -0.04R or worse):")
    for k, v in res.items():
        a = np.array(v); m, se = a[:, 0].mean(), a[:, 0].std() / np.sqrt(len(a))
        good = abs(m) < 3 * se or abs(m) < 0.02
        print(f"  {k:15s} avg R {m:+.3f} (s.e. {se:.3f})  PF {a[:, 1].mean():.2f}   {'PASS' if good else 'FAIL'}")
        ok &= good
    print("\nOVERALL:", "ALL CHECKS PASSED" if ok else "SOMETHING IS WRONG - do not trust backtests")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

