"""Self-test for the price-action engine (test #6). Run after ANY change to mt5bot/priceaction.py:  python check_priceaction.py
Must print ALL CHECKS PASSED before any result from this engine is trusted.

 U) hand-worked candles: H1 -> H4 grouping, engulfing and pin-bar signals, swing/trend/pullback logic, entry and exit prices,
    lot size, stop-first rule, gap stop, gap target, time exit, short side (mirror image), Wednesday triple swap
 A) independent single-pair reference implementation (plain Python, brute-force swings) matches the engine trade by trade
 B) zero-cost random walks: the average trade result is indistinguishable from zero
 C) mutation: a signal that peeks 6 candles ahead must be DETECTED as profit on random data
 D) costs behave: higher costs and swap never improve the result, and they are really charged
"""
from __future__ import annotations

import math
import sys
import time

import numpy as np
import pandas as pd

from mt5bot.priceaction import PACfg, run_pa, to_h4
from mt5bot.pullback import CONTRACT, Pair

T0 = time.time()


def log(m):
    print(f"[{time.time() - T0:5.0f}s] {m}", flush=True)


def close_to(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(b))


# ------------------------------------------------------------------ hand-worked candles ---------------------
# Candles are (open, high, low, close). With swing_n=1, atr_n=2 and no warm-up the first six candles build an uptrend:
#   swing highs 11.0 (candle 1) and 11.5 (candle 3) are rising, swing lows 9.8 (candle 2) and 10.2 (candle 5) are rising,
#   candles 4 and 5 are bearish (the pullback), and candle 6 is the signal candle.
UP = [(10.0, 10.5, 9.5, 10.2),    # 0
      (10.2, 11.0, 10.0, 10.8),   # 1 swing high 11.0
      (10.3, 10.4, 9.8, 9.9),     # 2 swing low 9.8
      (9.9, 11.5, 9.9, 11.2),     # 3 swing high 11.5
      (11.2, 11.3, 10.5, 10.6),   # 4 bearish
      (10.6, 10.9, 10.2, 10.3)]   # 5 bearish, swing low 10.2
ENGULF = (10.3, 11.1, 10.25, 11.0)      # bullish engulfing: open <= 10.3 (prev close), close >= 10.6 (prev open)
PIN = (10.9, 11.05, 10.25, 11.0)        # bullish pin bar: lower wick 0.65 >= 2 x body 0.1 and >= half the range; close in top third
NOSIG = (10.3, 10.6, 10.25, 10.5)       # bullish but covers neither the previous body nor is a pin bar
# ATR(2) at the signal candle with ENGULF: TRs 0.7 and 0.85 -> 0.775; stop = 10.25 - 0.25 x 0.775 = 10.05625
# entry fill = open 11.0 + half (spread 0.02 / 2 + slippage 0.01 = 0.02) = 11.02; stop distance 0.96375; target 11.02 + 1.9275 = 12.9475
# equity 1,000,000: risk 10,000 / (0.96375 x 100,000) = 0.1038 lots -> 0.10 lot; risk in dollars 0.10 x 96,375 = 9,637.5
HAND = dict(swing_n=1, atr_n=2, warmup=0, equity0=1_000_000.0)


def mk(candles, start="2024-01-01 00:00", swl=-10.0, sws=-20.0):
    idx = pd.date_range(start, periods=len(candles), freq="4h")
    df = pd.DataFrame(candles, columns=["open", "high", "low", "close"], index=idx)
    return Pair("X", df, False, 0.02, 0.01, swl, sws, 1.0)


def run1(candles, start="2024-01-01 00:00", **kw):
    return run_pa([mk(candles, start)], PACfg(**{**HAND, **kw})).trades


def mirror(candles):
    return [(20 - o, 20 - l, 20 - h, 20 - c) for (o, h, l, c) in candles]


def check_units():
    ok = True

    def expect(label, cond):
        nonlocal ok
        if not cond:
            print(f"   FAIL: {label}")
        ok &= bool(cond)

    # --- H1 -> H4 grouping
    idx = pd.date_range("2024-01-01 00:00", periods=8, freq="h")
    h1 = pd.DataFrame({"open": [1, 2, 3, 4, 5, 6, 7, 8.0], "high": [2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5],
                       "low": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5], "close": [2, 3, 4, 5, 6, 7, 8, 9.0]}, index=idx)
    h4 = to_h4(h1)
    expect("H4: two candles at 00:00 and 04:00", list(h4.index) == [pd.Timestamp("2024-01-01 00:00"), pd.Timestamp("2024-01-01 04:00")])
    expect("H4 first candle o=1 h=5.5 l=0.5 c=5", list(h4.iloc[0]) == [1.0, 5.5, 0.5, 5.0])
    expect("H4 second candle o=5 h=9.5 l=4.5 c=9", list(h4.iloc[1]) == [5.0, 9.5, 4.5, 9.0])
    h1b = h1.iloc[2:].copy()                                                   # starts at 02:00 -> first block has 2 hours
    h4b = to_h4(h1b)
    expect("H4 partial first block (02:00-03:59) is its own candle", len(h4b) == 2 and h4b.iloc[0].open == 3.0 and h4b.iloc[0].close == 5.0)

    # --- long, target hit in candle 8
    tail = [(11.0, 11.3, 10.9, 11.2), (11.2, 13.0, 11.1, 12.9)]
    tr = run1(UP + [ENGULF] + tail)
    expect("target: exactly one trade", len(tr) == 1)
    if len(tr):
        t = tr.iloc[0]
        expect("target: long, engulfing, reason target", t.dir == 1 and t.pat == "engulf" and t.reason == "target")
        expect("target: entry on candle 7 (04:00 Tue)", t.entry_date == pd.Timestamp("2024-01-02 04:00"))
        expect("target: exit on candle 8 (08:00 Tue)", t.exit_date == pd.Timestamp("2024-01-02 08:00"))
        expect("target: lots 0.10", t.lots == 0.1)
        expect("target: entry fill 11.02", close_to(t.entry_px, 11.02))
        expect("target: exit fill 12.9275 (target 12.9475 minus half)", close_to(t.exit_px, 12.9275))
        expect("target: risk $9,637.50", close_to(t.risk_usd, 9637.5))
        expect("target: net $19,075 (no swap: no 20:00 candle held)", close_to(t.pnl_usd, 19075.0) and t.swap_usd == 0.0)
        expect("target: R = 19075 / 9637.5", close_to(t.R, 19075.0 / 9637.5))
        expect("target: costs = 2 x 0.10 x 100000 x 0.02 = $400", close_to(t.cost_usd, 400.0))

    # --- stop and target both reachable inside candle 7 -> stop first
    tr = run1(UP + [ENGULF] + [(11.0, 13.0, 10.0, 11.5)])
    t = tr.iloc[0] if len(tr) else None
    expect("stop-first: one trade, reason stop", t is not None and len(tr) == 1 and t.reason == "stop")
    if t is not None:
        expect("stop-first: exit fill 10.03625 (stop 10.05625 minus half)", close_to(t.exit_px, 10.03625))
        expect("stop-first: net -$9,837.50", close_to(t.pnl_usd, -9837.5))
        expect("stop-first: R = -9837.5 / 9637.5", close_to(t.R, -9837.5 / 9637.5))

    # --- gap through the stop at the open of candle 8
    tr = run1(UP + [ENGULF] + [(11.0, 11.2, 10.9, 11.0), (10.0, 10.2, 9.9, 10.1)])
    t = tr.iloc[0] if len(tr) else None
    expect("gap stop: reason stop_gap, fill 9.98, net -$10,400",
           t is not None and t.reason == "stop_gap" and close_to(t.exit_px, 9.98) and close_to(t.pnl_usd, -10400.0))

    # --- gap through the target at the open of candle 8
    tr = run1(UP + [ENGULF] + [(11.0, 11.2, 10.9, 11.0), (13.0, 13.2, 12.9, 13.1)])
    t = tr.iloc[0] if len(tr) else None
    expect("gap target: reason target_gap, fill 12.98, net $19,600",
           t is not None and t.reason == "target_gap" and close_to(t.exit_px, 12.98) and close_to(t.pnl_usd, 19600.0))

    # --- time exit: max 2 candles; exit at the open of candle 9
    tr = run1(UP + [ENGULF] + [(11.0, 11.3, 10.9, 11.2), (11.2, 11.6, 11.0, 11.5), (11.5, 11.7, 11.4, 11.6)], max_bars=2)
    t = tr.iloc[0] if len(tr) else None
    expect("time exit: reason time, fill 11.48, net $4,600, 2 candles held",
           t is not None and t.reason == "time" and close_to(t.exit_px, 11.48) and close_to(t.pnl_usd, 4600.0) and t.bars == 2)

    # --- no signal when the signal candle is neither engulfing nor a pin bar
    tr = run1(UP + [NOSIG] + [(10.5, 10.9, 10.4, 10.7), (10.7, 11.0, 10.6, 10.9)])
    expect("no pattern -> no trade", len(tr) == 0)

    # --- pin bar signal (stop = 10.25 - 0.25 x 0.75 = 10.0625, target 11.02 + 2 x 0.9575 = 12.935)
    tr = run1(UP + [PIN] + [(11.0, 11.3, 10.9, 11.2), (11.2, 13.5, 11.1, 13.4)])
    t = tr.iloc[0] if len(tr) else None
    expect("pin bar: one long trade, pattern pin, target hit", t is not None and len(tr) == 1 and t.pat == "pin" and t.dir == 1 and t.reason == "target")

    # --- short side is the exact mirror image: same dollars, direction -1, entry fill 8.98, exit fill 7.0725
    tr = run1(mirror(UP + [ENGULF] + tail))
    t = tr.iloc[0] if len(tr) else None
    expect("mirror: one short trade", t is not None and len(tr) == 1 and t.dir == -1 and t.pat == "engulf")
    if t is not None:
        expect("mirror: entry fill 8.98, exit fill 7.0725", close_to(t.entry_px, 8.98) and close_to(t.exit_px, 7.0725))
        expect("mirror: net +$19,075", close_to(t.pnl_usd, 19075.0))

    # --- Wednesday triple swap: candle 10 is Wednesday 20:00; the long is open at its close -> 3 x (-10 pts x 1.0 x 0.10 lot) = -3.0
    held = [(11.0, 11.3, 10.9, 11.1)] * 5 + [(11.0, 11.2, 10.9, 11.0)]
    tr = run1(UP + [ENGULF] + held, start="2024-01-02 04:00", max_bars=5)
    t = tr.iloc[0] if len(tr) else None
    expect("swap: held over Wednesday 20:00 -> -$3.00, exit by time", t is not None and close_to(t.swap_usd, -3.0) and t.reason == "time")
    if t is not None:
        expect("swap: net = price result minus 3.00", close_to(t.pnl_usd, 10000.0 * ((11.0 - 0.02) - 11.02) - 3.0))
    log(f"U) hand-worked candles and trades: {'PASS' if ok else 'FAIL'}")
    return ok


# ------------------------------------------------------------------ synthetic data ---------------------
def synth_h4(seed, years=8, px0=1.1, annual_vol=0.08, start="2005-01-03"):
    """Random-walk hourly candles built from 4 sub-steps per hour (so highs and lows are real path extremes), grouped into H4."""
    rng = np.random.default_rng(seed)
    full = pd.date_range(start, periods=24 * 7 * 52 * years, freq="h")
    idx = full[full.weekday < 5]
    nh = len(idx)
    shock = rng.standard_normal(nh)
    lv = np.zeros(nh)
    for i in range(1, nh):
        lv[i] = 0.995 * lv[i - 1] + 0.05 * shock[i]
    sd = annual_vol / math.sqrt(252 * 24) * np.exp(lv - lv.var() / 2)
    steps = rng.standard_normal((nh, 4)) * (sd / 2)[:, None]
    start_lp = math.log(px0) + np.concatenate([[0.0], np.cumsum(steps.sum(1))[:-1]])
    path = start_lp[:, None] + np.concatenate([np.zeros((nh, 1)), np.cumsum(steps, axis=1)], axis=1)
    h1 = pd.DataFrame({"open": np.exp(path[:, 0]), "high": np.exp(path.max(1)), "low": np.exp(path.min(1)),
                       "close": np.exp(path[:, 4])}, index=idx)
    return to_h4(h1)


def synth_book(seed, years=8, costs=False, k=4):
    out = []
    for j in range(k):
        ub = (j % 3 == 2)
        sc = 100.0 if ub else 1.0
        out.append(Pair(f"P{j}", synth_h4(seed * 10 + j, years, px0=110.0 if ub else 1.1), ub,
                        (0.0001 * sc) if costs else 0.0, (0.00001 * sc) if costs else 0.0,
                        -0.7 if costs else 0.0, -1.0 if costs else 0.0, 0.7 if ub else 1.0))
    return out


# ------------------------------------------------------------------ independent reference ---------------
def reference(pair, cfg):
    """One pair, plain lists, brute-force swing search. Same rules as the engine, deliberately different code."""
    d = pair.df
    ts = list(d.index)
    O = [float(x) for x in d["open"]]
    H = [float(x) for x in d["high"]]
    L = [float(x) for x in d["low"]]
    C = [float(x) for x in d["close"]]
    n = len(C)
    w = cfg.swing_n
    half = (pair.spread / 2 + pair.slip) * cfg.cost_mult
    tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
    is_sh = [False] * n
    is_sl = [False] * n
    for i in range(w, n - w):
        is_sh[i] = all(H[i] > H[i - k] and H[i] > H[i + k] for k in range(1, w + 1))
        is_sl[i] = all(L[i] < L[i - k] and L[i] < L[i + k] for k in range(1, w + 1))

    def last_two(flags, vals, t):
        out = []
        for i in range(t - w, w - 1, -1):
            if flags[i]:
                out.append(vals[i])
                if len(out) == 2:
                    break
        return out

    def usd(q, px):
        return q / px if pair.usd_base else q

    def signal(t):
        if t < max(cfg.warmup, cfg.pull_n + 1) or t < cfg.atr_n - 1:
            return 0, None, None
        a = sum(tr[t - cfg.atr_n + 1:t + 1]) / cfg.atr_n
        hs, ls = last_two(is_sh, H, t), last_two(is_sl, L, t)
        if len(hs) < 2 or len(ls) < 2:
            return 0, None, None
        o, h, l, c, po, pc = O[t], H[t], L[t], C[t], O[t - 1], C[t - 1]
        rng, body = h - l, abs(c - o)
        if rng <= 0:
            return 0, None, None
        kind, name = 0, None
        if c > o and pc < po and o <= pc and c >= po:
            kind, name = 1, "engulf"
        elif c < o and pc > po and o >= pc and c <= po:
            kind, name = -1, "engulf"
        elif body > 0:
            lw, uw = min(o, c) - l, h - max(o, c)
            if lw >= 2 * body and lw >= 0.5 * rng and (c - l) >= 2.0 / 3.0 * rng:
                kind, name = 1, "pin"
            elif uw >= 2 * body and uw >= 0.5 * rng and (h - c) >= 2.0 / 3.0 * rng:
                kind, name = -1, "pin"
        if kind > 0 and hs[0] > hs[1] and ls[0] > ls[1] and all(C[t - k] < O[t - k] for k in range(1, cfg.pull_n + 1)):
            return 1, l - cfg.atr_pad * a, name
        if kind < 0 and hs[0] < hs[1] and ls[0] < ls[1] and all(C[t - k] > O[t - k] for k in range(1, cfg.pull_n + 1)):
            return -1, h + cfg.atr_pad * a, name
        return 0, None, None

    bal = cfg.equity0
    peak = bal
    pos = None
    pend = None
    pend_exit = False
    halted = False
    day, day_open = None, None
    out = []

    def close(t, mid):
        nonlocal bal, pos
        px = mid - pos["d"] * half
        g = usd(pos["d"] * pos["lots"] * CONTRACT * (px - pos["entry"]), px)
        bal += g
        out.append((pos["et"], ts[t], pos["lots"], pos["entry"], px, g + pos["swap"]))
        pos = None

    for t in range(n):
        if halted:
            continue
        if pend_exit and pos is not None:
            close(t, O[t])
        pend_exit = False
        eq_open = bal + (0.0 if pos is None else usd(pos["d"] * pos["lots"] * CONTRACT * (O[t] - pos["entry"]), O[t]))
        date = ts[t].normalize()
        if date != day:
            day, day_open = date, eq_open
        no_entry = eq_open <= day_open * (1 - cfg.day_loss)
        if pend is not None and pos is None and not no_entry:
            dd, st, _ = pend
            fill = O[t] + dd * half
            if not ((dd > 0 and fill <= st) or (dd < 0 and fill >= st)):
                sd = abs(fill - st)
                rpl = usd(sd * CONTRACT, fill)
                lots = math.floor(eq_open * cfg.risk / rpl / cfg.lot_step + 1e-9) * cfg.lot_step
                if lots < cfg.lot_step - 1e-12:
                    lots = cfg.lot_step if cfg.lot_step * rpl <= cfg.min_lot_risk_cap * eq_open else 0.0
                if lots > 0:
                    pos = dict(d=dd, lots=round(lots, 2), entry=fill, stop=st, target=fill + dd * cfg.rr * sd,
                               swap=0.0, bars=0, et=ts[t])
        pend = None
        if pos is not None:
            pos["bars"] += 1
            o, h, l = O[t], H[t], L[t]
            if pos["d"] > 0:
                if o <= pos["stop"]:
                    close(t, o)
                elif o >= pos["target"]:
                    close(t, o)
                elif l <= pos["stop"]:
                    close(t, pos["stop"])
                elif h >= pos["target"]:
                    close(t, pos["target"])
            else:
                if o >= pos["stop"]:
                    close(t, o)
                elif o <= pos["target"]:
                    close(t, o)
                elif h >= pos["stop"]:
                    close(t, pos["stop"])
                elif l <= pos["target"]:
                    close(t, pos["target"])
        if pos is not None and ts[t].hour == 20:
            pts = pair.swap_long if pos["d"] > 0 else pair.swap_short
            v = pts * pair.tick_value * pos["lots"]
            v = (v if cfg.swap_credit else 0.0) if v > 0 else v * cfg.swap_mult
            v *= 3 if ts[t].weekday() == 2 else 1
            pos["swap"] += v
            bal += v
        e = bal + (0.0 if pos is None else usd(pos["d"] * pos["lots"] * CONTRACT * (C[t] - pos["entry"]), C[t]))
        peak = max(peak, e)
        if e <= peak * (1 - cfg.dd_stop):
            if pos is not None:
                close(t, C[t])
            halted = True
            continue
        if pos is not None:
            if pos["bars"] >= cfg.max_bars:
                pend_exit = True
        else:
            s, st, nm = signal(t)
            if s != 0:
                pend = (s, st, nm)
    if pos is not None and not halted:
        close(n - 1, C[n - 1])
    return out


def check_reference():
    bad = 0
    total = 0
    for seed in range(4):
        ub = seed % 2 == 1
        df = synth_h4(300 + seed, years=4, px0=110.0 if ub else 1.1, annual_vol=0.10)
        p = Pair("R", df, ub, 0.01 if ub else 0.0001, 0.001 if ub else 0.00001, -0.7, -1.0, 0.7 if ub else 1.0)
        cfg = PACfg(equity0=500.0 if seed == 3 else 10_000.0, dd_stop=0.5)
        eng = run_pa([p], cfg).trades
        ref = reference(p, cfg)
        total += len(ref)
        if len(eng) != len(ref):
            print(f"   seed {seed}: engine {len(eng)} trades, reference {len(ref)}")
            bad += 1
            continue
        for k, rr in enumerate(ref):
            e = eng.iloc[k]
            same = (rr[0] == e.entry_date and rr[1] == e.exit_date and abs(rr[2] - e.lots) < 1e-12
                    and close_to(e.entry_px, rr[3], 1e-12) and close_to(e.exit_px, rr[4], 1e-12) and close_to(e.pnl_usd, rr[5], 1e-9))
            if not same:
                print(f"   seed {seed} trade {k}: engine {tuple(e[['entry_date', 'exit_date', 'lots', 'entry_px', 'exit_px', 'pnl_usd']])} vs reference {rr}")
                bad += 1
                break
        log(f"   ... reference seed {seed} done ({len(ref)} trades)")
    ok = bad == 0 and total >= 30
    log(f"A) independent reference vs engine, 4 runs, {total} trades compared (costs, swap, USD-base, small account): {'PASS' if ok else 'FAIL'}")
    return ok


# ------------------------------------------------------------------ random-walk checks ---------------------
def neutral_R(n_runs=16, **kw):
    means, counts = [], []
    for s in range(n_runs):
        r = run_pa(synth_book(900 + s), PACfg(dd_stop=0.99, day_loss=0.99, **kw))
        if len(r.trades):
            means.append(r.trades.R.mean())
            counts.append(len(r.trades))
        if (s + 1) % 4 == 0:
            log(f"   ... {s + 1}/{n_runs} random-walk portfolios done")
    return np.array(means), np.array(counts)


def check_neutrality():
    m, c = neutral_R()
    se = m.std(ddof=1) / math.sqrt(len(m))
    ok = abs(m.mean()) < 3 * se or abs(m.mean()) < 0.04
    log(f"B) zero-cost random walks, {len(m)} portfolios x 4 pairs x 8 years, {int(c.sum())} trades: mean R {m.mean():+.3f} "
        f"(s.e. {se:.3f})  {'PASS' if ok else 'FAIL'}")
    return ok, m


def check_mutation(base):
    m, c = neutral_R(_bug_peek=6)
    se = math.sqrt(m.std(ddof=1) ** 2 / len(m) + base.std(ddof=1) ** 2 / len(base))
    det = (m.mean() - base.mean()) > 4 * se and m.mean() > 0.10
    log(f"C) mutation: signal peeks 6 candles ahead -> mean R {m.mean():+.3f} (neutral {base.mean():+.3f})  "
        f"{'DETECTED' if det else 'NOT DETECTED'}")
    return det


def check_costs():
    free = run_pa(synth_book(5, years=6, costs=False), PACfg(dd_stop=0.99, day_loss=0.99))
    base = run_pa(synth_book(5, years=6, costs=True), PACfg(dd_stop=0.99, day_loss=0.99))
    harsh = run_pa(synth_book(5, years=6, costs=True), PACfg(dd_stop=0.99, day_loss=0.99, cost_mult=2.0, swap_mult=2.0, swap_credit=False))
    e = lambda r: r.equity.iloc[-1]
    ok = e(free) > e(base) > e(harsh) and base.cost_usd > 0 and base.swap_usd < 0 and harsh.cost_usd > base.cost_usd
    log(f"D) costs: end equity free {e(free):,.0f} > realistic {e(base):,.0f} > harsh {e(harsh):,.0f}; "
        f"costs ${base.cost_usd:,.0f}, swap ${base.swap_usd:,.0f}  {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    ok = check_units()
    ok &= check_reference()
    okn, base = check_neutrality()
    ok &= okn
    ok &= check_mutation(base)
    ok &= check_costs()
    print(f"\nOVERALL: {'ALL CHECKS PASSED' if ok else 'SOMETHING IS WRONG - do not trust results from this engine'}  ({time.time() - T0:.0f}s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
