"""Daily trend-pullback engine on FX majors (pre-registered test #4, see PREREGISTRATION_4_LOCKED.md).

Rules (one specification, nothing tuned):
  trend    : long only if close > SMA(200), short only if close < SMA(200)
  entry    : long when close > EMA(20) today and close < EMA(20) on at least one of the previous 5 bars (mirror for short);
             signal at the close, fill at the NEXT bar's open
  stop     : 2 x ATR(14) (simple mean of true range) from the fill price, fixed at entry
  exit     : close crosses back through EMA(20) against the trade -> exit at the next open; or stop (gap -> the open)
  size     : risk 1% of equity at the open, rounded DOWN to 0.01 lot; if that is < 0.01 lot, take 0.01 only if it risks <= 2%
  limits   : 1 position per pair, max 3 open, no new entries if equity fell 3% from the previous close to this open,
             strategy halts (and closes) at a 20% drawdown from peak
  costs    : half spread + slippage at every fill; swap per night (triple on Wednesday-dated close); P&L of USD-base pairs
             (quote currency JPY/CAD/CHF) converted to USD at the pair's own price
All prices are treated as mid prices. Nothing here touches MT5.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

CONTRACT = 100_000.0


@dataclass
class Pair:
    name: str
    df: pd.DataFrame          # columns open, high, low, close; index = bar date (the date the 22:00 UTC bar closes)
    usd_base: bool            # quote currency is not USD (USDJPY, USDCAD, USDCHF)
    spread: float             # price units, full spread
    slip: float               # price units, per fill
    swap_long: float          # broker points per lot per night
    swap_short: float
    tick_value: float         # USD per point per lot


@dataclass
class PCfg:
    equity0: float = 10_000.0
    risk: float = 0.01
    sma: int = 200
    ema: int = 20
    atr_n: int = 14
    atr_mult: float = 2.0
    recent: int = 5
    max_pos: int = 3
    day_loss: float = 0.03
    dd_stop: float = 0.20
    min_lot_risk_cap: float = 0.02
    lot_step: float = 0.01
    cost_mult: float = 1.0
    swap_mult: float = 1.0          # multiplies negative swap
    swap_credit: bool = True        # False: positive swap is ignored (harsh case)
    _bug_peek: bool = False         # TEST ONLY: signal peeks at the next day's close


@dataclass
class PResult:
    equity: pd.Series
    trades: pd.DataFrame
    skipped_min_lot: int
    skipped_slots: int
    halted_on: object
    cost_usd: float
    swap_usd: float


def _indicators(p: Pair, cfg: PCfg):
    d = p.df
    c, h, l = d["close"], d["high"], d["low"]
    sma = c.rolling(cfg.sma, min_periods=cfg.sma).mean()
    ema = c.ewm(span=cfg.ema, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    tr.iloc[0] = h.iloc[0] - l.iloc[0]
    atr = tr.rolling(cfg.atr_n, min_periods=cfg.atr_n).mean()
    below = pd.concat([(c.shift(k) < ema.shift(k)) for k in range(1, cfg.recent + 1)], axis=1).any(axis=1)
    above = pd.concat([(c.shift(k) > ema.shift(k)) for k in range(1, cfg.recent + 1)], axis=1).any(axis=1)
    valid = sma.notna() & atr.notna()
    long_f = valid & (c > sma) & (c > ema) & below
    short_f = valid & (c < sma) & (c < ema) & above
    if cfg._bug_peek:
        nxt = c.shift(-1)
        long_f &= nxt > c
        short_f &= nxt < c
    return ema, atr, long_f, short_f


def size_lots(equity: float, risk_per_lot_usd: float, cfg: PCfg):
    """Lots for 1% risk rounded DOWN to the lot step; falls back to the minimum lot if that risks <= 2%; else None."""
    raw = equity * cfg.risk / risk_per_lot_usd
    lots = np.floor(raw / cfg.lot_step + 1e-9) * cfg.lot_step
    if lots >= cfg.lot_step - 1e-12:
        return round(float(lots), 2)
    if cfg.lot_step * risk_per_lot_usd <= cfg.min_lot_risk_cap * equity:
        return cfg.lot_step
    return None


def _usd(q, px, usd_base):
    return q / px if usd_base else q


def run_pullback(pairs: list[Pair], cfg: PCfg) -> PResult:
    idx = pairs[0].df.index
    for p in pairs[1:]:
        idx = idx.union(p.df.index)
    idx = idx.sort_values()
    T = len(idx)
    A = {}
    for p in pairs:
        ema, atr, lf, sf = _indicators(p, cfg)
        A[p.name] = dict(
            O=p.df["open"].reindex(idx).to_numpy(float), H=p.df["high"].reindex(idx).to_numpy(float),
            L=p.df["low"].reindex(idx).to_numpy(float), C=p.df["close"].reindex(idx).to_numpy(float),
            E=ema.reindex(idx).to_numpy(float), R=atr.reindex(idx).to_numpy(float),
            LF=lf.reindex(idx).fillna(False).to_numpy(bool), SF=sf.reindex(idx).fillna(False).to_numpy(bool))

    half = {p.name: (p.spread / 2 + p.slip) * cfg.cost_mult for p in pairs}
    pmap = {p.name: p for p in pairs}

    def swap_usd_night(p: Pair, d: int, lots: float):
        pts = p.swap_long if d > 0 else p.swap_short
        v = pts * p.tick_value * lots
        if v > 0:
            return v if cfg.swap_credit else 0.0
        return v * cfg.swap_mult

    bal = cfg.equity0
    peak = bal
    pos = {}
    pend_entry = {}
    pend_exit = set()
    eq = np.full(T, np.nan)
    trades = []
    sk_lot = sk_slot = 0
    cost_tot = swap_tot = 0.0
    halted = None
    last_close = {p.name: np.nan for p in pairs}

    def unreal(name, px):
        po = pos[name]
        return _usd(po["d"] * po["lots"] * CONTRACT * (px - po["entry"]), px, pmap[name].usd_base)

    def close_pos(name, t, fill_mid, reason):
        nonlocal bal, cost_tot
        po = pos.pop(name)
        p = pmap[name]
        px = fill_mid - po["d"] * half[name]
        gross = _usd(po["d"] * po["lots"] * CONTRACT * (px - po["entry"]), px, p.usd_base)
        cexit = _usd(po["lots"] * CONTRACT * half[name], px, p.usd_base)
        bal += gross
        cost_tot += cexit
        net = gross + po["swap"]
        trades.append(dict(pair=name, dir=po["d"], entry_date=po["edate"], exit_date=idx[t], lots=po["lots"],
                           entry_px=po["entry"], exit_px=px, reason=reason, risk_usd=po["risk"], pnl_usd=net,
                           swap_usd=po["swap"], cost_usd=po["centry"] + cexit, R=net / po["risk"]))

    for t in range(T):
        a_prev = eq[t - 1] if t > 0 else cfg.equity0
        if halted is not None:
            eq[t] = bal
            continue
        names_today = [p.name for p in pairs if np.isfinite(A[p.name]["C"][t])]
        # 1. exits decided at the previous close, executed at this open
        for n in [n for n in names_today if n in pend_exit]:
            if n in pos:
                close_pos(n, t, A[n]["O"][t], "signal")
            pend_exit.discard(n)
        # 2. equity at the open, daily loss check
        eq_open = bal + sum(unreal(n, A[n]["O"][t] if n in names_today else last_close[n]) for n in pos)
        no_entry = eq_open <= a_prev * (1 - cfg.day_loss)
        # 3. entries decided at the previous close, fixed priority order
        for p in pairs:
            n = p.name
            if n not in pend_entry or n not in names_today:
                continue
            d, atr = pend_entry.pop(n)
            if no_entry or n in pos:
                continue
            if len(pos) >= cfg.max_pos:
                sk_slot += 1
                continue
            o = A[n]["O"][t]
            fill = o + d * half[n]
            sd = cfg.atr_mult * atr
            rpl = _usd(sd * CONTRACT, fill, p.usd_base)
            lots = size_lots(eq_open, rpl, cfg)
            if lots is None:
                sk_lot += 1
                continue
            cent = _usd(lots * CONTRACT * half[n], fill, p.usd_base)
            cost_tot += cent
            pos[n] = dict(d=d, lots=lots, entry=fill, stop=fill - d * sd, risk=lots * rpl, swap=0.0, edate=idx[t], centry=cent)
        # 4. stops inside the bar
        for n in list(pos):
            if n not in names_today:
                continue
            po = pos[n]
            o, h, l = A[n]["O"][t], A[n]["H"][t], A[n]["L"][t]
            if po["d"] > 0:
                if o <= po["stop"]:
                    close_pos(n, t, o, "stop_gap")
                elif l <= po["stop"]:
                    close_pos(n, t, po["stop"], "stop")
            else:
                if o >= po["stop"]:
                    close_pos(n, t, o, "stop_gap")
                elif h >= po["stop"]:
                    close_pos(n, t, po["stop"], "stop")
        # 5. swap for positions held over this close
        wd = idx[t].weekday()
        for n in pos:
            if n in names_today:
                s = swap_usd_night(pmap[n], pos[n]["d"], pos[n]["lots"]) * (3 if wd == 2 else 1)
                pos[n]["swap"] += s
                bal += s
                swap_tot += s
        for n in names_today:
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
        # 7. signals at this close for the next open
        pend_entry = {}
        for p in pairs:
            n = p.name
            if n not in names_today:
                continue
            c, em = A[n]["C"][t], A[n]["E"][t]
            if n in pos:
                if (pos[n]["d"] > 0 and c < em) or (pos[n]["d"] < 0 and c > em):
                    pend_exit.add(n)
            elif A[n]["LF"][t]:
                pend_entry[n] = (1, A[n]["R"][t])
            elif A[n]["SF"][t]:
                pend_entry[n] = (-1, A[n]["R"][t])
    if halted is None:
        for n in list(pos):
            close_pos(n, T - 1, last_close[n], "end")
        eq[T - 1] = bal
    tr = pd.DataFrame(trades)
    return PResult(pd.Series(eq, index=idx), tr, sk_lot, sk_slot, halted, cost_tot, swap_tot)


def pstats(res: PResult, seed: int = 12345) -> dict:
    tr = res.trades
    eq = res.equity.ffill()
    out = {"trades": int(len(tr)), "skipped_min_lot": res.skipped_min_lot, "skipped_slots": res.skipped_slots,
           "halted_on": res.halted_on}
    r = eq.pct_change().dropna()
    out["sharpe"] = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else float("nan")
    out["max_dd_pct"] = float((eq / eq.cummax() - 1).min() * 100)
    out["end_equity"] = float(eq.iloc[-1])
    if len(tr):
        R = tr["R"].to_numpy()
        out["mean_R"] = float(R.mean())
        rng = np.random.default_rng(seed)
        bs = rng.choice(R, size=(5_000, len(R)), replace=True).mean(axis=1)
        out["mean_R_lb95"] = float(np.percentile(bs, 2.5))
        w, l = tr.loc[tr.pnl_usd > 0, "pnl_usd"].sum(), -tr.loc[tr.pnl_usd < 0, "pnl_usd"].sum()
        out["profit_factor"] = float(w / l) if l > 0 else float("inf")
        out["pair_pnl"] = tr.groupby("pair")["pnl_usd"].sum().to_dict()
    return out
