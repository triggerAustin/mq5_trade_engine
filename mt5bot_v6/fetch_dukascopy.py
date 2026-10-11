#!/usr/bin/env python3
"""Download hourly candles from Dukascopy (no extra libraries needed).

Examples:
  python fetch_dukascopy.py                              # EUR/USD, 2018 -> now
  python fetch_dukascopy.py --inst XAU-USD --out data/XAUUSD_H1.csv
  python fetch_dukascopy.py --inst GBP-USD --start 2020-01

Each month is saved to data/cache/ as it arrives, so if your connection drops
just run the same command again and it continues where it stopped.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

URL = "https://jetta.dukascopy.com/v1/candles/hour/{inst}/{side}/{year}/{month}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Origin": "https://www.dukascopy.com",
    "Referer": "https://www.dukascopy.com/",
    "Accept": "application/json",
}


def decode(d: dict) -> list[tuple]:
    """Turn one month of Dukascopy's compact format into (ms, o, h, l, c, volume) rows.

    The file holds a starting price per field and a list of CHANGES. Prices are
    rebuilt with integer arithmetic so rounding errors can't accumulate.
    """
    m = d["multiplier"]
    decimals = int(round(-math.log10(m)))
    t = int(d["timestamp"])
    shift = int(d["shift"])
    o, h, l, c = (int(round(d[k] / m)) for k in ("open", "high", "low", "close"))
    rows = []
    for i in range(len(d["times"])):
        t += int(d["times"][i]) * shift
        o += int(d["opens"][i]); h += int(d["highs"][i])
        l += int(d["lows"][i]); c += int(d["closes"][i])
        rows.append((t, round(o * m, decimals), round(h * m, decimals),
                     round(l * m, decimals), round(c * m, decimals), d["volumes"][i]))
    return rows


def bad_candles(rows) -> int:
    """Count candles that are internally inconsistent (high/low don't contain open/close)."""
    eps = 1e-9
    return sum(1 for _, o, h, l, c, _v in rows if h < max(o, c) - eps or l > min(o, c) + eps)


def fetch_month(inst, side, year, month, retries=8):
    """Returns parsed JSON, or None if Dukascopy has no data for that month."""
    url = URL.format(inst=inst, side=side, year=year, month=month)
    for attempt in range(1, retries + 1):
        wait = min(5 * attempt, 30)
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                status, body = r.status, r.read()
            if status == 200 and body:
                return json.loads(body)
            print(f"    status {status}, retrying in {wait}s ({attempt}/{retries})")
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 410):  # 400 = month not published yet (e.g. current month)
                return None
            print(f"    HTTP {e.code}, retrying in {wait}s ({attempt}/{retries})")
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            print(f"    {type(e).__name__}: {e}; retrying in {wait}s ({attempt}/{retries})")
        time.sleep(wait)
    raise RuntimeError(f"gave up on {year}-{month:02d}; run the same command again to resume")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", default="EUR-USD", help="e.g. EUR-USD, GBP-USD, XAU-USD")
    ap.add_argument("--side", default="BID", choices=["BID", "ASK"])
    ap.add_argument("--start", default="2018-01", help="YYYY-MM")
    ap.add_argument("--end", default=None, help="YYYY-MM (default: this month)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--pause", type=float, default=0.7, help="seconds between requests")
    a = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    sy, sm = map(int, a.start.split("-"))
    ey, em = map(int, a.end.split("-")) if a.end else (now.year, now.month)
    out = a.out or f"data/{a.inst.replace('-', '')}_H1.csv"
    cache = os.path.join(os.path.dirname(out) or ".", "cache")
    os.makedirs(cache, exist_ok=True)

    all_rows, y, m, skipped = [], sy, sm, []
    while (y, m) <= (ey, em):
        path = os.path.join(cache, f"{a.inst}_{a.side}_{y}_{m:02d}.json")
        is_current = (y, m) == (now.year, now.month)
        if os.path.exists(path) and not is_current:
            with open(path) as f:
                d = json.load(f)
            src = "cache"
        else:
            d = fetch_month(a.inst, a.side, y, m)
            src = "downloaded"
            if d is not None and not is_current:
                with open(path, "w") as f:
                    json.dump(d, f)
            time.sleep(a.pause)
        if d is None or not d.get("times"):
            skipped.append(f"{y}-{m:02d}")
            print(f"{y}-{m:02d}  no data")
        else:
            rows = decode(d)
            all_rows += rows
            print(f"{y}-{m:02d}  {len(rows):4d} candles ({src})")
        m += 1
        if m == 13:
            y, m = y + 1, 1

    if not all_rows:
        sys.exit("No data downloaded.")
    all_rows = sorted(set(all_rows))
    bad = bad_candles(all_rows)
    with open(out, "w") as f:
        f.write("time,open,high,low,close,volume\n")
        for t, o, h, l, c, v in all_rows:
            ts = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts},{o},{h},{l},{c},{v}\n")
    first = dt.datetime.fromtimestamp(all_rows[0][0] / 1000, dt.timezone.utc)
    last = dt.datetime.fromtimestamp(all_rows[-1][0] / 1000, dt.timezone.utc)
    print(f"\nSaved {len(all_rows)} candles ({first:%Y-%m-%d} -> {last:%Y-%m-%d}) to {out}")
    print(f"Inconsistent candles: {bad}  (should be 0)")
    if skipped:
        print("Months with no data:", ", ".join(skipped))


if __name__ == "__main__":
    main()

