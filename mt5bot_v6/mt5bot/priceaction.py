"""Price-action engine on H4 candles (pre-registered test #6, see PREREGISTRATION_6_LOCKED.md).

Rules (one specification, nothing tuned):
  swings  : a swing high has a strictly higher high than each of the 3 candles before and the 3 after it; usable once the 3rd
            candle after it has closed. Swing low = mirror.
  trend   : uptrend = last two swing highs strictly rising AND last two swing lows strictly rising; downtrend = the reverse
  pullback: the 2 candles right before the signal candle are both bearish (long) / both bullish (short)
  signal  : bullish engulfing or bullish pin bar (long); bearish engulfing / bearish pin bar (short); see _classify
  entry   : at the next candle's open (this pair's next candle)
  stop    : signal low - 0.25 x ATR(14)  (high + 0.25 x ATR for shorts); trade skipped if the entry is already beyond it
  target  : entry fill + 2 x (entry fill - stop); stop is assumed first when both are reachable inside one candle
  exit    : stop, target, or time exit at the open after 20 candles
  size    : 1% of equity at the open, rounded DOWN to 0.01 lot; minimum lot allowed if it risks <= 2%
  limits  : max 3 open; no new entries on a UTC day once equity is 3% below its value at that day's first candle;
            the strategy halts at a 20% drawdown from its peak
  costs   : every fill pays half spread + slippage; one swap night for each position open at the close of the 20:00 UTC
            candle (triple on Wednesday-dated candles)
Prices are treated as mid prices. Nothing here touches MT5.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mt5bot.pullback import CONTRACT, Pair, _usd, size_lots


@dataclass
class PACfg:
    equity0: float = 10_000.0
    risk: float = 0.01
    swing_n: int = 3
    atr_n: int = 14
    atr_pad: float = 0.25
    rr: float = 2.0
    pull_n: int = 2
    max_bars: int = 20
    warmup: int = 100
    max_pos: int = 3
    day_loss: float = 0.03
    dd_stop: float = 0.20
    min_lot_risk_cap: float = 0.02
    lot_step: float = 0.01
    cost_mult: float = 1.0
    swap_mult: float = 1.0
    swap_credit: bool = True
    _bug_peek: int = 0              # TEST ONLY: the signal also requires the close this many candles ahead to agree


@dataclass
class PAResult:
    equity: pd.Series
    trades: pd.DataFrame
    skipped_min_lot: int
    skipped_slots: int
    skipped_stop: int
    halted_on: object
    cost_usd: float
    swap_usd: float


def to_h4(h1: pd.DataFrame) -> pd.DataFrame:
    """Hourly candles (index = UTC open time; columns open, high, low, close) -> H4 candles on 00/04/08/12/16/20 UTC blocks."""
    g = h1.resample("4h", label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
    return out.dropna()


def _classify(o, h, l, c, po, pc):
    """Return (+1 or -1, pattern name) if the candle (o,h,l,c) after the previous candle (open po, close pc) is a bullish /
    bearish engulfing or pin bar; otherwise (0, '')."""
    rng = h - l
    body = abs(c - o)
    if rng <= 0:
        return 0, ""
    if c > o and pc < po and o <= pc and c >= po:
        return 1, "engulf"
    if c < o and pc > po and o >= pc and c <= po:
        return -1, "engulf"
    if body > 0:
        lw = min(o, c) - l
        if lw >= 2 * body and lw >= 0.5 * rng and (c - l) >= (2.0 / 3.0) * rng:
            return 1, "pin"
        uw = h - max(o, c)
        if uw >= 2 * body and uw >= 0.5 * rng and (h - c) >= (2.0 / 3.0) * rng:
            return -1, "pin"
    return 0, ""


def signals(df: pd.DataFrame, cfg: PACfg):
    """Per-candle signal arrays computed from data up to and including each candle's close."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    w = cfg.swing_n
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    if n > 1:
        tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = pd.Series(tr).rolling(cfg.atr_n, min_periods=cfg.atr_n).mean().to_numpy()
    sh, sl = [], []
    d = np.zeros(n, int)                     # +1 long signal, -1 short signal
    stop = np.full(n, np.nan)
    pat = np.full(n, "", dtype=object)
    for t in range(n):
        i = t - w
        if i >= w:                           # the swing at i becomes known at the close of candle i + w = t
            if h[i] > h[i - w:i].max() and h[i] > h[i + 1:i + w + 1].max():
                sh.append(h[i])
            if l[i] < l[i - w:i].min() and l[i] < l[i + 1:i + w + 1].min():
                sl.append(l[i])
        if t < max(cfg.warmup, cfg.pull_n + 1) or not np.isfinite(atr[t]) or len(sh) < 2 or len(sl) < 2:
            continue
        s, name = _classify(o[t], h[t], l[t], c[t], o[t - 1], c[t - 1])
        if s == 0:
            continue
        if s > 0:
            ok = sh[-1] > sh[-2] and sl[-1] > sl[-2] and all(c[t - k] < o[t - k] for k in range(1, cfg.pull_n + 1))
            if ok and cfg._bug_peek:
                ok = t + cfg._bug_peek < n and c[t + cfg._bug_peek] > c[t]
            if ok:
                d[t], stop[t], pat[t] = 1, l[t] - cfg.atr_pad * atr[t], name
        else:
            ok = sh[-1] < sh[-2] and sl[-1] < sl[-2] and all(c[t - k] > o[t - k] for k in range(1, cfg.pull_n + 1))
            if ok and cfg._bug_peek:
                ok = t + cfg._bug_peek < n and c[t + cfg._bug_peek] < c[t]
            if ok:
                d[t], stop[t], pat[t] = -1, h[t] + cfg.atr_pad * atr[t], name
    return d, stop, pat


def run_pa(pairs: list[Pair], cfg: PACfg, log=None) -> PAResult:
    idx = pairs[0].df.index
    for p in pairs[1:]:
        idx = idx.union(p.df.index)
    idx = idx.sort_values()
    T = len(idx)
    A = {}
    for p in pairs:
        d, stop, pat = signals(p.df, cfg)
        A[p.name] = dict(O=p.df["open"].reindex(idx).to_numpy(float), H=p.df["high"].reindex(idx).to_numpy(float),
                         L=p.df["low"].reindex(idx).to_numpy(float), C=p.df["close"].reindex(idx).to_numpy(float),
                         D=pd.Series(d, index=p.df.index).reindex(idx).fillna(0).to_numpy(int),
                         S=pd.Series(stop, index=p.df.index).reindex(idx).to_numpy(float),
                         P=pd.Series(pat, index=p.df.index).reindex(idx).fillna("").to_numpy(object))
    half = {p.name: (p.spread / 2 + p.slip) * cfg.cost_mult for p in pairs}
    pmap = {p.name: p for p in pairs}
    hours = idx.hour.to_numpy()
    wdays = idx.weekday.to_numpy()
    dates = idx.normalize()

    bal = cfg.equity0
    peak = bal
    pos, pend_entry, pend_exit = {}, {}, set()
    eq = np.full(T, np.nan)
    trades = []
    sk_lot = sk_slot = sk_stop = 0
    cost_tot = swap_tot = 0.0
    halted = None
    last_close = {p.name: np.nan for p in pairs}
    day_key, day_open_eq = None, bal

    def unreal(n, px):
        po = pos[n]
        return _usd(po["d"] * po["lots"] * CONTRACT * (px - po["entry"]), px, pmap[n].usd_base)

    def close_pos(n, t, mid, reason):
        nonlocal bal, cost_tot
        po = pos.pop(n)
        p = pmap[n]
        px = mid - po["d"] * half[n]
        gross = _usd(po["d"] * po["lots"] * CONTRACT * (px - po["entry"]), px, p.usd_base)
        cexit = _usd(po["lots"] * CONTRACT * half[n], px, p.usd_base)
        bal += gross
        cost_tot += cexit
        net = gross + po["swap"]
        trades.append(dict(pair=n, dir=po["d"], pat=po["pat"], entry_date=po["edate"], exit_date=idx[t], lots=po["lots"],
                           entry_px=po["entry"], exit_px=px, reason=reason, bars=po["bars"], risk_usd=po["risk"],
                           pnl_usd=net, swap_usd=po["swap"], cost_usd=po["centry"] + cexit, R=net / po["risk"]))

    for t in range(T):
        if log and t % 20000 == 0:
            log(f"  candle {t}/{T} {idx[t]} balance ${bal:,.0f} trades {len(trades)}")
        if halted is not None:
            eq[t] = bal
            continue
        today = [p.name for p in pairs if np.isfinite(A[p.name]["C"][t])]
        # 1. time exits decided at the previous close, executed at this candle's open
        for n in [n for n in today if n in pend_exit]:
            if n in pos:
                close_pos(n, t, A[n]["O"][t], "time")
            pend_exit.discard(n)
        # 2. equity at the open; daily loss check
        eq_open = bal + sum(unreal(n, A[n]["O"][t] if n in today else last_close[n]) for n in pos)
        if dates[t] != day_key:
            day_key, day_open_eq = dates[t], eq_open
        no_entry = eq_open <= day_open_eq * (1 - cfg.day_loss)
        # 3. entries decided at the previous close of this pair, fixed priority order
        for p in pairs:
            n = p.name
            if n not in pend_entry or n not in today:
                continue
            d, st, pt = pend_entry.pop(n)
            if no_entry or n in pos:
                continue
            if len(pos) >= cfg.max_pos:
                sk_slot += 1
                continue
            fill = A[n]["O"][t] + d * half[n]
            if (d > 0 and fill <= st) or (d < 0 and fill >= st):
                sk_stop += 1
                continue
            sd = abs(fill - st)
            rpl = _usd(sd * CONTRACT, fill, p.usd_base)
            lots = size_lots(eq_open, rpl, cfg)
            if lots is None:
                sk_lot += 1
                continue
            cent = _usd(lots * CONTRACT * half[n], fill, p.usd_base)
            cost_tot += cent
            pos[n] = dict(d=d, lots=lots, entry=fill, stop=st, target=fill + d * cfg.rr * sd, risk=lots * rpl, swap=0.0,
                          edate=idx[t], centry=cent, bars=0, pat=pt)
        # 4. stop / target inside the candle (stop first when both are reachable)
        for n in list(pos):
            if n not in today:
                continue
            po = pos[n]
            po["bars"] += 1
            o, h, l = A[n]["O"][t], A[n]["H"][t], A[n]["L"][t]
            if po["d"] > 0:
                if o <= po["stop"]:
                    close_pos(n, t, o, "stop_gap")
                elif o >= po["target"]:
                    close_pos(n, t, o, "target_gap")
                elif l <= po["stop"]:
                    close_pos(n, t, po["stop"], "stop")
                elif h >= po["target"]:
                    close_pos(n, t, po["target"], "target")
            else:
                if o >= po["stop"]:
                    close_pos(n, t, o, "stop_gap")
                elif o <= po["target"]:
                    close_pos(n, t, o, "target_gap")
                elif h >= po["stop"]:
                    close_pos(n, t, po["stop"], "stop")
                elif l <= po["target"]:
                    close_pos(n, t, po["target"], "target")
        # 5. swap: the 20:00 UTC candle covers the 22:00 rollover
        if hours[t] == 20:
            for n in pos:
                if n in today:
                    p = pmap[n]
                    pts = p.swap_long if pos[n]["d"] > 0 else p.swap_short
                    v = pts * p.tick_value * pos[n]["lots"]
                    v = (v if cfg.swap_credit else 0.0) if v > 0 else v * cfg.swap_mult
                    v *= 3 if wdays[t] == 2 else 1
                    pos[n]["swap"] += v
                    bal += v
                    swap_tot += v
        for n in today:
            last_close[n] = A[n]["C"][t]
        # 6. mark to market at the close; drawdown halt
        e = bal + sum(unreal(n, last_close[n]) for n in pos)
        peak = max(peak, e)
        if e <= peak * (1 - cfg.dd_stop):
            for n in list(pos):
                close_pos(n, t, last_close[n], "dd_halt")
            halted = idx[t]
            e = bal
        eq[t] = e
        if halted is not None:
            continue
        # 7. signals at this close for this pair's next candle; time exits
        for p in pairs:
            n = p.name
            if n not in today:
                continue
            if n in pos:
                if pos[n]["bars"] >= cfg.max_bars:
                    pend_exit.add(n)
            elif n not in pend_entry and A[n]["D"][t] != 0:
                pend_entry[n] = (int(A[n]["D"][t]), A[n]["S"][t], A[n]["P"][t])
    if halted is None:
        for n in list(pos):
            close_pos(n, T - 1, last_close[n], "end")
        eq[T - 1] = bal
    return PAResult(pd.Series(eq, index=idx), pd.DataFrame(trades), sk_lot, sk_slot, sk_stop, halted, cost_tot, swap_tot)


def pa_stats(res: PAResult, seed: int = 12345) -> dict:
    tr = res.trades
    eq = res.equity.ffill()
    daily = eq.resample("1D").last().dropna()
    r = daily.pct_change().dropna()
    out = {"trades": int(len(tr)), "skipped_min_lot": res.skipped_min_lot, "skipped_slots": res.skipped_slots,
           "skipped_stop": res.skipped_stop, "halted_on": res.halted_on,
           "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if len(r) > 2 and r.std() > 0 else float("nan"),
           "max_dd_pct": float((eq / eq.cummax() - 1).min() * 100), "end_equity": float(eq.iloc[-1])}
    if len(tr):
        R = tr["R"].to_numpy()
        out["mean_R"] = float(R.mean())
        rng = np.random.default_rng(seed)
        out["mean_R_lb95"] = float(np.percentile(rng.choice(R, size=(5_000, len(R)), replace=True).mean(axis=1), 2.5))
        w, l = tr.loc[tr.pnl_usd > 0, "pnl_usd"].sum(), -tr.loc[tr.pnl_usd < 0, "pnl_usd"].sum()
        out["profit_factor"] = float(w / l) if l > 0 else float("inf")
        out["win_rate"] = float((tr.pnl_usd > 0).mean())
    return out
