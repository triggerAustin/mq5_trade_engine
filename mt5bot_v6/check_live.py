"""Live-logic self-test.   python check_live.py [--all]   (run after ANY change to mt5bot/live.py)

A) NO-PEEK: signals computed from the last WINDOW closed bars up to day t must equal the signals the
   full-history backtest has for day t. Catches look-ahead and window/warm-up differences.
B) REPLAY: step through history one closed bar at a time, call decide() on ONLY the bars known at that
   moment, keep a paper position, and compare the resulting trades (entry/exit dates, side, reason,
   exit price) with the portfolio backtest engine. They must be identical.

The paper broker below deliberately follows the SAME fill conventions as mt5bot/portfolio.py (stop wins
over a same-bar signal exit, gap fills at the open, no re-entry on a bar where a stop fired mid-bar).
Real data (data/universe_daily) is used if present: EURUSD and XAUUSD by default, every market with --all.
"""
from __future__ import annotations
import argparse, os, sys, time
import numpy as np, pandas as pd
from check_portfolio import true_path_daily
from mt5bot.live import SPEC, WINDOW, Position, decide
from mt5bot.portfolio import Market, PConfig, run_portfolio
from mt5bot.strategies import donchian_breakout

SPREAD, SLIP = 0.0002, 0.00003


def check_no_peek(df, name, n_cuts=150, seed=0):
    full = donchian_breakout(df, **SPEC)
    rng = np.random.default_rng(seed)
    cuts = rng.integers(60, len(df), n_cuts)
    bad = 0
    for t in cuts:
        w = donchian_breakout(df.iloc[:t + 1].iloc[-WINDOW:], **SPEC)
        for k in ("long_entry", "short_entry", "long_exit", "short_exit"):
            bad += int(w[k][-1] != full[k][t])
        a, b = w["stop_dist"][-1], full["stop_dist"][t]
        bad += int(not ((np.isnan(a) and np.isnan(b)) or np.isclose(a, b, rtol=1e-9, atol=0)))
    print(f"A) no-peek {name:8s}: {len(cuts)} cut points, {bad} mismatches  {'PASS' if bad == 0 else 'FAIL'}")
    return bad == 0


def replay(df, spread=SPREAD, slip=SLIP):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    idx = df.index
    pos, trades = None, []

    def close(j, px, reason):
        nonlocal pos
        trades.append(dict(entry_time=pos.opened, exit_time=idx[j], side="long" if pos.side == 1 else "short",
                           exit=px, reason=reason))
        pos = None

    for j in range(1, len(df)):
        dec = decide(df.iloc[:j], pos)          # ONLY bars 0..j-1 are known here
        n0, stopped = len(trades), False
        if pos is not None:
            if pos.side == 1:
                if o[j] <= pos.stop: close(j, o[j] - slip, "stop_gap")
                elif l[j] <= pos.stop: close(j, pos.stop - slip, "stop")
                elif dec.close_position: close(j, o[j] - slip, "signal")
            else:
                if o[j] + spread >= pos.stop: close(j, o[j] + spread + slip, "stop_gap")
                elif h[j] + spread >= pos.stop: close(j, pos.stop + slip, "stop")
                elif dec.close_position: close(j, o[j] + spread + slip, "signal")
            stopped = len(trades) > n0 and trades[-1]["reason"] == "stop"
        if pos is None and not stopped and dec.entry_side != 0:
            s = dec.entry_side
            pos = Position(s, o[j] + spread + slip if s == 1 else o[j] - slip,
                           o[j] - dec.stop_dist if s == 1 else o[j] + dec.stop_dist, 0.0, idx[j])
            if s == 1 and l[j] <= pos.stop: close(j, pos.stop - slip, "stop")
            elif s == -1 and h[j] + spread >= pos.stop: close(j, pos.stop + slip, "stop")
    return pd.DataFrame(trades)


def check_replay(df, name):
    t0 = time.time()
    mine = replay(df)
    eng = run_portfolio([Market(name, df, donchian_breakout(df, **SPEC), SPREAD, SLIP)],
                        PConfig(initial_equity=1e9)).trades
    eng = eng[eng.reason != "end"].reset_index(drop=True)
    ok = len(mine) == len(eng)
    if ok and len(mine):
        ok = ((mine.entry_time.values == eng.entry_time.values).all() and (mine.exit_time.values == eng.exit_time.values).all()
              and (mine.side.values == eng.side.values).all() and (mine.reason.values == eng.reason.values).all()
              and np.allclose(mine.exit.values, eng.exit.values, atol=1e-9))
    print(f"B) replay  {name:8s}: live-style {len(mine)} vs engine {len(eng)} trades, identical: {'PASS' if ok else 'FAIL'}  ({time.time() - t0:.0f}s)")
    if not ok:
        n = min(len(mine), len(eng))
        for i in range(n):
            if not (mine.entry_time[i] == eng.entry_time[i] and mine.exit_time[i] == eng.exit_time[i] and mine.reason[i] == eng.reason[i]):
                print("   first difference:\n", mine.iloc[i].to_dict(), "\n", eng.iloc[i][["entry_time", "exit_time", "side", "reason", "exit"]].to_dict()); break
    return ok


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--all", action="store_true")
    ap.add_argument("--data-dir", default="data/universe_daily"); a = ap.parse_args()
    ok = True
    for seed in (1, 2):
        df = true_path_daily(n=3000, seed=seed)
        ok &= check_no_peek(df, f"synth{seed}"); ok &= check_replay(df, f"synth{seed}")
    names = ["EURUSD", "XAUUSD"] if not a.all else ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"]
    found = False
    for n in names:
        p = os.path.join(a.data_dir, f"{n}_D1.csv")
        if os.path.exists(p):
            found = True
            d = pd.read_csv(p, index_col=0, parse_dates=True)
            ok &= check_no_peek(d, n); ok &= check_replay(d, n)
    if not found:
        print("   (no real data files found - real-data checks skipped)")
    print("\nOVERALL:", "ALL LIVE CHECKS PASSED" if ok else "SOMETHING IS WRONG - do not trust the signal runner")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
