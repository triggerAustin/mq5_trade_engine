# MT5 automated trading project: full status handoff (v2)

*Written 2026-10-10 (Saturday) for a second AI model to review. Companion to the earlier `HANDOFF.md` / `HANDOFF_summary.md`, which hold the verbatim code and the first two failed tests. This document covers the whole project to date and what is open.*

---

## 0. How to use this document

You are being asked for an independent second opinion. Please be adversarial:

1. Look for flaws in the methodology (sections 4 and 5), especially anything that could make a result look worse or better than it is.
2. Look for flaws in the plan (sections 7 and 9), especially the order of work and the assumptions about the broker.
3. Propose the strongest next experiment you can defend (section 10), under the constraints in section 2.
4. Say clearly where you think stopping is the right call.

Things stated here as **verified** were actually run or observed. Things stated as **unverified** were not, and I (the previous model) have flagged them as such.

---

## 1. The person and the goal

- Wants to make money trading on MetaTrader 5 (MT5) through automation. Said: "you are the brains". **No trading knowledge.**
- **Hardware:** a Fedora Linux laptop (Sway window manager). No Windows machine. **No VPS** and cannot rent one now.
- **Connection:** slow and unreliable (Kenya, timezone UTC+03:00). Downloads from some hosts crawl at ~30 kB/s.
- **Capital:** under $500 for real money, if it ever gets that far.
- **Maximum tolerable drawdown from peak:** about 20%.
- **Chosen direction (latest):** cross-asset trend-following, picked from options A (cross-asset trend), B (currency carry), C (index with risk control). The recommended option was taken.
- The person asked for a stopping recommendation once. I said plainly that stopping is a defensible choice, because two pre-registered tests failed. They chose to continue with a disciplined redesign.

## 2. Ground rules that were adopted (please hold the project to these)

1. **No real money** until a strategy survives a fair, pre-registered, out-of-sample test.
2. **Costs are always charged** (spread, slippage, and a financing stand-in in the stress case).
3. The engine **must show no profit on random data**. A surprising result is assumed to be a bug first.
4. Pass/fail rules are written **before** the data is looked at.
5. A **locked-box holdout** is used for any redesign: develop on older data, then run the sealed recent period once.
6. Demo trading is for **plumbing and cost measurement only**, never as evidence of edge.

## 3. Where things stand (one paragraph)

Two families of strategies have been tested and **both failed validation**: single-pair EURUSD (breakout and mean reversion on H1/H4/D1) and an 8-market daily Donchian trend-following portfolio. A research pipeline, a verified backtester and portfolio simulator, real Dukascopy data (2003 to 2026), and a working MT5-to-Python bridge on a demo account now exist. **There is no strategy that has passed a test, so there is nothing to trade with real money.** The current work is (a) a read-only export of broker data to Python, and (b) a redesign toward cross-asset trend-following, which is blocked on knowing which non-FX symbols the broker offers and how far back their data goes.

---

## 4. Research infrastructure (all verified)

### 4.1 Data
- **Source:** Dukascopy's public candle API (`jetta.dukascopy.com/v1/candles/hour/<PAIR>/BID/<year>/<month>`). It needs browser-like headers (User-Agent, Origin, Referer). Responses are delta-encoded month JSON, rebuilt with integer arithmetic. The current month returns HTTP 400 and is treated as "no data". `dukascopy-node` did not work (HTTP 202).
- **Universe downloaded (daily bars cut at 22:00 UTC, i.e. a 17:00 New York roll):** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD, 2003-06 to 2026-09. Files: `data/universe_daily/<MKT>_D1.csv`. EURUSD hourly is also held (about 2003 to 2026), in two CSVs.
- Per-month cache means downloads are resumable and never repeated.
- **Data bugs found and fixed:** a `dayfirst=True` date-parsing bug that swapped day and month on ISO dates (this produced 21,468 mis-parsed bars and a future end date); the loader now parses ISO8601 first and rejects non-monotonic timestamps or an end date more than 2 days in the future.

### 4.2 Backtesters
- `mt5bot/backtest.py`: single-market, bar-based. Signals from the close of bar j-1, execution at the open of bar j. Data is BID. Longs enter at ask (open + spread + slippage), exit at bid; shorts mirror. ATR(14) Wilder stops checked intrabar; a gap fills at the open; stop beats a same-bar signal exit. Fixed-fractional sizing with lot rounding. Min-lot trades are skipped rather than over-risked.
- `mt5bot/portfolio.py`: multi-market, one shared USD equity pool, mark-to-market sizing, same execution rules. USD-quote P&L is `side*N*(exit/entry-1)`. USD-base pairs use `side*N*(exit-entry)/exit`. Optional financing drag (a % per year of notional) as a swap stand-in.
- `mt5bot/strategies.py`: Donchian breakout, z-score mean reversion, session filter, trend filter.

### 4.3 Critical bug found and fixed (important to the credibility of everything)
After an **intrabar stop-out**, the engine re-entered at that same bar's open, which is a stale price (trading in the past). This inflated results. Fix: a `stopped_bar` flag blocks re-entry on the bar where a stop fired. Earlier results from the buggy engine were **retracted**. I had earlier claimed a random-data test "passed"; that claim was wrong.

### 4.4 Validation of the engines (self-tests; all must print ALL CHECKS PASSED)
- `check_engine.py` and `check_portfolio.py`:
  - zero-cost random-walk neutrality using true-path (sub-bar) synthetic data (no edge may appear);
  - an independent reference simulator;
  - single-market engine vs portfolio engine, trade-for-trade equivalence (same timing and prices);
  - a mutation test (re-introduce the bug and confirm the test fails).
- Thresholds were first too strict and produced a false FAIL; they were loosened on statistical grounds (40 runs of 20k hours; |avg R| < 0.02).

---

## 5. Results so far (both FAIL)

### 5.1 EURUSD single pair (exploratory, 292 configurations)
Breakout and mean reversion on H1/H4/D1, trained 2003 to 2017 / tested later, at "standard" and "harsh" costs. Nothing survived out of sample with realistic costs. **Caveat:** 292 configs is a large multiple-comparison surface, so even the best in-sample results were discounted heavily. Single-pair D1 results at a $1,000 account were mostly zero trades because of min-lot rounding; rerun at $10k.

### 5.2 Pre-registered multi-market daily trend test (the real test)
- **Spec (fixed before looking at data):** 8 markets above. Donchian breakout 55 / exit 20, ATR(14) x 3 stop. Next-open execution. Long and short. One position per market. 0.5% of portfolio equity risked per position. Costs per market (price units, spread / slippage): EURUSD 0.00010 / 0.00001, GBPUSD 0.00013 / 0.00001, USDJPY 0.010 / 0.001, AUDUSD 0.00012 / 0.00001, USDCAD 0.00015 / 0.00002, USDCHF 0.00015 / 0.00002, NZDUSD 0.00015 / 0.00002, XAUUSD 0.30 / 0.05. "Harsh" = 2x costs plus 2% a year financing.
- **Pass rule:** realistic Sharpe >= 0.50 over the full period AND >= 0.20 in each half (split 2014-12-31) AND harsh Sharpe >= 0.30.
- **Result:** FAIL. The other model's plan document reports Sharpe about -0.06, CAGR about -0.7%, max drawdown about -32% at 0.5% risk. (I did not re-derive these here; see the earlier handoff for the original printout.)
- **Interpretation:** consistent with a known pattern. The classic trend-following diversification benefit comes mainly from many *uncorrelated* markets (rates, equity indices, commodities). Seven of these eight markets are USD pairs and move together, and 2003 to 2026 FX trends were comparatively weak. The test universe was narrow; this is the stated reason for the cross-asset redesign.

---

## 6. Broker and MT5 facts

- **Constraints:** WebTrader cannot run bots. EAs and the Python MetaTrader5 API need the desktop terminal on Windows. On Linux the terminal runs under Wine. A VPS is a later option. The Python package cannot run natively on Linux, so the chosen route is: **MQL5 Expert Advisor + plain-file bridge + Python on Linux**.
- **Installed (verified):** MT5 via MetaQuotes' official Linux script (`download.terminal.free/...mt5linux.sh`; their help page lists Fedora as supported; run without sudo). Wine prefix `~/.mt5`.
- **Demo account (verified, from `bridge_sync.py` output):** MetaQuotes-Demo server, account type demo, **hedging**, **USD**, leverage 1:100, equity **100,000** (the default; not changed).
- **Symbol specs from the broker (verified):** all eight contract sizes match expectations (FX 100,000, XAUUSD 100). Min lot 0.01 and step 0.01 for all. Stops level 0. Spreads quoted on a Saturday are not reliable (NZDUSD 37 pts, XAUUSD 32 pts, stale).
- **Alignment check (verified):** MetaQuotes daily bars (server time, closing at 17:00 New York) vs Dukascopy daily bars over 394 overlapping days: median close differences are tiny relative to limits (EURUSD 8e-05, XAUUSD 0.958 vs a limit of 1.8). So the two sources can be stitched.
- **Symbol universe on MetaQuotes-Demo (verified):** 12,306 symbols. First 300 matches (from a keyword filter) showed:
  - `Metals\`: XAUUSD, XAUEUR, XAUAUD, XAGUSD, XAGEUR, XPDUSD, XPTUSD, XAGAUD, XAUCHF, XAUGBP
  - `Indexes\`: AUS200, UK100, ESP35, EUSTX50, FRA40, HK50, JPN225, US500, US30, USTEC, DE40, CA60, CHINA50, CHINAH, IT40, NETH25, NOR25, SA40, SE30, SWI20, US2000, MIDDE50, TECHDE30 (plus mini variants US30M, US500M, USTECH100M)
  - A very large `Nasdaq\...` stock/ETF/bond-ETN listing (this filled the cap and hid other folders)
  - **Not yet seen:** oil/energy and government-bond futures symbols. Whether they exist is **unknown**.
- **Unknown (blocking):** how far back the broker's daily history goes for the indices and metals. Demo-server CFD history is often much shorter than the 2003 start of the FX data. The scanner's pass 2 (history start dates) has not been run yet.

---

## 7. The MT5-to-Python bridge (built by a different AI, reviewed here)

Another model produced `DEMO_AUTOMATION_PLAN.md`, `MT5BotExport.mq5` and `bridge_sync.py`, which rely on `signal_runner.py` and `mt5bot/live.py` (a "v6.1" codebase). I reviewed the three uploaded files and then **ran Phase 0 and 1 with the user**.

- **Architecture:** MT5 terminal (Wine) + EA <-> bridge folder of plain files (`Common/Files/bridge`, atomic temp-then-rename writes) <-> Python on Linux. Python decides; the EA only exports (Phase 1) and later executes orders with its own hard limits and a broker-side stop on every position.
- **Phase 1 EA (export only):** every minute writes `bars/<MKT>_D1.csv`, `specs.json`, `account.json`, `heartbeat.json`. No trading code. Verified working after fixing one environment issue: MT5 returns error 4401 (history not found) for symbols whose **daily** history has not been downloaded yet; the user had to open a Daily chart for AUDUSD, NZDUSD, XAUUSD (and scroll back) before the EA's `CopyRates` succeeded.
- **`bridge_sync.py` (verified output):** heartbeat fresh, account is demo/USD/hedging, 8/8 symbols exported, 6 new bars imported per market, "All checks passed". It refuses to run on a non-demo account.
- **Plan's later phases (unbuilt):** P2 dry run with intents, P3 demo trading at small risk, P4 review. It specifies drawdown ladder (-4% half risk, -8% no entries, -12% flatten), 0.25% risk per trade, total open risk cap 2%, max 5 positions, daily loss limit 1.5%, spread filter, margin cap. It lists 53 edge cases (stale data, DST, netting vs hedging, requotes, stop rejection, gaps, partial fills, restarts, laptop asleep near the 17:10 New York run time, which is about 00:10 Kenya time).
- **My review (honest):**
  - The plan is candid that the strategy inside it failed twice and that a demo cannot change that verdict (about 3 to 4 trades a month). Its stated purpose is plumbing and cost measurement only. I agree with that framing.
  - Likely first failure point: the EA writes dates as `2026.10.09` (MQL5 `TIME_DATE`); it turned out the importer accepted them.
  - The daily 17:10 New York run needs the laptop awake around midnight in Kenya.
  - The plan does not advance the search for a strategy with an edge. That search is still the bottleneck.
  - I could not compile or run the MQL5 code before the user did; they did compile and run it successfully.

### 7.1 Scanner utility (written this session)
`MT5SymbolScan.mq5` is a one-off MT5 *script* (not an EA, no trading) to list symbols by folder and check history start dates. History: v1 tried to sync history for all 12,306 symbols and hung (my design flaw; it also added every symbol to Market Watch); v2/v3 added caps, flushed output and progress logs; a stuck v1 instance held a file open (error 5004), so output filenames were versioned; v4 (current) adds a per-top-folder count (`folders_v4.csv`), filters by folder prefix, writes `symbols_v4.csv`, and has an optional bounded pass 2 for history start dates (`history_start_v4.csv`, max 15 s per symbol). **v4 has been delivered but not yet run.** The user asked that long-running scripts always log progress (saved to preferences).

---

## 8. Small-account reality check (under $500, about 20% max drawdown)

Not yet tested numerically; this is reasoning, flagged as unverified:
- Minimum lot 0.01. On a $500 account, one 0.01 lot of EURUSD is about $0.10 per pip. A 3 x ATR daily stop on FX is often 100 to 300 pips, i.e. $10 to $30, i.e. **2% to 6% of the account for a single stop-out**, versus the 0.25 to 0.5% the research assumed. A 20% drawdown allowance leaves very little room.
- Gold (100 oz per lot) and index CFDs have bigger minimum exposure; a single stop can cost many percent of $500. Some index CFDs (US500, DE40) may be sized fine on a 0.1-unit contract; contract sizes for the indices are unknown until `symbols_v4.csv` is read.
- Therefore a diversified portfolio at fixed fractional risk is probably infeasible as-is. Either risk per trade must be larger than designed (raising drawdown), or trades are skipped (changing the strategy), or a cent/micro account is needed. A **min-lot feasibility test** is planned alongside the edge test.
- Even if an edge exists, expected absolute profit on $500 is small (tens of dollars a year at realistic volatility targets of roughly 8 to 10% a year). The person has been told this.

---

## 9. Proposed next design (not yet pre-registered)

**Cross-asset trend following with a locked box.**
- **Universe candidates:** FX majors (existing), plus equity indices (US500, DE40, UK100, JPN225, and others), metals (gold, silver), and, if available, oil and government bonds.
- **Rules to pre-specify:** a small, economically motivated set. For example: time-series momentum with a lookback and ATR(14) x k stop, volatility-targeted position size (roughly 8 to 10% annualized portfolio volatility to fit a 20% drawdown tolerance), a gross leverage cap, and a per-market weight cap.
- **Locked-box protocol:** develop and choose everything on 2003 (or the earliest common date) to 2021. Seal 2022 to 2026. Run it **once**. Pass thresholds fixed beforehand (for example, realistic Sharpe floors by sub-period, harsh-cost Sharpe, max drawdown below the stated tolerance, and no single market contributing more than a stated share of profit).
- **Feasibility test:** replay the chosen strategy with real minimum lots at $500 and report how often trades are skipped and the effective risk per trade.
- **Data problem:** Dukascopy has some indices, metals and commodities, but start dates are probably 2010 to 2012 and later, and the exact instrument IDs and start dates have **not been verified** (the lookup was blocked by a rate limit). The MetaQuotes demo history length is also unknown. Alternatives: Yahoo/Stooq daily data or ETF proxies (via the user's laptop, since the cloud sandbox allowlist blocks most sites), accepting that those are not the tradable instrument.

---

## 10. Questions for you (second opinion)

1. Given two failed tests, is a third attempt (cross-asset trend) well-founded, or is the right advice to stop, or to run a very different strategy class? Which, and why?
2. Is the locked-box design adequate given that only about 12 to 15 years of non-FX data may exist, and that 2022 to 2026 (the sealed period) was itself a distinctive regime (rate hikes, strong trends in some assets)?
3. Is trading on a sub-$500 account with a 20% drawdown limit and minimum lots compatible with any diversified trend strategy? Is a cent account, a fund-style product, or simply not trading with real money the better answer?
4. Are there flaws in the cost model (spread plus 10% slippage per fill, 2%/yr financing stand-in) especially for index and metal CFDs? Real CFD swap on a retail broker is often larger than 2%.
5. Is the bridge architecture (EA + files + Python) reasonable, or is there a simpler robust way for a Linux-only user, accepting that Wine is required?
6. Are there tests I have missed for catching a hidden look-ahead or survivorship issue?

---

## 11. Environment and file inventory (for reproducibility)

- **User's laptop:** `~/Projects/Trade/mt5bot_v6/` contains `bridge_sync.py`, `signal_runner.py`, `check_*.py`, `research*.py`, `run_portfolio_test.py`, `run_backtest.py`, `download_universe.py`, `fetch_dukascopy.py`, `mt5bot/` (data.py, backtest.py, portfolio.py, strategies.py, live.py), `data/` (EURUSD_H1*.csv, universe_daily/*.csv, cache/), `logs/`, `HANDOFF.md`, `DEMO_AUTOMATION_PLAN.md`. Python venv created with `python3 -m venv --system-site-packages .venv` (numpy/pandas via dnf, because pip downloads time out).
- **Cloud sandbox** (where I work): `/root/mt5bot` (v3 code). It cannot reach most websites (allowlist), so downloads happen on the user's laptop.
- **MT5 bridge folder on the laptop:** `~/.mt5/drive_c/users/penality/AppData/Roaming/MetaQuotes/Terminal/Common/Files/bridge/`.
- **Coding conventions to keep:** pandas 3.x quirks (use `"24h"` not `"1D"` with `offset`; `Timestamp.value` resolution is not nanoseconds; do not use `dayfirst=True` on ISO dates).

## 12. Immediate next steps (in order)

1. User runs the v4 scanner and sends `folders_v4.csv` and `symbols_v4.csv`.
2. I pick a short symbol list; the user runs pass 2 to get history start dates for the candidate indices, metals and any oil/bond symbols.
3. Decide the data source for the cross-asset test (broker export vs Dukascopy vs outside daily data), write and freeze the pre-registration, extend the portfolio engine (volatility targeting, per-market caps, min-lot feasibility mode), and add self-tests before running anything on real data.
4. Run development on the pre-lockbox period; run the sealed period once; record the result whatever it is.
5. In parallel, leave the export-only EA running to collect real spread/swap data. Do not build order-placing code until a strategy passes.

*End of document.*
