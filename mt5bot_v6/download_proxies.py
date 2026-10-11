#!/usr/bin/env python3
"""Download long DAILY history for cross-asset research proxies (ETFs etc.) to data/proxies_d1/.

    python download_proxies.py                      # default list below, from Yahoo Finance
    python download_proxies.py --symbols SPY TLT    # only these
    python download_proxies.py --force              # re-download even if a file exists
    python download_proxies.py --from-json DIR      # MANUAL FALLBACK: convert JSON files you saved from your browser
                                                    #   (DIR/SPY.json, DIR/TLT.json, ...)

Browser fallback, if the script keeps getting HTTP 429: open this in your normal browser, one per symbol,
and save the page as DIR/<SYMBOL>.json  (Ctrl+S, or copy the text into a file):
    https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=max&interval=1d&events=div%7Csplit&includeAdjustedClose=true

* Output columns: date,open,high,low,close,adj_close,volume
  (open/high/low/close are RAW; adj_close includes dividends and splits)
* Resumable: existing files are skipped. Progress is printed for every symbol and every retry.
* Nothing here trades or touches MT5.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT = {
    "equity_us": ["SPY", "QQQ", "IWM"],
    "equity_intl": ["EFA", "EEM", "EWJ", "VGK"],
    "bonds": ["TLT", "IEF", "SHY", "LQD", "HYG", "TIP"],
    "commodities": ["GLD", "SLV", "DBC", "USO", "UNG"],
    "real_estate": ["VNQ"],
}
OUT_DIR = "data/proxies_d1"
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))
_warmed = False


def warm_up() -> None:
    """Visit Yahoo once so we hold a session cookie, like a browser would."""
    global _warmed
    if _warmed:
        return
    for url in ("https://fc.yahoo.com", "https://finance.yahoo.com/"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
            _opener.open(req, timeout=30).read(2000)
        except Exception:  # noqa: BLE001  (fc.yahoo.com normally answers 404 but still sets the cookie)
            pass
    _warmed = True
    print(f"  (session cookies obtained: {len(_jar)})", flush=True)


def parse_yahoo(raw: bytes) -> list[tuple]:
    j = json.loads(raw)
    res = j["chart"]["result"]
    if not res:
        raise ValueError(f"no result: {j['chart'].get('error')}")
    r = res[0]
    ts = r["timestamp"]
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c) or adj[i] is None:
            continue
        d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()
        rows.append((d, o, h, l, c, adj[i], v or 0))
    return rows


def fetch_yahoo(sym: str, attempts: int = 6) -> list[tuple]:
    warm_up()
    last = "no attempt"
    for k in range(attempts):
        host = HOSTS[k % len(HOSTS)]
        url = (f"https://{host}/v8/finance/chart/{sym}?range=max&interval=1d&events=div%7Csplit&includeAdjustedClose=true")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,*/*",
                                                       "Accept-Language": "en-US,en;q=0.9"})
            with _opener.open(req, timeout=60) as r:
                return parse_yahoo(r.read())
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} from {host}"
            wait = 20 * (k + 1) if e.code == 429 else 5 * (k + 1)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            wait = 5 * (k + 1)
        print(f"    attempt {k + 1}/{attempts} failed ({last}); waiting {wait}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(last)


def sanity(rows: list[tuple]) -> list[str]:
    notes = []
    dates = [r[0] for r in rows]
    if dates != sorted(dates):
        notes.append("dates not sorted")
    if len(set(dates)) != len(dates):
        notes.append("duplicate dates")
    bad = sum(1 for r in rows if not (r[2] >= max(r[1], r[4]) - 1e-9 and r[3] <= min(r[1], r[4]) + 1e-9))
    if bad:
        notes.append(f"{bad} bars with inconsistent OHLC")
    big = sum(1 for a, b in zip(rows, rows[1:]) if a[4] > 0 and abs(b[4] / a[4] - 1) > 0.25)
    if big:
        notes.append(f"{big} one-day close moves over 25% (split or bad tick?)")
    return notes


def save(sym: str, rows: list[tuple]) -> str:
    rows.sort()
    path = os.path.join(OUT_DIR, f"{sym}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "adj_close", "volume"])
        w.writerows(rows)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--pause", type=float, default=4.0, help="seconds between symbols (be polite; default 4)")
    ap.add_argument("--from-json", default=None, help="convert Yahoo JSON files saved from a browser instead of downloading")
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    summary, problems = [], []

    if a.from_json:
        files = sorted(glob.glob(os.path.join(a.from_json, "*.json")))
        # a file is either one Yahoo reply (symbol = file name) or a combined {"SPY": {...}, "TLT": {...}} file
        jobs = []
        for fp in files:
            try:
                with open(fp, "rb") as f:
                    j = json.loads(f.read())
            except Exception as e:  # noqa: BLE001
                print(f"{fp}: not valid JSON ({e})", flush=True)
                problems.append(os.path.basename(fp))
                continue
            if isinstance(j, dict) and "chart" in j:
                jobs.append((os.path.splitext(os.path.basename(fp))[0].upper(), json.dumps(j).encode()))
            elif isinstance(j, dict):
                jobs += [(k.upper(), json.dumps(v).encode()) for k, v in j.items()]
        print(f"converting {len(jobs)} symbols from {a.from_json}/", flush=True)
        for n, (sym, raw) in enumerate(jobs, 1):
            try:
                rows = parse_yahoo(raw)
                save(sym, rows)
                notes = sanity(rows)
                print(f"[{n}/{len(jobs)}] {sym}: OK, {len(rows)} bars {rows[0][0]} -> {rows[-1][0]}"
                      f"{'  NOTES: ' + '; '.join(notes) if notes else ''}", flush=True)
                summary.append((sym, "json", len(rows), rows[0][0], rows[-1][0], "; ".join(notes)))
            except Exception as e:  # noqa: BLE001
                print(f"[{n}/{len(jobs)}] {sym}: FAILED ({e})", flush=True)
                problems.append(sym)
    else:
        syms = a.symbols or [s for grp in DEFAULT.values() for s in grp]
        print(f"{len(syms)} symbols -> {OUT_DIR}/", flush=True)
        for n, sym in enumerate(syms, 1):
            path = os.path.join(OUT_DIR, f"{sym}.csv")
            if os.path.exists(path) and not a.force:
                print(f"[{n}/{len(syms)}] {sym}: already downloaded, skipping", flush=True)
                continue
            t0 = time.time()
            print(f"[{n}/{len(syms)}] {sym}: downloading from Yahoo ...", flush=True)
            try:
                rows = fetch_yahoo(sym)
                if len(rows) < 200:
                    raise RuntimeError(f"only {len(rows)} rows")
            except Exception as e:  # noqa: BLE001
                print(f"[{n}/{len(syms)}] {sym}: FAILED ({e})", flush=True)
                problems.append(sym)
                time.sleep(a.pause)
                continue
            save(sym, rows)
            notes = sanity(rows)
            print(f"[{n}/{len(syms)}] {sym}: OK, {len(rows)} bars {rows[0][0]} -> {rows[-1][0]} "
                  f"({time.time() - t0:.0f}s){'  NOTES: ' + '; '.join(notes) if notes else ''}", flush=True)
            summary.append((sym, "yahoo", len(rows), rows[0][0], rows[-1][0], "; ".join(notes)))
            time.sleep(a.pause)

    print("\n=========== SUMMARY ===========")
    for s in summary:
        print(f"{s[0]:6s} {s[1]:6s} {s[2]:6d} bars  {s[3]} -> {s[4]}  {s[5]}")
    if problems:
        print("FAILED:", ", ".join(problems))
        print("If these keep failing with HTTP 429, use the browser fallback described at the top of this file")
        print("(python download_proxies.py --from-json <folder>), or tell me and I will switch to another source.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
