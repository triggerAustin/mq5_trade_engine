#!/usr/bin/env python3
"""Analyse the demo forward run.   python analyse_forward.py --dir "<path to MT5 Common/Files>"
Reads pa_signals.csv, pa_deals.csv, pa_snapshots.csv written by PA_Forward.mq5.
Plumbing checks first, then a live-vs-assumed spread check, then results per variant.

Exit codes: 0 = ok, 1 = no signals file, 2 = spread assumption violated (results withheld)."""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

ASSUMED_SPREAD_PTS = {
    "EURUSD": 10,
    "GBPUSD": 13,
    "USDJPY": 10,
    "AUDUSD": 12,
}  # points, as used in the backtests (5-digit/3-digit quotes)
REASON = {
    0: "client",
    1: "mobile",
    2: "web",
    3: "expert",
    4: "stop_loss",
    5: "take_profit",
    6: "stop_out",
}

# spread-check thresholds
SPREAD_RATIO_WARN = 1.5  # live median > 1.5x assumed -> withhold results
SPREAD_MIN_SAMPLES = (
    30  # fewer than this many live samples per symbol -> withhold results
)


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def boot_lb(R, seed=1, n_boot=5000, alpha=2.5):
    """Bootstrap (alpha)% lower bound on the mean of R.  Returns nan for n < 5.
    A 2-point bootstrap is not a confidence bound, it is a rumour."""
    n = len(R)
    if n < 5:
        return float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = R[idx].mean(axis=1)
    return float(np.percentile(means, alpha))


def spread_check(sig, sn, assumed):
    """Compare live spreads against the backtest assumption.
    Returns (ok: bool, table: pd.DataFrame)."""
    rows = []
    # from the signals file: one row per traded/skipped signal, live spread at decision time
    if "spread_pts" in sig.columns:
        live_sig = (
            sig[sig.spread_pts > 0]
            .groupby("symbol")
            .spread_pts.agg(
                n_sig="count", med_sig="median", p95_sig=lambda x: x.quantile(0.95)
            )
        )
    else:
        live_sig = pd.DataFrame()
    # from the snapshots: hourly, independent of whether a signal fired
    if sn is not None and len(sn):
        live_snap = sn.groupby("symbol").spread_pts.agg(
            n_snap="count",
            med_snap="median",
            p95_snap=lambda x: x.quantile(0.95),
            max_snap="max",
        )
    else:
        live_snap = pd.DataFrame()
    for s in sorted(set(list(live_sig.index) + list(live_snap.index))):
        a = assumed.get(s, np.nan)
        r = {"symbol": s, "assumed": a}
        if s in live_sig.index:
            r.update(live_sig.loc[s].to_dict())
        if s in live_snap.index:
            r.update(live_snap.loc[s].to_dict())
        med = r.get("med_snap", r.get("med_sig", np.nan))
        r["ratio_med"] = (med / a) if (a and a > 0 and not np.isnan(med)) else np.nan
        r["n_live"] = int(r.get("n_snap", 0) + r.get("n_sig", 0))
        r["ok"] = (
            (not np.isnan(r["ratio_med"]))
            and (r["ratio_med"] <= SPREAD_RATIO_WARN)
            and (r["n_live"] >= SPREAD_MIN_SAMPLES)
        )
        rows.append(r)
    table = pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame()
    ok = bool(table.ok.all()) if len(table) else False
    return ok, table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument(
        "--force",
        action="store_true",
        help="print variant results even if the spread check fails",
    )
    ap.add_argument(
        "--min-trades", type=int, default=100, help="plan's review gate for variant A"
    )
    a = ap.parse_args()
    p = lambda f: os.path.join(a.dir, f)
    if not os.path.exists(p("pa_signals.csv")):
        sys.exit(
            "pa_signals.csv not found - no candle with a signal yet, or wrong --dir"
        )

    sig = pd.read_csv(p("pa_signals.csv"))
    log(
        f"signals file: {len(sig)} rows, {sig.candle_time_server.iloc[0]} -> {sig.candle_time_server.iloc[-1]}"
    )
    log("signal status counts by variant:")
    print(pd.crosstab(sig.variant, sig.status).to_string())
    fails = sig[sig.status.str.startswith("FAIL_")]
    log(
        f"order failures: {len(fails)}"
        + (f"  codes: {fails.status.value_counts().to_dict()}" if len(fails) else "")
    )
    log(
        f"late candles ignored (terminal off/disconnected): {int((sig.status == 'LATE_CANDLE_IGNORED').sum())}"
    )

    sn = None
    if os.path.exists(p("pa_snapshots.csv")):
        sn = pd.read_csv(p("pa_snapshots.csv"))
        if len(sn):
            eq = sn.drop_duplicates("time_server").equity
            log(f"equity {eq.iloc[0]:,.2f} -> {eq.iloc[-1]:,.2f}")

    log("--- live spread vs backtest assumption (points) ---")
    spread_ok, sp_tab = spread_check(sig, sn, ASSUMED_SPREAD_PTS)
    if len(sp_tab):
        print(sp_tab.round(2).to_string())
    else:
        log("no usable spread samples yet")
    if not spread_ok:
        log(
            f"SPREAD CHECK FAILED (threshold: median <= {SPREAD_RATIO_WARN}x assumed, >= {SPREAD_MIN_SAMPLES} samples/symbol)"
        )
        log(
            "The backtest assumed different costs. Variant results below would be mis-scaled, so they are withheld."
        )
        if not a.force:
            log(
                "Re-run with --force to print them anyway. Better: fix the cost assumption first."
            )
            return 2
        log("--force given, printing results anyway.")

    if not os.path.exists(p("pa_deals.csv")):
        log("no deals yet")
        return 0

    dl = pd.read_csv(p("pa_deals.csv"))
    traded = sig[sig.status == "TRADED"].copy()
    ins = dl[dl.entry == 0].set_index("position_id")
    outs = (
        dl[dl.entry == 1]
        .groupby("position_id")
        .agg(close_time=("time_server", "last"), reason=("reason", "last"))
    )
    tot = dl.groupby("position_id")[["profit", "swap", "commission"]].sum()
    closed = tot.join(outs, how="inner").join(
        ins[["price", "volume", "magic"]].rename(columns={"price": "fill"}), how="left"
    )
    closed["pnl"] = closed.profit + closed.swap + closed.commission
    traded = traded.set_index("order_ticket")
    m = closed.join(
        traded[
            [
                "variant",
                "symbol",
                "dir",
                "pattern",
                "ref_price",
                "risk_acct",
                "spread_pts",
            ]
        ],
        how="left",
    )
    orphans = int(m.variant.isna().sum())
    log(
        f"plumbing: {len(traded)} orders sent, {len(closed)} positions closed, {orphans} closed positions not matched to a signal row"
    )
    log(f"still open (or unmatched): {len(traded) - len(closed)}")
    m = m.dropna(subset=["variant"])
    if len(m) == 0:
        log("no closed trades yet")
        return 0
    m["R"] = m.pnl / m.risk_acct
    m["slip_pts"] = m.dir * (m.fill - m.ref_price)
    m["reason_txt"] = m.reason.map(REASON).fillna(m.reason.astype(str))
    log(
        f"slippage vs the price seen at decision (points, + = worse for us for buys, sign follows direction): mean {m.slip_pts.mean():+.5f}"
    )

    for v, g in m.groupby("variant"):
        R = g.R.to_numpy()
        w, l = g.pnl[g.pnl > 0].sum(), -g.pnl[g.pnl < 0].sum()
        se = R.std(ddof=1) / np.sqrt(len(R)) if len(R) > 1 else float("nan")
        lb = boot_lb(R)
        lb_txt = f"{lb:+.3f}" if not np.isnan(lb) else "n/a (n<5)"
        log(
            f"variant {v}: trades {len(g)} | mean R {R.mean():+.3f} (s.e. {se:.3f}, 95% low {lb_txt}) | "
            f"PF {w / l if l > 0 else float('inf'):.2f} | win {100 * (g.pnl > 0).mean():.0f}% | pnl {g.pnl.sum():+.2f} | "
            f"swap {g.swap.sum():+.2f} | exits {g.reason_txt.value_counts().to_dict()}"
        )
    if "A" in m.variant.values:
        log(
            f"by symbol (A only): "
            + ", ".join(
                f"{s}: {len(g)}, {g.R.mean():+.2f}"
                for s, g in m[m.variant == "A"].groupby("symbol")
            )
        )
        nA = int((m.variant == "A").sum())
        if nA < a.min_trades:
            log(
                f"NOTE: variant A has {nA} closed trades, review gate is {a.min_trades}. Numbers above are plumbing, not evidence."
            )
    log(
        "REMINDER: a few dozen trades cannot show an edge. Compare the s.e. above with +0.10 R. The value of this run is plumbing and costs."
    )
    m.to_csv(p("forward_trades_merged.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
