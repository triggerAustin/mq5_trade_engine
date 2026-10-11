#!/usr/bin/env python3
"""Download the 8-market universe from Dukascopy and build DAILY files for the portfolio test.

    python download_universe.py                 # all 8 markets, 2003-06 -> 2026-09
    python download_universe.py --markets GBPUSD XAUUSD

* Resumable: every month is cached in data/cache/. If it stops (connection drop, Ctrl+C), run the
  same command again and it continues where it stopped.
* EURUSD is built from the two files you already have (data/EURUSD_H1_old.csv + data/EURUSD_H1.csv)
  if they exist, so it is not downloaded again.
* Output: data/universe_daily/<MARKET>_D1.csv  (daily bars on the 17:00 New York roll - see mt5bot.data.to_daily) and
          data/universe_daily.zip  (small - attach this to your chat message).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
import time
import zipfile

import pandas as pd

from fetch_dukascopy import bad_candles, decode, fetch_month
from mt5bot.data import to_daily, validate_daily

UNIVERSE = {
    "EURUSD": "EUR-USD", "GBPUSD": "GBP-USD", "USDJPY": "USD-JPY", "AUDUSD": "AUD-USD",
    "USDCAD": "USD-CAD", "USDCHF": "USD-CHF", "NZDUSD": "NZD-USD", "XAUUSD": "XAU-USD",
}
OUT_DIR = "data/universe_daily"
CACHE = "data/cache"


def months(start: str, end: str):
    y, m = map(int, start.split("-")); ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def get_month(code: str, y: int, m: int):
    """Closed months are cached forever; the CURRENT month is never cached (it is still growing)."""
    now = dt.datetime.now(dt.timezone.utc)
    is_current = (y, m) == (now.year, now.month)
    path = os.path.join(CACHE, f"{code}_BID_{y}_{m:02d}.json")
    if os.path.exists(path) and not is_current:
        with open(path) as f:
            return json.load(f), "cache"
    d = fetch_month(code, "BID", y, m)
    if d is not None and not is_current:
        with open(path, "w") as f:
            json.dump(d, f)
    return d, "downloaded"


def build_market(name: str, code: str, start: str, end: str, workers: int, use_csv: bool = True):
    t0 = time.time()
    if use_csv and name == "EURUSD" and os.path.exists("data/EURUSD_H1_old.csv") and os.path.exists("data/EURUSD_H1.csv"):
        from mt5bot.data import load_csv
        h = pd.concat([load_csv("data/EURUSD_H1_old.csv"), load_csv("data/EURUSD_H1.csv")])
        h = h[~h.index.duplicated()].sort_index()
        return h, [], []
    todo = list(months(start, end))
    rows, missing, failed = [], [], []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(get_month, code, y, m): (y, m) for y, m in todo}
        for fut in cf.as_completed(futs):
            y, m = futs[fut]
            try:
                d, _src = fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append(f"{y}-{m:02d}"); print(f"    {name} {y}-{m:02d} FAILED: {e}"); continue
            if d is None or not d.get("times"):
                missing.append(f"{y}-{m:02d}")
            else:
                rows += decode(d)
            done += 1
            if done % 24 == 0 or done == len(todo):
                print(f"  {name}: {done}/{len(todo)} months  ({time.time() - t0:.0f}s)", flush=True)
    if not rows:
        return None, sorted(missing), sorted(failed)
    rows = sorted(set(rows))
    h = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"])
    h.index = pd.to_datetime(h.pop("t"), unit="ms")
    h.index.name = "time"
    return h, sorted(missing), sorted(failed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", nargs="*", default=list(UNIVERSE))
    ap.add_argument("--start", default="2003-06")
    ap.add_argument("--end", default="2026-09")
    ap.add_argument("--no-csv", action="store_true", help="build EURUSD from the monthly JSON cache/download too (needed to refresh to today)")
    ap.add_argument("--workers", type=int, default=3, help="parallel downloads (3 is polite and ~3x faster)")
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True); os.makedirs(CACHE, exist_ok=True)

    summary, problems = [], []
    for name in a.markets:
        print(f"\n=== {name} ===", flush=True)
        h, missing, failed = build_market(name, UNIVERSE[name], a.start, a.end, a.workers, use_csv=not a.no_csv)
        if failed:
            problems.append(f"{name}: {len(failed)} months failed ({failed[:3]}...) - run the same command again")
        if h is None or len(h) == 0:
            problems.append(f"{name}: NO DATA at all - instrument code '{UNIVERSE[name]}' may be wrong or the connection is blocked")
            continue
        bad = bad_candles([(0, r.open, r.high, r.low, r.close, 0) for r in h.itertuples()])
        d = to_daily(h)
        issues = validate_daily(d, name)
        problems += issues
        d.to_csv(os.path.join(OUT_DIR, f"{name}_D1.csv"))
        summary.append((name, len(h), len(d), str(d.index[0].date()), str(d.index[-1].date()), bad, len(missing)))
        print(f"  {name}: {len(h)} hourly candles -> {len(d)} daily bars, {d.index[0].date()} -> {d.index[-1].date()}, "
              f"inconsistent {bad}, months with no data {len(missing)}", flush=True)

    print("\n=========== SUMMARY ===========")
    print(f"{'market':8s} {'hourly':>8s} {'daily':>6s}  {'first':10s}  {'last':10s}  inconsistent  no-data months")
    for r in summary:
        print(f"{r[0]:8s} {r[1]:8d} {r[2]:6d}  {r[3]:10s}  {r[4]:10s}  {r[5]:12d}  {r[6]:14d}")
    for p in problems:
        print("PROBLEM:", p)
    if os.path.isdir(OUT_DIR) and os.listdir(OUT_DIR):
        with zipfile.ZipFile("data/universe_daily.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(os.listdir(OUT_DIR)):
                z.write(os.path.join(OUT_DIR, f), f"universe_daily/{f}")
        print("\nWrote data/universe_daily.zip  <- attach this file to your chat message")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()

