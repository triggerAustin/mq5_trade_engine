"""Cross-asset time-series momentum engine (pre-registered test #3). See PREREGISTRATION_cross_asset.md.

Everything is expressed in USD-quote orientation: every instrument has a USD price series, a long position gains
when the price rises. USD-base FX pairs (USDJPY, USDCAD, USDCHF) are inverted by the loader (price Q = 1/P),
so "long USDJPY" is "short Q"; P&L is then exactly units * (price change) for every instrument.

Conventions (kept identical to the earlier engines):
  * signals use data up to and including the CLOSE of the rebalance day (the last union-calendar day of a month)
  * trades execute at the NEXT day's OPEN; costs are charged on the traded notional at that open
  * overnight P&L (previous close -> open) is earned by the OLD position; open -> close by the NEW one
  * no look-ahead: every quantity at day t uses data with index <= t only  (a deliberately broken variant,
    `_bug_lookahead` = days peeked ahead, exists ONLY so the self-test can prove the harness detects look-ahead)
  * financing is charged per calendar day on gross notional (a stand-in for CFD overnight charges)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Asset:
    name: str
    cls: str                  # equity / bond / commodity / fx
    df: pd.DataFrame          # columns open, close; USD-quote orientation; total-return adjusted for ETFs
    cost_side: float          # fractional cost per side, e.g. 0.0002 = 2 bps


@dataclass
class XConfig:
    lookbacks: tuple = (63, 126, 252)
    vol_span: int = 60
    asset_vol: float = 0.10
    port_vol: float = 0.08
    gross_cap: float = 3.0
    port_window: int = 60
    vol_floor: float = 0.02          # implementation detail (not in the spec): avoids dividing by ~0
    financing: float = 0.03          # per year on gross notional
    cost_mult: float = 1.0
    initial_equity: float = 100_000.0
    _bug_lookahead: int = 0          # TEST ONLY: peek this many days ahead when computing the signal


@dataclass
class XResult:
    equity: pd.Series
    class_pnl: pd.DataFrame          # cumulative gross P&L by class (before costs and financing)
    costs: float
    financing_paid: float
    turnover_per_year: float
    rebalances: pd.DataFrame
    stats: dict = field(default_factory=dict)


def panel(assets: list[Asset]):
    idx = assets[0].df.index
    for a in assets[1:]:
        idx = idx.union(a.df.index)
    idx = idx.sort_values()
    T, N = len(idx), len(assets)
    O = np.full((T, N), np.nan)
    C = np.full((T, N), np.nan)
    has = np.zeros((T, N), bool)
    for j, a in enumerate(assets):
        c = a.df["close"].reindex(idx)
        o = a.df["open"].reindex(idx)
        has[:, j] = c.notna().to_numpy()
        cff = c.ffill()                           # NaN before the first bar, flat on days without a bar
        prev = cff.shift(1)
        o = o.where(c.notna(), prev)              # no bar today: "open" = yesterday's close (no trading gain)
        C[:, j] = cff.to_numpy()
        O[:, j] = o.to_numpy()
    return idx, O, C, has


def _month_ends(idx: pd.DatetimeIndex) -> np.ndarray:
    m = idx.to_period("M")
    flag = np.zeros(len(idx), bool)
    flag[:-1] = m[1:] != m[:-1]
    return flag


def run_xasset(assets: list[Asset], cfg: XConfig) -> XResult:
    idx, O, C, has = panel(assets)
    T, N = C.shape
    classes = [a.cls for a in assets]
    cls_names = sorted(set(classes))
    cost = np.array([a.cost_side for a in assets]) * cfg.cost_mult

    # daily returns on the union calendar (flat days give 0); EWMA volatility, annualised
    R = np.full((T, N), np.nan)
    R[1:] = C[1:] / C[:-1] - 1.0
    Rdf = pd.DataFrame(R)
    vol = (Rdf.ewm(span=cfg.vol_span, min_periods=30).std().to_numpy()) * np.sqrt(252)
    vol = np.where(np.isfinite(vol), np.maximum(vol, cfg.vol_floor), np.nan)
    R0 = np.nan_to_num(R)

    is_me = _month_ends(idx)
    days = np.zeros(T)
    days[1:] = (idx[1:] - idx[:-1]).days

    units = np.zeros(N)
    E = cfg.initial_equity
    pending = None                                   # target weights, executed at the next day's open
    eq = np.full(T, np.nan)
    pnl_cls = {c: np.zeros(T) for c in cls_names}
    cost_total = fin_total = traded = 0.0
    reb = []

    for t in range(T):
        pnl_i = np.zeros(N)
        if t == 0:
            pass
        elif pending is not None:
            ok = np.isfinite(O[t]) & np.isfinite(C[t - 1])
            over = np.where(ok, units * (O[t] - C[t - 1]), 0.0)         # old position, previous close -> open
            E += over.sum()
            pnl_i += over
            tgt = np.where(np.isfinite(pending), pending, 0.0) * E       # target notional at this open
            cur = units * np.where(np.isfinite(O[t]), O[t], 0.0)
            trade = np.abs(tgt - cur)
            c_t = float((trade * cost).sum())
            E -= c_t
            cost_total += c_t
            traded += float(trade.sum())
            with np.errstate(divide="ignore", invalid="ignore"):
                units = np.where(np.isfinite(O[t]) & (O[t] > 0), tgt / O[t], 0.0)
            intr = np.where(np.isfinite(O[t]) & np.isfinite(C[t]), units * (C[t] - O[t]), 0.0)   # new position
            E += intr.sum()
            pnl_i += intr
            pending = None
        else:
            dp = np.where(np.isfinite(C[t]) & np.isfinite(C[t - 1]), units * (C[t] - C[t - 1]), 0.0)
            E += dp.sum()
            pnl_i += dp
        for j in range(N):
            pnl_cls[classes[j]][t] += pnl_i[j]

        if cfg.financing and t > 0:
            gross = float((np.abs(units) * np.where(np.isfinite(C[t]), C[t], 0.0)).sum())
            f = gross * cfg.financing * days[t] / 365.0
            E -= f
            fin_total += f
        eq[t] = E

        # ---- month-end: decide targets from data up to and including this close -------------
        if is_me[t] and t < T - 1:
            w = np.full(N, np.nan)
            sig = np.zeros(N)
            elig = np.zeros(N, bool)
            for j in range(N):
                tt = min(t + cfg._bug_lookahead, T - 1) if cfg._bug_lookahead else t
                ok = np.isfinite(vol[t, j])
                s = 0.0
                for L in cfg.lookbacks:
                    if t - L < 0 or not np.isfinite(C[t - L, j]) or not ok:
                        ok = False
                        break
                    s += np.sign(C[tt, j] / C[t - L, j] - 1.0)
                if ok:
                    elig[j] = True
                    sig[j] = s / len(cfg.lookbacks)
            if elig.any():
                active_cls = sorted({classes[j] for j in range(N) if elig[j]})
                n_cls = len(active_cls)
                raw = np.zeros(N)
                for c in active_cls:
                    members = [j for j in range(N) if elig[j] and classes[j] == c]
                    for j in members:
                        raw[j] = sig[j] * (cfg.asset_vol / vol[t, j]) / len(members) / n_cls
                lo = max(0, t - cfg.port_window + 1)
                rp = R0[lo:t + 1] @ raw
                vp = float(np.std(rp, ddof=1) * np.sqrt(252)) if len(rp) > 5 else 0.0
                gross_raw = float(np.abs(raw).sum())
                if vp > 0 and gross_raw > 0:
                    scale = min(cfg.port_vol / vp, cfg.gross_cap / gross_raw)
                else:
                    scale = 0.0
                w = np.where(elig, raw * scale, 0.0)
                pending = w
                reb.append({"date": idx[t], "gross": float(np.abs(w).sum()), "scale": scale, "n_active": int(elig.sum())})
            else:
                pending = np.zeros(N)

    eqs = pd.Series(eq, index=idx)
    cp = pd.DataFrame({c: np.cumsum(v) for c, v in pnl_cls.items()}, index=idx)
    years = max((idx[-1] - idx[0]).days / 365.25, 1e-9)
    res = XResult(eqs, cp, cost_total, fin_total, traded / cfg.initial_equity / years, pd.DataFrame(reb))
    res.stats = xstats(eqs, cfg.initial_equity)
    return res


def sharpe(eq: pd.Series, start=None, end=None) -> float:
    e = eq.loc[start:end]
    r = e.pct_change().dropna()
    if len(r) < 20 or r.std() == 0:
        return float("nan")
    return float(r.mean() / r.std() * np.sqrt(252))


def xstats(eq: pd.Series, init: float) -> dict:
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    end = float(eq.iloc[-1])
    return {
        "sharpe": sharpe(eq),
        "cagr_pct": ((end / init) ** (1 / years) - 1) * 100 if end > 0 else -100.0,
        "max_dd_pct": float((eq / eq.cummax() - 1).min() * 100),
        "ann_vol_pct": float(eq.pct_change().std() * np.sqrt(252) * 100),
        "end_equity": end, "years": years,
    }
