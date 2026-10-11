# Automated Demo Trading Plan (MT5) - design, safety and edge cases

*Version 1, 2026-10-10. Applies to mt5bot v6.1 (`mt5bot/live.py`, `signal_runner.py`, `check_live.py`).*

## 1. Purpose and honest framing

- **What this is:** a fully automated bot trading on an MT5 **demo** account, with a journal and weekly reports that track its progress.
- **What this is not:** evidence of profit. The strategy inside (Donchian 55/20 trend-following, 8 markets) failed its pre-registered test twice (Sharpe -0.06, CAGR -0.7%, max drawdown -32% at 0.5% risk per trade). A demo of this strategy produces about 3 to 4 trades a month, so months of demo trading cannot change that verdict.
- **Goal of the run:** prove the plumbing. Signals become orders, every order has a broker-side stop, state reconciles, and the real costs (spread, slippage, swap) can be compared with what the backtest assumed.
- **"Less negative" design:** this plan limits the size and speed of losses (small risk per trade, caps, drawdown ladder, kill switches, stops at the broker). It cannot guarantee a profit, and a strategy without an edge still tends to lose slowly. Every limit below is pre-specified and **not tuned on historical results**, and stays fixed for the whole run so results remain interpretable.
- **Rule that does not change:** no real money unless a strategy passes a pre-registered test. A good demo is not such a test.

## 2. Architecture

```
 Broker feed -- MT5 terminal (Wine on Fedora) -- Expert Advisor (EA)
                                                    |  writes: bars, symbol specs, account, positions,
                                                    |          deals, heartbeat
                                              bridge folder  (plain files, atomic writes)
                                                    |  reads: order intents, HALT / FLATTEN flags
 Python runner (Linux) -- checks -> decide() -> risk overlays -> order intents; journal; reports
```

| Part | Responsibility | Never does |
|---|---|---|
| **Python runner** | Reads exported bars, runs the same `decide()` as the backtests, applies risk overlays, writes order intents, keeps the journal, builds reports | Talks to the broker directly |
| **EA** | Exports data, executes intents with hard limits of its own, attaches the stop-loss, writes results | Decides what to trade |
| **Broker stop-loss** | Protects every position even if Python, the EA or the laptop is down | |

**Bridge folder** (path configured once, verified at start-up; under Wine it is in the MT5 data folder or the Common Files folder):

| File | Writer | Content |
|---|---|---|
| `bars/<SYMBOL>_D1.csv` | EA | broker daily bars with open time, OHLC, spread |
| `specs.json` | EA | per symbol: contract size, tick size and value, min/max/step lot, stops level, freeze level, filling modes, trade mode, current and median spread |
| `account.json` | EA | login, currency, balance, equity, margin, margin mode (netting or hedging), leverage, connected and trade-allowed flags |
| `positions.json`, `deals.csv` | EA | open positions with stop, swap, magic number; closed deals with prices |
| `heartbeat.txt` | EA | timestamp and server time, refreshed every minute |
| `orders/<id>.json` | Python | one order intent (action, symbol, side, volume, stop distance, expiry, plan reference) |
| `results/<id>.json` | EA | executed, rejected or expired, with fill price, slippage, retcode |
| `HALT`, `FLATTEN` | you or Python | HALT = no new entries; FLATTEN = close all positions of this bot |

Files are written to a temporary name, then renamed (atomic), and carry a row count so a reader ignores anything half-written.

## 3. Daily timeline (America/New_York)

| Time | Event |
|---|---|
| 17:00 | FX roll: the daily bar closes, spreads are wide for 10 to 20 minutes, swap is applied |
| 17:05 | EA exports bars and state |
| 17:10 | Python run (systemd timer set in the New York timezone): health checks, import bars, reconcile, `decide()`, overlays, write intents. Intents expire at 17:40 |
| 17:10-17:40 | EA executes when the spread is acceptable; attaches stops; writes results |
| 17:45 | Python reads results, journals, checks stops are in place |
| 17:50 | Daily health report |

Notes:
- The backtest assumes the fill at the daily open. Live fills come minutes later. **Implementation shortfall** (fill versus the broker's D1 open) is measured and reported, and the model's 0.1 pip slippage will probably prove optimistic at the roll.
- 17:00 New York is roughly midnight to 1 am in Kenya (UTC+3). The laptop must be awake, powered and online then (section 5, rows 40 and 41).
- Scheduling is always in the New York timezone, so the UTC time shifts by an hour twice a year by design.

## 4. Safety layers

| Layer | Checks |
|---|---|
| **1. Python preflight** | heartbeat fresh; account login matches the configured demo account; account currency is USD; bars fresh, aligned and gap-free; journal reconciles with `positions.json`; drawdown ladder state; HALT absent; config hash matches the frozen run config |
| **2. EA hard limits** (independent of Python) | no order without a stop; risk per trade and total open risk caps recomputed from its own data; maximum positions; margin cap; spread cap; order expiry; magic number so it only touches its own orders; processed-ID store so a restart cannot repeat an order; kill on FLATTEN |
| **3. Broker-side stop-loss** | on every position from the moment it is opened |

Any layer can refuse an order. No layer can override another.

## 5. Edge-case register

### Data and time
| # | Situation | Detection | Response |
|---|---|---|---|
| 1 | Stale bars (export older than expected) | last bar label versus expected; heartbeat age | halt for the day, notify; existing stops stay active |
| 2 | Missing weekday in bars | gap check | allowed only for known FX holidays (Dec 25, Jan 1); otherwise halt that market |
| 3 | Broker daily boundary not at 17:00 New York (server-time DST rules can differ for a few weeks a year) | expected candle times in exported hourly bars; weekly audit against Dukascopy once the month is published | halt that market until aligned; log |
| 4 | Sunday or Saturday stub bars in broker data | weekday label check | dropped (as `import` already does) |
| 5 | Level jump at the seam between Dukascopy history and broker bars | alignment check on 5 or more overlapping days, median close difference at most 6x spread | refuse the import |
| 6 | Bad tick or spike bar | latest bar range far outside recent ATR | flag; no trade on that market until reviewed |
| 7 | Thin holiday days (few candles) | candle count | accept at 4 or more candles, else treat as missing |
| 8 | Laptop clock drift | compare with the EA's server time and NTP | halt if drift exceeds 60 seconds |
| 9 | DST changes (New York or Europe) | timer defined in New York time; next-run time printed | re-verify alignment the week after each change |

### Broker and symbol
| # | Situation | Detection | Response |
|---|---|---|---|
| 10 | Symbol suffix or different name (EURUSD.m, GOLD) | symbol map file; EA confirms the symbol exists and is tradable | halt that market if unmapped |
| 11 | Contract size or tick value differs (gold especially) | `specs.json` against the expected table | size with the real tick value; halt if far from the expected contract size and not in the map |
| 12 | Account currency not USD | `account.json` | halt (first version does not convert) |
| 13 | Netting versus hedging account | margin mode | one position per symbol either way; the EA never opens a second position on a symbol |
| 14 | Lot limits and step | `specs.json` | round down; skip and record SKIP if the minimum lot would over-risk |
| 15 | Stops level or freeze level | `specs.json` | keep the stop at least the minimum distance away; skip if impossible |
| 16 | Filling mode not supported | symbol filling flags | use a supported mode; otherwise halt that market |
| 17 | Trading disabled, session closed, holiday | trade mode, retcode | retry inside the window, then expire and record MISSED |
| 18 | Demo account reset, expired, or server maintenance | login mismatch; heartbeat gap | halt; you re-confirm the account number manually |
| 19 | Broker changes spreads, commission or swap | exported per day | tracked in the weekly report |

### Execution
| # | Situation | Detection | Response |
|---|---|---|---|
| 20 | Wide spread at the roll | spread above 3x the symbol's median, or above a hard cap | wait until the intent expires; skip if still wide |
| 21 | Requote, price changed, off quotes, timeout | retcodes | up to 3 retries, 5 seconds apart, transient errors only |
| 22 | Invalid stops, invalid volume, not enough money | retcodes | no retry; log; skip |
| 23 | Fill slips far from plan | fill versus expected | if actual risk to the stop exceeds 1.25x the planned risk, close at once and log; the deviation parameter limits slippage at send |
| 24 | Stop-loss missing or rejected after a fill | position check right after the fill | the EA sets it; if it still fails after 3 tries, close the position (never leave one naked) |
| 25 | Partial fill | filled versus requested volume | keep it, set the stop on the filled volume, no top-up, record |
| 26 | Stop triggered by a gap (weekend, news, peg break) | deal record | journal slippage versus stop; the next signal handles re-entry |
| 27 | Flip signal (close one side, open the other) | | close first and confirm it closed; open only then; if the close fails, do not open |
| 28 | Several markets signal at once | | closes first; opens in a fixed priority order until a cap is reached; skipped ones are logged |
| 29 | Trade context busy, too many requests | retcode | back off and retry within the window |
| 30 | Swap at rollover and triple swap on Wednesdays | exported per position | compared with the modelled financing in the report |

### State and restart
| # | Situation | Detection | Response |
|---|---|---|---|
| 31 | Python crash mid-run | intent files plus append-only journal | next run reconciles; intents are idempotent by ID |
| 32 | EA or terminal restart | persistent processed-ID store | never repeats an ID |
| 33 | Duplicate order file | same ID | ignored |
| 34 | Old intents after the laptop was asleep | expiry timestamp | EA ignores expired intents |
| 35 | Journal disagrees with MT5 (position in one only) | reconcile on every run | the broker is the truth; halt new entries until cleared |
| 36 | Manual trade placed on the same account | magic number | never touched, counted in exposure, warning raised |
| 37 | Half-written files | atomic rename and row counts | ignored until complete |
| 38 | Disk nearly full or logs growing | free-space check | rotate logs; halt below a floor |

### Platform and operations
| # | Situation | Detection | Response |
|---|---|---|---|
| 39 | Wine or MT5 freeze or crash | stale heartbeat | halt; optional auto-restart script; notify |
| 40 | Laptop asleep, off or power cut near midnight Kenya time | missed run | no late chasing of entries; existing stops stay active; exits run at the next window and are recorded as late; disable suspend during the window |
| 41 | Internet outage | EA connected flag in the heartbeat | same as row 40; stops live at the broker |
| 42 | AutoTrading disabled or EA removed | trade-allowed flag | halt and notify |
| 43 | MT5 or Wine update changes behaviour | version string in the heartbeat | pin versions; rerun the dry-run tests after any update |
| 44 | Path or permission differences under Wine | start-up self-test writes and reads a test file in the bridge folder | halt if it fails |
| 45 | Time zone mix-ups | | schedule in New York time, log in UTC |

### Strategy and market events
| # | Situation | Detection | Response |
|---|---|---|---|
| 46 | Scheduled news close to the window | rare at 17:00 New York | accept; slippage is journaled |
| 47 | Flash crash or extreme volatility | spread and slippage rules | skip entries; rows 20 and 23 apply |
| 48 | Gold stop too wide for the minimum lot | sizing | skip and record SKIP with the risk the minimum lot would carry |
| 49 | Currency peg break or similar gap (CHF in January 2015 is in the history) | cannot be prevented | the per-trade and total-risk caps limit the damage |
| 50 | Live signal differs from the backtest logic | each day, `decide()` is rerun offline on the stitched series and compared with the live run | any mismatch flagged and the day's entries halted |
| 51 | Partial bar used by mistake | `closed_bars()` | already guarded |

### Human
| # | Situation | Response |
|---|---|---|
| 52 | Wanting to override the bot | only through HALT or FLATTEN, recorded in the journal as an override |
| 53 | Changing parameters mid-run | the config hash is recorded; a change starts a new, separately labelled run |

## 6. Downside-limiting settings (pre-specified defaults, frozen for the run)

| Setting | Default | Reason |
|---|---|---|
| Risk per trade | 0.25% of equity (backtest used 0.5%) | roughly halves loss size and drawdown depth; Sharpe is unchanged by scaling |
| Total open risk cap | 2% of equity | limits the loss if everything stops out together |
| Max open positions | 5 | |
| USD cluster cap | at most 2 positions on the same side of the dollar | seven of the eight markets are USD pairs and move together |
| Drawdown ladder (from peak equity) | -4%: risk x0.5; -8%: no new entries; -12%: flatten and stop the run | de-risks automatically; it limits depth but also slows recovery |
| Daily loss limit | -1.5% of start-of-day equity: no new entries that day | |
| Spread filter | skip if above 3x the symbol's median or the hard cap | avoids roll-time spikes |
| Max planned-risk overrun at fill | 25% | row 23 |
| Margin cap | used margin at most 25% of equity | |
| Intent validity | 30 minutes | no late chasing |
| Stops | broker-side on every position; never moved wider | |

Considered but not included: skipping Friday entries to avoid weekend gaps, news filters, discretionary exits. There is no evidence here that they help, and each adds a rule that would need its own test.

An offline overlay backtest can show what each limit would have done over 2003 to 2026. That would be informational only. The defaults must not be tuned on it.

## 7. Journal and tracking

- **Store:** SQLite `journal.db` plus weekly CSV exports. Tables: runs (config hash), signals, intents, orders, fills, position snapshots, daily equity, health events, overrides.
- **Paper twin (the key benchmark):** every day the same signals are run through the backtest engine's fill rules on the broker's bars with the model's costs. Demo P&L versus the twin separates execution cost from strategy results.
- **Weekly report:** equity and drawdown; open positions and stops; trades; fill versus D1 open (shortfall); spread paid versus model; swap versus the 2% per year assumption; signal match rate against the offline rerun; rejections, skips, missed windows; heartbeat uptime; drawdown-ladder state.

## 8. Demo success and kill criteria

**Success is about execution, not profit:**
- 95% or more of signal days executed inside the window
- 100% of positions carry a stop
- median slippage within 2x what the model assumes
- zero unresolved reconciliation mismatches
- signal match rate against the offline rerun is 100%

**Stop the run immediately if:** a position is ever found without a stop; a reconciliation mismatch stays unresolved for more than a day; the -12% ladder level is hit; or repeated unexplained rejections occur.

## 9. Build and test plan

| Phase | What happens | Duration (rough) |
|---|---|---|
| P0 | Install MT5 under Wine, open a demo account, record symbol specs, run the bridge-folder self-test | you |
| P1 | EA exports only (no trading). Validate bar alignment against Dukascopy for the month and compare spreads | 2 weeks |
| P2 | Dry run: the full pipeline writes intents and the EA only logs "would trade". Compare with the paper twin | 2 to 4 weeks |
| P3 | Trading on the demo at 0.1% risk for two weeks, then the default | 2 weeks, then ongoing |
| P4 | Review against section 8 | |

**Fault-injection tests before P3:** kill Python mid-run; delete the heartbeat; send a duplicate and an expired intent; force a wide-spread rejection; disable AutoTrading; place a manual trade; switch the account currency in a test; power the laptop down inside the window.

## 10. What I need from you and what I cannot verify

**Needed:** whether MT5 under Wine runs on your Fedora; the broker and demo account type (netting or hedging, USD currency); the exact symbol names and the XAUUSD specification; whether the laptop can stay on near midnight Kenya time; and how you want alerts (desktop notification, email or Telegram).

**I cannot verify from here:**
- MQL5 compilation and EA behaviour (expect a few rounds with your compile errors and logs)
- Wine behaviour on your machine
- broker-specific rules
- a reliable free source of recent bars apart from the MT5 export

## 11. Honest expectations

- The best realistic outcome of this run is a trustworthy automated pipeline and a measured picture of real trading costs.
- The strategy itself is expected to stay flat to slightly negative. If so, the plumbing is reusable for a different strategy that passes a proper test.
- Risk limits make losing survivable. They do not make winning likely.
