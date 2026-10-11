"""Strategies produce signal arrays; they never touch prices after the bar close."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import atr


def donchian_breakout(df: pd.DataFrame, entry_n: int = 55, exit_n: int = 20,
                      atr_n: int = 14, atr_stop: float = 2.5, allow_short: bool = True) -> dict:
    """Classic trend-following breakout.

    Long when the close breaks above the highest high of the previous `entry_n` bars;
    exit when the close falls below the lowest low of the previous `exit_n` bars
    (or the ATR stop is hit). Mirror image for shorts.
    """
    hh = df["high"].rolling(entry_n).max().shift(1)
    ll = df["low"].rolling(entry_n).min().shift(1)
    exit_hi = df["high"].rolling(exit_n).max().shift(1)
    exit_lo = df["low"].rolling(exit_n).min().shift(1)
    a = atr(df, atr_n)
    c = df["close"]

    long_entry = (c > hh).fillna(False).to_numpy()
    short_entry = ((c < ll).fillna(False).to_numpy()) if allow_short else np.zeros(len(df), bool)
    long_exit = (c < exit_lo).fillna(False).to_numpy()
    short_exit = (c > exit_hi).fillna(False).to_numpy()
    stop_dist = (a * atr_stop).to_numpy()
    return dict(long_entry=long_entry, short_entry=short_entry,
                long_exit=long_exit, short_exit=short_exit, stop_dist=stop_dist)


def mean_reversion(df: pd.DataFrame, n: int = 50, k: float = 2.0, atr_n: int = 14,
                   atr_stop: float = 3.0, allow_short: bool = True) -> dict:
    """Fade stretched moves: buy when price is k standard deviations below its n-bar
    mean, sell when k above; exit when price returns to the mean (or the ATR stop hits)."""
    c = df["close"]
    ma = c.rolling(n).mean()
    sd = c.rolling(n).std()
    z = (c - ma) / sd
    a = atr(df, atr_n)
    long_entry = (z < -k).fillna(False).to_numpy()
    short_entry = ((z > k).fillna(False).to_numpy()) if allow_short else np.zeros(len(df), bool)
    long_exit = (c >= ma).fillna(False).to_numpy()
    short_exit = (c <= ma).fillna(False).to_numpy()
    return dict(long_entry=long_entry, short_entry=short_entry, long_exit=long_exit,
                short_exit=short_exit, stop_dist=(a * atr_stop).to_numpy())


def with_session(sig: dict, df: pd.DataFrame, start_hour: int = 7, end_hour: int = 16) -> dict:
    """Only allow NEW entries when the signal bar falls in [start_hour, end_hour) UTC."""
    h = df.index.hour
    m = (h >= start_hour) & (h < end_hour)
    out = dict(sig)
    out["long_entry"] = sig["long_entry"] & m
    out["short_entry"] = sig["short_entry"] & m
    return out


def with_trend(sig: dict, df: pd.DataFrame, n: int = 200) -> dict:
    """Only go long above the n-bar average and short below it."""
    c = df["close"]
    ma = c.rolling(n).mean()
    up = (c > ma).fillna(False).to_numpy()
    dn = (c < ma).fillna(False).to_numpy()
    out = dict(sig)
    out["long_entry"] = sig["long_entry"] & up
    out["short_entry"] = sig["short_entry"] & dn
    return out

