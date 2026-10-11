#!/usr/bin/env python3
"""Phase 1: read what the MT5 export EA (MT5BotExport.mq5) wrote, check it, and import the broker's daily bars.

    python bridge_sync.py                         # finds the bridge folder automatically
    python bridge_sync.py --bridge-dir "/path/to/Common/Files/bridge"
    python bridge_sync.py --find                  # just list candidate bridge folders

Safety: this script refuses to continue unless the MT5 account is a DEMO account.
It places no orders and cannot; it only reads files and updates data/universe_daily/*.csv
(each import keeps a .bak copy and runs the same alignment check as `signal_runner.py import`).
"""
from __future__ import annotations
import argparse, datetime as dt, glob, json, os, sys
from types import SimpleNamespace

import signal_runner as sr
from mt5bot.live import MARKET_SPECS

PATTERNS = [
    "~/.mt5/drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files/bridge",
    "~/.wine/drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files/bridge",
]


def candidates() -> list[str]:
    out = []
    for p in PATTERNS:
        out += glob.glob(os.path.expanduser(p))
    return sorted(set(out))


def read_json(path: str):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        sys.exit(f"{path} is not valid JSON ({e}). The EA may have been interrupted; wait a minute and retry.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bridge-dir", default=None)
    ap.add_argument("--data-dir", default=sr.DATA_DIR)
    ap.add_argument("--max-age", type=int, default=300, help="max heartbeat age in seconds (default 300)")
    ap.add_argument("--find", action="store_true")
    ap.add_argument("--force", action="store_true", help="pass --force to the import step (use only if you understand why)")
    a = ap.parse_args()

    if a.find:
        c = candidates()
        print("\n".join(c) if c else "no bridge folder found yet. Is the EA attached and running? See the setup steps.")
        return
    bridge = a.bridge_dir
    if not bridge:
        c = candidates()
        if not c:
            sys.exit("Could not find the bridge folder. Run:  find ~ -type d -name bridge -path '*MetaQuotes*'\n"
                     "and pass the result with --bridge-dir.")
        if len(c) > 1:
            print("Several bridge folders found, using the most recently modified:")
            c.sort(key=os.path.getmtime)
        bridge = c[-1]
    print(f"bridge folder: {bridge}")

    problems = []
    hb = read_json(os.path.join(bridge, "heartbeat.json"))
    if hb is None:
        sys.exit("No heartbeat.json yet: the EA has not completed an export. Check the Experts tab in MT5.")
    age = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.datetime.fromisoformat(hb["utc"])).total_seconds()
    print(f"heartbeat: {hb['utc']} UTC ({age:.0f}s ago)  connected={hb.get('connected')}  markets exported={hb.get('markets_exported')}  build={hb.get('build')}")
    if age > a.max_age:
        problems.append(f"heartbeat is {age:.0f}s old (limit {a.max_age}s): MT5 or the EA is not running, or the laptop clock is off")
    if not hb.get("connected"):
        problems.append("MT5 reports it is NOT connected to the broker")

    acc = read_json(os.path.join(bridge, "account.json"))
    if acc is None:
        sys.exit("No account.json found.")
    print(f"account: login {acc['login']} | {acc['company']} / {acc['server']} | {acc['trade_mode_text']} | {acc['margin_mode_text']} | "
          f"{acc['currency']} | leverage 1:{acc['leverage']} | equity {acc['equity']}")
    if acc.get("trade_mode") != 0:
        sys.exit(f"REFUSING: this MT5 account is '{acc['trade_mode_text']}', not DEMO. This project only runs on demo accounts.")
    if acc.get("currency") != "USD":
        problems.append(f"account currency is {acc['currency']}, not USD: position sizing assumes USD, so do not trade this account yet")
    if acc.get("margin_mode_text") == "exchange":
        problems.append("exchange margin mode is not supported")

    specs = (read_json(os.path.join(bridge, "specs.json")) or {}).get("symbols", {})
    print("\nsymbol specs (expected contract size in brackets):")
    for m, exp in MARKET_SPECS.items():
        s = specs.get(m)
        if not s:
            problems.append(f"{m}: no spec exported (symbol missing at this broker or suffix wrong)")
            continue
        flag = "" if abs(s["contract_size"] - exp["contract"]) < 1e-9 else "   <-- DIFFERENT: sizing must use the broker value"
        if flag:
            problems.append(f"{m}: contract size {s['contract_size']} differs from the expected {exp['contract']}")
        print(f"  {m:7s} contract {s['contract_size']:>9g} [{exp['contract']:g}]  min lot {s['volume_min']:g}  step {s['volume_step']:g}  "
              f"spread {s['spread_points']} pts  stops level {s['stops_level']}  swap L/S {s['swap_long']:g}/{s['swap_short']:g}")

    print("\nimporting broker daily bars:")
    done = 0
    for m in MARKET_SPECS:
        f = os.path.join(bridge, "bars", f"{m}_D1.csv")
        if not os.path.isfile(f):
            problems.append(f"{m}: no bars file yet")
            continue
        try:
            sr.cmd_import(SimpleNamespace(market=m, file=f, data_dir=a.data_dir, force=a.force))
            done += 1
        except SystemExit as e:
            problems.append(f"{m}: {e.code}")
    print(f"\n{done}/{len(MARKET_SPECS)} markets processed")
    for p in problems:
        print("PROBLEM:", p)
    if not problems:
        print("All checks passed. Next:  python signal_runner.py signals --equity <demo equity>")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
