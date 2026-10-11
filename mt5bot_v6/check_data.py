"""Data self-test and audit.   python check_data.py

1) Regression test for the v5 daily-bar bug: on a synthetic hourly timeline with the REAL weekly FX
   session (Sunday 17:00 New York -> Friday 17:00 New York, DST-aware), the old fixed-22:00-UTC cut
   must show spurious stub bars and the v6 to_daily() must not.
2) Audit of data/universe_daily/*_D1.csv if present (v6 format, `candles` column): no weekend labels,
   no stub bars, ~250-263 bars per full year.
Run after ANY change to to_daily() and before every pre-registered test.
"""
from __future__ import annotations
import glob, os
import numpy as np, pandas as pd
from mt5bot.data import to_daily, validate_daily


def synthetic_hourly(start="2004-01-01", end="2025-01-03") -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="1h", tz="UTC")
    ny = idx.tz_convert("America/New_York")
    dow, hr = ny.dayofweek, ny.hour
    sess = ((dow == 6) & (hr >= 17)) | dow.isin([0, 1, 2, 3]) | ((dow == 4) & (hr < 17))
    t = idx[sess].tz_localize(None)
    rng = np.random.default_rng(0)
    p = 1.1 * np.exp(np.cumsum(rng.standard_normal(len(t)) * 1e-4))
    return pd.DataFrame({"open": p, "high": p * 1.0001, "low": p * 0.9999, "close": p}, index=t)


def old_to_daily(h):  # the v5 method, kept ONLY to prove the test detects the bug
    return h.resample("24h", offset="22h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def main() -> int:
    ok = True
    h = synthetic_hourly()
    weekdays = len(pd.bdate_range("2004-01-01", "2024-12-31"))
    old, new = old_to_daily(h), to_daily(h)
    old, new = old.loc[:"2024-12-31"], new.loc[:"2024-12-31"]   # ignore the partial bar at the end of the synthetic series
    n_stub_old = int((h.resample("24h", offset="22h")["open"].count() <= 3).sum() - ((h.resample("24h", offset="22h")["open"].count() == 0)).sum())
    print(f"1) synthetic 2004-2024: weekdays {weekdays} | old method bars {len(old)} (stubs ~{n_stub_old}) | v6 bars {len(new)}")
    good = len(new) == weekdays and not (new.index.dayofweek >= 5).any() and (new["candles"] >= 20).all() and len(old) > weekdays + 300
    print("   PASS" if good else "   FAIL"); ok &= good

    files = sorted(glob.glob("data/universe_daily/*_D1.csv"))
    if not files:
        print("2) no data/universe_daily files found - audit skipped")
    for f in files:
        name = os.path.basename(f).split("_")[0]
        d = pd.read_csv(f, index_col=0, parse_dates=True)
        issues = validate_daily(d, name)
        full = d.groupby(d.index.year).size()
        print(f"2) {name:7s} bars {len(d):5d} | min candles/bar {int(d['candles'].min()) if 'candles' in d else '?'} | "
              f"{'OK' if not issues else 'PROBLEM'}")
        for i in issues:
            print("     -", i)
        ok &= not issues
    print("\nOVERALL:", "DATA CHECKS PASSED" if ok else "SOMETHING IS WRONG - do not run any daily test")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
