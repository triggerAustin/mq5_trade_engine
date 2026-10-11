#!/usr/bin/env python3
"""Daily signal sheet (Phase A - no broker connection, nothing is traded by this script).

    python signal_runner.py refresh                 # download COMPLETED months only, rebuild daily files, audit them
    python signal_runner.py import --market XAUUSD --file XAUUSD_D1.csv   # add recent DAILY bars (e.g. an MT5 bar export)
    python signal_runner.py signals --equity 10000  # print what to do at the next open, per market
    python signal_runner.py record --market EURUSD --side long --entry 1.0850 --stop 1.0700 --lots 0.10
    python signal_runner.py record --market EURUSD --flat      # after a position was closed or stopped out
    python signal_runner.py show                    # positions this script believes are open

Daily routine (demo account while we are only testing the plumbing):
  1. Shortly after the 17:00 New York close (that is also the start of the next FX day): `refresh`, then `signals`.
  2. Act on the sheet at the new day's open: close what it says to close; open what it says to open.
  3. EVERY entry gets a real stop-loss order at the broker: stop = FILL price -/+ the stop distance on the sheet
     (not the last close). Never rely on this script to stop you out.
  4. `record` what you actually did (use your real fill prices) so the next sheet knows your positions.

The sheet uses only CLOSED bars. The strategy is the pre-registered Donchian spec whose backtest FAILED;
this is an execution test, not evidence of an edge. Do not use real money.
"""
from __future__ import annotations
import argparse, csv, datetime as dt, json, os, sys
import pandas as pd
from mt5bot.data import validate_daily
from mt5bot.live import MARKET_SPECS, SPEC, Position, closed_bars, decide, lots_for, stop_hit

DATA_DIR, STATE_FILE, LOG_FILE = "data/universe_daily", "state/positions.json", "logs/signals.csv"
MARKETS = list(MARKET_SPECS)


def costs():
    from run_portfolio_test import COSTS
    return COSTS


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(st: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=2)


def now_utc(a) -> pd.Timestamp:
    return pd.Timestamp(a.now, tz="UTC") if getattr(a, "now", None) else pd.Timestamp.now(tz="UTC")


def current_label(now: pd.Timestamp) -> pd.Timestamp:
    return (now.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=7)).normalize()


def cmd_refresh(a):
    import download_universe as du
    end = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    sys.argv = ["download_universe.py", "--end", end, "--no-csv"]
    du.main()
    print("\nNOTE: Dukascopy's free monthly files exist only for COMPLETED months, so the data now ends at the last day of\n"
          "the previous month at best. For a live sheet you need the days since then from another source (section 13).")


def cmd_signals(a):
    now, st, C = now_utc(a), load_state(), costs()
    cl = current_label(now)
    expected_last = cl - pd.offsets.BDay(1)            # label of the most recent bar that should have closed
    rows, total_new_risk, problems = [], 0.0, []
    print(f"\nSIGNAL SHEET   generated {now:%Y-%m-%d %H:%M} UTC   (FX day now forming: {cl:%Y-%m-%d})   equity {a.equity:,.0f}   risk/trade {a.risk:.2%}")
    print("Act at the new day's open. Place a broker stop-loss with EVERY entry: stop = fill -/+ stop distance.\n")
    for name in MARKETS:
        p = os.path.join(a.data_dir, f"{name}_D1.csv")
        if not os.path.exists(p):
            print(f"{name:7s} no data file - run `refresh`"); continue
        d = pd.read_csv(p, index_col=0, parse_dates=True)
        issues = validate_daily(d, name)
        if issues:
            problems += issues
        d = closed_bars(d, now)
        last = d.index[-1]
        spread, slip, _ub = C[name]
        stale = last < expected_last - pd.offsets.BDay(1)     # allow one missing day (holiday)
        if stale:
            problems.append(f"{name}: data ends {last:%Y-%m-%d} but the latest closed bar should be about {expected_last:%Y-%m-%d} - run `refresh`")
        ps = st.get(name)
        pos = Position(**ps) if ps else None
        inferred_stop = False
        if pos is not None:
            since = d[d.index >= pd.Timestamp(pos.opened)]
            inferred_stop = any(stop_hit(pos, r, spread) for _, r in since.iterrows())
        eff_pos = None if inferred_stop else pos
        dec = decide(d, eff_pos)
        px = float(d["close"].iloc[-1])
        status = "FLAT" if eff_pos is None else ("LONG" if eff_pos.side == 1 else "SHORT")
        if inferred_stop:
            status = "FLAT?"
            action = f"STOP PROBABLY HIT (bars show the stop level {pos.stop} was touched) - check your broker, then `record --market {name} --flat`"
        elif eff_pos is not None and dec.close_position:
            action = "CLOSE at open"
            if dec.entry_side == -eff_pos.side:
                action += f" and then OPEN {'LONG' if dec.entry_side == 1 else 'SHORT'} (flip)"
        elif eff_pos is not None:
            action = f"HOLD (broker stop {eff_pos.stop})"
        elif dec.entry_side:
            action = f"OPEN {'LONG' if dec.entry_side == 1 else 'SHORT'}"
        else:
            action = "nothing"
        detail = ""
        opening = (eff_pos is None or dec.close_position) and dec.entry_side != 0 and not inferred_stop
        if opening:
            lots, risk = lots_for(name, a.equity, a.risk, dec.stop_dist, px, spread, slip, a.min_lot, a.lot_step)
            stop_est = px - dec.stop_dist if dec.entry_side == 1 else px + dec.stop_dist
            if lots > 0:
                total_new_risk += risk
                detail = f"stop distance {dec.stop_dist:.5g} (stop ~{stop_est:.5g} if filled near {px:.5g}); size ~{lots:g} lots (risk ~{risk:,.0f}, {risk / a.equity:.2%})"
            else:
                detail = (f"stop distance {dec.stop_dist:.5g}; SKIP: even the minimum lot ({a.min_lot:g}) would risk ~{risk:,.0f} "
                          f"({risk / a.equity:.1%} of equity) > {a.risk:.2%} intended")
        rows.append((name, str(last.date()), status, action, detail))
        print(f"{name:7s} last closed bar {last:%Y-%m-%d}  {status:6s} -> {action}")
        if detail:
            print(f"        {detail}")
    print(f"\nNew risk if you take every OPEN above: ~{total_new_risk / a.equity:.2%} of equity")
    for pr in problems:
        print("WARNING:", pr)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["generated_utc", "market", "last_closed_bar", "status", "action", "detail"])
        for r in rows:
            w.writerow([f"{now:%Y-%m-%d %H:%M}", *r])
    if problems:
        sys.exit(1)


def read_broker_d1(path: str) -> pd.DataFrame:
    """Read a daily-bars CSV: MT5 'Export Bars' (tab-separated, <DATE> [<TIME>] <OPEN> <HIGH> <LOW> <CLOSE> ...)
    or any CSV with date/open/high/low/close columns. Dates are parsed with explicit formats (never guessed)."""
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]
    need = ["open", "high", "low", "close"]
    if not all(c in df.columns for c in need):
        sys.exit(f"{path}: needs open/high/low/close columns, found {list(df.columns)}")
    dcol = next((c for c in ("date", "time", "datetime", "gmt time") if c in df.columns), df.columns[0])
    raw = df[dcol].astype(str).str.strip().str.slice(0, 10)
    ts = None
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
        t = pd.to_datetime(raw, format=fmt, errors="coerce")
        if t.notna().mean() > 0.99:
            ts = t
            break
    if ts is None:
        sys.exit(f"{path}: could not read the dates in column '{dcol}' (expected yyyy.mm.dd or yyyy-mm-dd)")
    out = df[need].astype(float)
    out.index = pd.DatetimeIndex(ts, name="date")
    out = out[out.index.notna()]
    return out[~out.index.duplicated(keep="last")].sort_index()


def cmd_import(a):
    import shutil
    if a.market not in MARKET_SPECS:
        sys.exit(f"unknown market {a.market}")
    spread = costs()[a.market][0]
    p = os.path.join(a.data_dir, f"{a.market}_D1.csv")
    if not os.path.exists(p):
        sys.exit(f"{p} not found - run `refresh` first")
    d = pd.read_csv(p, index_col=0, parse_dates=True)
    b = read_broker_d1(a.file)
    wk = int((b.index.dayofweek >= 5).sum())
    b = b[b.index.dayofweek < 5]
    if wk:
        print(f"note: dropped {wk} Saturday/Sunday bar(s) from the file (stub sessions; their few hours of range are ignored)")
    last = d.index[-1]
    ov = b.index.intersection(d.index)
    if len(ov) >= 5:
        med = float((b.loc[ov, "close"] - d.loc[ov, "close"]).abs().median())
        tol = 6 * spread
        print(f"alignment check on {len(ov)} overlapping days: median |close difference| {med:.5g} (limit {tol:.5g})")
        if med > tol and not a.force:
            sys.exit("MISALIGNED: the file's daily bars do not line up with the Dukascopy bars (different day boundary or "
                     "a different instrument/price). Not imported. Use --force only if you understand why.")
    elif not a.force:
        sys.exit(f"only {len(ov)} overlapping days with the existing data (need >= 5 to verify alignment). "
                 f"Export from about 15 trading days before {last:%Y-%m-%d}, or use --force.")
    new = b[b.index > last]
    if new.empty:
        print(f"{a.market}: nothing newer than {last:%Y-%m-%d} in the file"); return
    gap = len(pd.bdate_range(last + pd.Timedelta(days=1), new.index[0])) - 1
    if gap > 1 and not a.force:
        sys.exit(f"{gap} weekdays are missing between {last:%Y-%m-%d} and {new.index[0]:%Y-%m-%d}; indicators would be wrong. "
                 "Export a longer range, or use --force.")
    new = new.assign(candles=24)[["open", "high", "low", "close", "candles"]]   # candle count unknown for imported bars
    merged = pd.concat([d[["open", "high", "low", "close", "candles"]], new])
    merged.index.name = "date"
    issues = validate_daily(merged, a.market)
    shutil.copy(p, p + ".bak")
    merged.to_csv(p)
    print(f"{a.market}: added {len(new)} bar(s), {new.index[0]:%Y-%m-%d} -> {new.index[-1]:%Y-%m-%d}  (backup: {p}.bak)")
    for i in issues:
        print("WARNING:", i)


def cmd_record(a):
    st = load_state()
    if a.market not in MARKET_SPECS:
        sys.exit(f"unknown market {a.market}")
    if a.flat:
        st.pop(a.market, None); save_state(st); print(f"{a.market}: recorded FLAT"); return
    if not (a.side and a.entry and a.stop):
        sys.exit("record needs --side, --entry and --stop (or --flat)")
    side = 1 if a.side == "long" else -1
    if (side == 1 and a.stop >= a.entry) or (side == -1 and a.stop <= a.entry):
        sys.exit("stop is on the wrong side of the entry price")
    opened = a.date or f"{current_label(now_utc(a)):%Y-%m-%d}"
    st[a.market] = dict(side=side, entry=a.entry, stop=a.stop, lots=a.lots or 0.0, opened=opened)
    save_state(st); print(f"{a.market}: recorded {a.side} entry {a.entry} stop {a.stop} lots {a.lots or 0.0} opened {opened}")


def cmd_show(a):
    st = load_state()
    if not st:
        print("no open positions recorded"); return
    for m, p in st.items():
        print(f"{m:7s} {'long' if p['side'] == 1 else 'short':5s} entry {p['entry']} stop {p['stop']} lots {p['lots']} opened {p['opened']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh")
    s = sub.add_parser("signals")
    s.add_argument("--equity", type=float, required=True); s.add_argument("--risk", type=float, default=0.005)
    s.add_argument("--min-lot", type=float, default=0.01); s.add_argument("--lot-step", type=float, default=0.01)
    s.add_argument("--data-dir", default=DATA_DIR); s.add_argument("--now", default=None, help="override the clock, e.g. 2026-10-12T22:30 (UTC), for testing")
    r = sub.add_parser("record")
    r.add_argument("--market", required=True); r.add_argument("--side", choices=["long", "short"])
    r.add_argument("--entry", type=float); r.add_argument("--stop", type=float); r.add_argument("--lots", type=float)
    r.add_argument("--flat", action="store_true"); r.add_argument("--date", default=None); r.add_argument("--now", default=None)
    im = sub.add_parser("import")
    im.add_argument("--market", required=True); im.add_argument("--file", required=True)
    im.add_argument("--data-dir", default=DATA_DIR); im.add_argument("--force", action="store_true")
    sub.add_parser("show")
    a = ap.parse_args()
    {"refresh": cmd_refresh, "signals": cmd_signals, "record": cmd_record, "show": cmd_show, "import": cmd_import}[a.cmd](a)


if __name__ == "__main__":
    main()
