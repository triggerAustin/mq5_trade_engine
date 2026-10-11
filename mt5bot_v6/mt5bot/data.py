"""Data loading and synthetic data generation."""
from __future__ import annotations

import numpy as np
import pandas as pd

OHLC = ["open", "high", "low", "close"]


def load_csv(path: str) -> pd.DataFrame:
    """Load OHLC candles from a CSV file.

    Understands the common exports:
      * Dukascopy:  Gmt time, Open, High, Low, Close, Volume
      * MT5 export: <DATE>, <TIME>, <OPEN>, <HIGH>, <LOW>, <CLOSE>, ... (tab separated)
      * Generic:    time/datetime/date, open, high, low, close
    Returns a DataFrame indexed by UTC datetime with columns open/high/low/close.
    """
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]

    if "date" in df.columns and "time" in df.columns:  # MT5 style
        ts = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    else:
        tcol = next(
            (c for c in df.columns if c in ("time", "datetime", "date", "gmt time", "timestamp")),
            df.columns[0],
        )
        raw = df[tcol]
        if pd.api.types.is_numeric_dtype(raw):  # epoch timestamps (dukascopy-node)
            unit = "ms" if raw.abs().median() > 1e11 else "s"
            ts = pd.to_datetime(raw, unit=unit)
        else:
            # ISO dates (2024-05-04 ...) must NOT be read day-first or day/month swap.
            ts = pd.to_datetime(raw, format="ISO8601", errors="coerce")
            if ts.isna().mean() > 0.5:  # not ISO (e.g. 04.05.2024 12:00:00.000): day-first
                ts = pd.to_datetime(raw, dayfirst=True, errors="coerce")

    out = df[OHLC].astype(float)
    out.index = pd.DatetimeIndex(ts, name="time")
    out = out[~out.index.isna()]
    n_raw = len(out)
    if not out.index.is_monotonic_increasing:
        raise ValueError("CSV timestamps are not in chronological order - dates were probably misread. "
                         "Do not trust any backtest on this data.")
    out = out[~out.index.duplicated(keep="first")]
    if len(out) < n_raw:
        print(f"warning: dropped {n_raw - len(out)} duplicate timestamps")
    if out.index[-1] > pd.Timestamp.now() + pd.Timedelta(days=2):
        raise ValueError(f"data ends in the future ({out.index[-1]}) - dates misread")
    return out.dropna()


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample candles, e.g. rule='1h' or '4h'."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return df.resample(rule).agg(agg).dropna()


def synthetic_prices(n: int = 60_000, start_price: float = 1.10, annual_vol: float = 0.07,
                     seed: int = 0, freq: str = "1h") -> pd.DataFrame:
    """Driftless random-walk candles with volatility clustering.

    There is NO exploitable edge in this data. A trustworthy backtester must
    NOT make money on it once costs are charged. Use it as a sanity check.
    """
    rng = np.random.default_rng(seed)
    bars_per_year = 24 * 252
    base = annual_vol / np.sqrt(bars_per_year)

    # simple volatility clustering (AR(1) in log-vol)
    lv = np.zeros(n)
    for i in range(1, n):
        lv[i] = 0.98 * lv[i - 1] + 0.15 * rng.standard_normal()
    vol = base * np.exp(lv - lv.var() / 2)

    rets = vol * rng.standard_normal(n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    # intrabar excursion
    ex_hi = np.abs(rng.standard_normal(n)) * vol * 0.5 * close
    ex_lo = np.abs(rng.standard_normal(n)) * vol * 0.5 * close
    high = np.maximum(open_, close) + ex_hi
    low = np.minimum(open_, close) - ex_lo

    idx = pd.date_range("2018-01-01", periods=n, freq=freq, name="time")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)



MIN_CANDLES_PER_DAY = 4   # a real FX day has ~24 hourly candles; a stub of 1-3 candles is a session-edge artefact


def to_daily(h: pd.DataFrame, min_candles: int = MIN_CANDLES_PER_DAY) -> pd.DataFrame:
    """Hourly UTC candles -> daily FX bars on the real FX roll: 17:00 New York to 17:00 New York.

    v6 fix. The older code cut days at a FIXED 22:00 UTC, which is the 17:00 New York roll only in
    winter. In US summer the market reopens Sunday 21:00 UTC, so that single candle formed its own
    one-hour "Sunday" bar (~800 spurious bars per pair over 2003-2026). Those stubs shrank ATR,
    shortened every rolling window and fired signals on one-hour bars.

    Method: express each candle's time as New York WALL-CLOCK time, add 7 hours (17:00 -> 24:00),
    then take calendar days. Bars are labelled with the date on which they CLOSE, so a bar's label
    is always Monday-Friday and the Sunday-evening session belongs to Monday. Output also carries a
    `candles` column (hourly candles in the bar) so data can be audited later.
    """
    s = h.copy()
    wall = s.index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    s.index = wall + pd.Timedelta(hours=7)
    g = s.resample("D")
    d = g.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    d["candles"] = g["open"].count()
    d = d[d["candles"] >= min_candles].dropna()
    d.index.name = "date"
    return d


def validate_daily(d: pd.DataFrame, name: str = "") -> list[str]:
    """Return a list of problems with a daily frame (empty list = OK). Run on every market before any test."""
    p = []
    if "candles" not in d.columns:
        return [f"{name}: no `candles` column - rebuild with to_daily() (v6 data format)"]
    if (d.index.dayofweek >= 5).any():
        p.append(f"{name}: {int((d.index.dayofweek >= 5).sum())} bars labelled Saturday/Sunday (bad day roll)")
    if (d["candles"] < MIN_CANDLES_PER_DAY).any():
        p.append(f"{name}: {int((d['candles'] < MIN_CANDLES_PER_DAY).sum())} stub bars (< {MIN_CANDLES_PER_DAY} candles)")
    full_years = d.loc[d.index.year.isin(range(d.index.year[0] + 1, d.index.year[-1]))]
    per_year = full_years.groupby(full_years.index.year).size()
    if len(per_year) and not per_year.between(245, 263).all():
        bad = per_year[~per_year.between(245, 263)]
        p.append(f"{name}: bars/year outside 245-263 -> {bad.to_dict()}")
    if d.index.duplicated().any():
        p.append(f"{name}: duplicate dates")
    return p
