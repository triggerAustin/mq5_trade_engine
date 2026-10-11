# MT5 Automated Trading Research — Project Handoff (v6)

*State as of 2026-10-10. Written so that a different AI model (or a human reviewer) can pick this up cold, check the work, and give an independent opinion.*

## Status at a glance (v6)

- **Aim:** find out honestly whether an automated MT5 strategy can make money, and risk no real money until one survives a fair, pre-registered test. The research infrastructure itself (verified backtester, resumable data pipeline, self-tests) is a second, independent deliverable.
- **What the evidence says so far:** no persistent edge found in single-pair EUR/USD rules (hourly, 4-hour, daily) nor in an 8-market daily Donchian trend-following portfolio (v5 result: FAIL on all three criteria).
- **New in v6:** an independent review found a **data-construction bug in every daily bar** (section 6.2). The engine review found no further fill-ordering bug. **The Stage 0 rerun on corrected bars gave the same FAIL (section 9.2)**, so the negative result is robust to that bug.
- **Stage 0 is done** (2026-10-10). **Next action:** decide whether to spend the Stage 1 test budget (sections 11-12), and settle the open questions in section 12 (capital, broker, drawdown tolerance) before anything is frozen.
- **v6.1:** a daily signal-sheet runner and a replay test that matches the backtest trade for trade (section 13), for demo-account plumbing tests only.
- **Rule that still holds:** no live money until a strategy has survived a fair test.

## Version history

| Version | Change |
|---|---|
| v1-v3 | engine, data downloader, first grids (buggy engine; results discarded) |
| v4 | stale re-entry bug fixed; self-tests `check_engine.py`, `check_portfolio.py`; pre-registered out-of-era and multi-market tests |
| v5 | multi-market data downloaded; pre-registered 8-market test run (FAIL, on defective daily bars) |
| **v6** | **daily bars rebuilt on the 17:00 New York roll (`mt5bot.data.to_daily`); `validate_daily()` guard in `run_portfolio_test.py`; `check_data.py` regression test; independent review added (section 10); staged roadmap (section 11); results re-labelled by validity (section 7)** |
| **v6.1** | **Phase A live pipeline: `mt5bot/live.py`, `signal_runner.py`, `check_live.py` (section 13); current month no longer cached; `download_universe.py --no-csv`** |

## 0. How to use this document

You are being asked to act as an **independent, skeptical reviewer**. Do not assume anything below is correct — an earlier version of the backtest engine had a real bug (section 6) that went unnoticed for several rounds of results. Please:

1. Read sections 1–5 for context, then sections 6–8 for the evidence (6.2 is new in v6). Section 10 holds the previous reviewer's findings; challenge them too.
2. Try to **find flaws** in the methodology, the engine (source code is in the appendix), the cost assumptions, and the pre-registered test (section 9).
3. Answer the specific questions in section 10.
4. Say plainly whether you think continuing is worthwhile, and what you would do instead or in addition.

Please give honest assessments even if they are discouraging. The project's explicit rule is: **no real money until a strategy has survived a fair test.**

## 1. Goal and the person's situation

- **Goal:** make money by running an automated (bot) trading strategy on MetaTrader 5 (MT5), instead of discretionary trading. The honest question behind it is whether any such strategy survives a fair test with free data; the project is also valuable as engineering work whatever the answer.
- The person has **no prior trading experience** and described themselves as needing help with "almost everything". They are a software developer (backend), comfortable with Python and a Linux terminal once told what to run.
- **Constraints they stated:** only has a Linux laptop (Fedora); cannot rent a Windows VPS right now; internet is slow and unreliable (large downloads time out). MT5 and its official Python package are Windows-only, so everything so far is research/backtesting in Python on Linux. Live execution (MQL5 Expert Advisor, or Python on a Windows VPS) is a later phase that only happens if a strategy survives.
- Starting capital was asked about but **not stated**; examples in this document use $1,000–$10,000 and $100,000 (the latter for the portfolio simulator, percentages are scale-free).
- Region: Kenya (relevant to broker regulation and typical retail spreads, not otherwise used).

## 2. Ground rules adopted

1. No live trading until a strategy passes a pre-specified out-of-sample test.
2. Costs (spread, slippage, commission) are always charged; the backtester must find **no profit on random data**.
3. Parameters are never chosen using the data they are evaluated on (train/test split by date, later a whole separate historical era).
4. Pass/fail criteria are written down **before** looking at results ("pre-registration"). Post-hoc observations are labelled as such and are not evidence.
5. When something looks surprisingly good or bad, assume a bug first.
6. **(v6)** Every data file is audited (`check_data.py`, `validate_daily()`) before any test; a test refuses to run on data that fails the audit.
7. **(v6)** Search budget: at most two further pre-registered tests after Stage 0. If both fail, stop searching for an edge in this data.


## 3. Data

- **Source:** Dukascopy historical candles (hourly, **bid** prices) via their public `jetta.dukascopy.com/v1/candles/hour/<PAIR>/BID/<year>/<month>` endpoint, downloaded with a custom resumable Python script (`fetch_dukascopy.py`). The existing npm tool `dukascopy-node` failed (the server answered HTTP 202 to its requests; browser-like headers fixed it, so the custom downloader sends those headers).
- The endpoint returns each month in a compact **delta-encoded** form: a starting open/high/low/close, a multiplier (1e-5), and per-candle integer deltas for times (in hours), opens, highs, lows, closes, plus volumes. The decoder rebuilds prices with integer arithmetic. Decoder semantics were verified on a real sample (candle internal consistency, close-to-next-open continuity < 1 pip, correct price levels).
- **EUR/USD hourly:** 2003-06-01 → 2017-12-29 (91,221 bars) and 2018-01-01 → 2026-09-30 (54,541 bars). Validation: 0 internally inconsistent candles (high < max(open, close) or low > min); the all-time extremes match reality to the day (high 1.6039 on 2008-07-15, low 1.0340 on 2017-01-03); the only gaps are weekends/holidays.
- **(v6) Daily bars** are built from hourly candles on the real FX roll, **17:00 New York to 17:00 New York** (DST-safe), labelled by the date they close, stubs of fewer than 4 candles dropped, with a `candles` column kept for auditing (`mt5bot.data.to_daily`). **v5 used a fixed 22:00 UTC cut, which was wrong in US summer (section 6.2). All v5 daily files must be rebuilt.**
- **Multi-market data (downloaded 2026-10-10 by the person, on their own machine):** GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD hourly bid candles, converted to daily bars (22:00 UTC cut). All end 2026-09-30; 0 internally inconsistent candles in every market. Start dates: EURUSD/GBPUSD/USDJPY/USDCHF 2003-05-31, XAUUSD 2003-06-01, AUDUSD/USDCAD/NZDUSD 2003-08-02 (no earlier data exists for these three).

## 4. Code inventory (all Python; numpy + pandas only)

| File | Purpose |
|---|---|
| `mt5bot/data.py` | CSV loader (Dukascopy/MT5/generic formats; ISO-date safe; refuses out-of-order or future dates), resampling, synthetic random-walk generator, **`to_daily()` and `validate_daily()` (v6)** |
| `mt5bot/backtest.py` | Single-market bar-by-bar engine with costs, ATR stops, fixed-fractional sizing, risk limits, metrics |
| `mt5bot/strategies.py` | Donchian breakout, z-score mean-reversion, session filter, trend filter |
| `mt5bot/portfolio.py` | Multi-market daily simulator with one shared USD equity pool |
| `fetch_dukascopy.py`, `download_universe.py` | Resumable downloaders |
| `run_backtest.py`, `research.py`, `research2.py`, `research3.py` | Experiment drivers (grids across strategies × timeframes × filters × costs × eras) |
| `mt5bot/live.py`, `signal_runner.py`, `check_live.py` | **(v6.1)** live-style decision logic, daily signal sheet, replay/no-peek self-test (section 13) |
| `check_engine.py`, `check_portfolio.py`, `check_data.py` | **Self-tests** (sections 6.1, 6.2) — must pass before any result is trusted |
| `run_portfolio_test.py` | The pre-registered multi-market test, pass rule hard-coded |

## 5. Engine specification (what the simulator assumes)

Single-market engine (`backtest.py`) and portfolio engine (`portfolio.py`) share these conventions; the portfolio engine is verified to reproduce the single engine **trade for trade**.

- Signals are computed from the **close of bar j−1** and executed at the **open of bar j** (no look-ahead).
- Prices are **bid**. Longs enter at ask = open + spread + slippage and exit at bid − slippage. Shorts enter at bid − slippage and exit at ask (+ spread + slippage). So the spread is paid once per round trip.
- **Stops** are checked intrabar against the bar's high/low. Fill at the stop price (minus/plus slippage), or at the **open** if the bar gapped through the stop. If a stop and a signal exit both occur on the same bar, **the stop wins**.
- **A stop that fires intrabar blocks re-entry on that same bar** (re-entering at the bar's stale open would be trading in the past — this was the bug, section 6). Entry then waits for the next bar's open.
- **Sizing:** risk a fixed fraction of equity (1% single-market, 0.5% portfolio) at the stop distance, lots rounded down to the lot step; skip the trade if below the minimum lot. (Portfolio engine uses fractional notional, no lot rounding.)
- Strategies: **Donchian breakout** (enter on a close beyond the prior N-bar high/low, exit on a close beyond the prior M-bar opposite extreme, ATR(14)×k stop; ATR is Wilder-style EWM) and **mean-reversion** (z-score of close vs n-bar mean; enter beyond ±k, exit on return to the mean, ATR stop). Optional UTC session filter (07–16) and 200-bar trend filter.
- Cost models: **"realistic"** = EUR/USD spread 1.0 pip, slippage 0.1 pip per fill (≈1.2 pips round trip, typical standard retail account); **"harsh"** = spread 1.2 pips, slippage 0.2 pip per fill, plus $7/lot commission (≈2.3 pips round trip) for hourly runs; for the portfolio test harsh = 2× spreads/slippage plus a 2%/yr financing drag on notional.
- Research runs switch off the daily-loss limit and the 25% drawdown kill switch to see raw signal quality; in live use they are safety features, not edges.

**Known limitations / not modelled:** swap/rollover (the data contain none; only a crude financing drag in the harsh portfolio case), fixed (not time-varying) spreads — real spreads widen at news/rollover and were much wider in 2003–2010, margin/leverage limits and stop-outs, broker differences, partial fills, weekend gap risk beyond what the bars contain, intrabar path ambiguity when both a stop and a target could be touched in one bar (only stops and next-open signal exits are used, so only the stop-vs-open-exit ordering matters), single data vendor.

## 6. Bugs found so far (please read)

### 6.1 Engine bug: stale re-entry after an intrabar stop (fixed in v4, still fixed)

1. The first real-data run (hourly EUR/USD, Donchian) lost money in every parameter set. I (the AI) reported it as "no edge" and also claimed an earlier random-data test "passed" because the strategy lost money there.
2. Suspicion arose when a **zero-cost** test on genuinely random data still showed a negative average R (−0.04R Donchian, −0.08 to −0.10R mean-reversion). On a random walk with zero costs no strategy can have an expected profit or loss.
3. An independent bare-bones simulator (walks every sub-bar price step, long-only mean-reversion) gave −0.6 ± 0.9 pips/trade versus the engine's −5.6 ± 0.8, and the engine opened ~10% more trades.
4. **Root cause:** after a stop-out in the middle of a bar, the engine re-entered the position at **that bar's open price** — a price the market had already left. Every such re-entry started underwater. This made all strategies look worse than they were, on every result produced up to that point.
5. **Fix:** block re-entry on the bar in which an intrabar stop fired.
6. **Self-tests added** (`check_engine.py`): (a) engine vs the independent reference simulator (3,961 vs 3,959 trades, −0.64 vs −0.62 pips/trade); (b) zero-cost random walks built from genuine fine-grained paths, 40 runs × 20,000 hours each, for breakout, mean-reversion and random-entry strategies: average R must be within 3 s.e. of zero or ±0.02R. After the fix: +0.017 ± 0.018, +0.019 ± 0.007, +0.016 ± 0.011 (a small positive drift remains, consistent with fills at the stop price on a discretised path). With the bug deliberately re-introduced the test fails (mean-reversion −0.090R, trade counts off 10%).
7. **Portfolio simulator self-tests** (`check_portfolio.py`): (A) identical trades to the single-market engine across 456 trades on 6 random runs; (B) zero-cost random walks, 30 portfolios × 8 markets × 6,000 days: Sharpe +0.002 ± 0.038, average R +0.002 ± 0.012; (C) real EUR/USD daily 2003–2026: 107 vs 107 trades with identical timing and prices. With the stale-re-entry bug re-introduced, test A fails (the bug is rarer on daily bars).

**Reviewer: please look for further bugs of this kind** (anything that makes fills inconsistent with the order in which prices actually occurred).

### 6.2 Data bug: spurious Sunday "stub" bars in daily data (found in v6 review, fixed in v6)

1. **Defect.** v5 built daily bars with `resample("24h", offset="22h")`, a fixed 22:00 UTC cut. The FX roll is 17:00 New York, which is 22:00 UTC only in winter (21:00 UTC in US summer). In summer the market reopens Sunday at 21:00 UTC, so that single hourly candle fell into its own bucket (Saturday 22:00 to Sunday 22:00) and became a one-candle "Sunday" daily bar.
2. **Evidence.** The v5 download summary shows 6,957 daily bars for EURUSD (similar for every FX pair) against about 6,090 weekdays in 2003-05 to 2026-09: roughly 870 spurious bars. A synthetic hourly timeline with the real DST-aware weekly session reproduces it (2004-2024: 5,479 weekdays; old method 6,182 bars with about 700 one-candle stubs; v6 method exactly 5,479). XAUUSD (6,056 bars, close to the weekday count) has a different session and is probably unaffected; its raw data was not re-inspected.
3. **Why it matters.** Stub bars have a near-zero true range, so ATR(14) is understated in summer weeks (tighter 3xATR stops, more stop-outs); every rolling window (55/20-day Donchian) covers fewer real days in summer; and signals can fire on a one-hour bar. The distortion works against trend-following, but its size is unknown. It was not caught by `check_portfolio.py` because the synthetic days there are continuous calendar days.
4. **Fix.** `to_daily()` converts timestamps to New York wall-clock time, adds 7 hours (17:00 becomes midnight), takes calendar days, drops bars with fewer than 4 candles, and records the candle count.
5. **Guards.** `validate_daily()` rejects weekend-labelled bars, stub bars, duplicate dates, and years outside 245-263 bars; `run_portfolio_test.py` refuses to run on files that fail it or lack the `candles` column. `check_data.py` contains a regression test that proves the old method produces stubs and the new one does not.
6. **Remaining known approximation.** 4-hour bars (`resample("4h")`) still use fixed UTC buckets, so a few Sunday buckets are partial. Hourly data is unaffected.

## 7. Results so far (all with the corrected engine unless stated)

**v6 status of each result.** The daily bars used in every D1 result below were built with the defective 22:00 UTC cut (section 6.2). Hourly results do not use daily bars and are unaffected. 4-hour bars are only mildly affected (a few partial Sunday buckets).

| Result | Data used | v6 status |
|---|---|---|
| 7.1 early hourly grid | hourly, buggy engine | discard (engine bug 6.1) |
| 7.2 grid 2018-2026, H1 and H4 families | hourly / 4h | valid |
| 7.2 grid 2018-2026, D1 families | defective daily bars | **affected by 6.2 - not recomputed (low priority; same rule family as the failed 9.2 test)** |
| 7.3 hourly / 4-hour families 2003-2017 | hourly / 4h | valid |
| 7.3 daily mean-reversion FAIL, daily breakout | defective daily bars | **affected by 6.2 - not recomputed (low priority; same rule family as the failed 9.2 test)** |
| 7.4 daily breakout regime analysis | defective daily bars | **affected by 6.2 - not recomputed (low priority; same rule family as the failed 9.2 test)** |
| 9.1 pre-registered 8-market test | defective daily bars | **rerun done on corrected bars (9.2): same FAIL** |


### 7.1 Invalid early result
Hourly EUR/USD 2018–2026 Donchian grid under the buggy engine and harsh costs: best train −0.08%, out-of-sample −24%. **Discard.**

### 7.2 Corrected grid, 2018–2026 (train to 2023-03-31, test after), $10k account, never selecting on the test half
292 configurations: breakout (entry 20/40/55/80, exit 10/20, ATR stop 2/3) and mean-reversion (n 20/50/100, k 1.5–3, stop 2/3/4) × H1/H4/D1 × {none, session, trend} filters.
- Realistic costs: 23% of configs profitable on train, 16% on test; median profit factor 0.86 on both. Zero costs: 32% / 28%, median PF 0.92 / 0.91 — i.e. **no raw edge even before costs**.
- Zero configs with PF > 1.1 and t > 1 on both halves.
- Daily mean-reversion looked best (58% of 36 configs profitable on train, 67% on test, median test PF 1.49) but with ~20–30 trades per half (strongest configs had 4–8 trades); the sensible-sized ones had t-statistics 0.5–0.8.

### 7.3 Pre-registered out-of-era test of daily mean-reversion on **2003–2017** (data nothing was tuned on) [daily parts AFFECTED by 6.2]
Rule fixed in advance: pass if > 50% of the 36 configs profitable and median PF > 1.1.
- Realistic: **6/36 profitable, median PF 0.69, median return −7.5%** (median 74 trades). Harsh: identical. **FAIL.** Daily mean-reversion dropped.
- Rest of the grid in that era (no re-tuning, realistic costs): hourly families sit at or below break-even (median PF 0.86–1.00; median returns from −5% to −56% over the era); 4-hour families roughly break-even (median PF 0.86–1.10; the best was breakout with the session filter, 71% of configs profitable, median PF 1.10); **daily breakout profitable in 2003–2017** (93% of 14 configs, median PF 1.36, median +12%; with a 200-day trend filter 100% profitable, PF 1.78, +20.8%).
- Zero configs with PF > 1.1, ≥ 40 trades **and** t > 2.

### 7.4 Why the daily-breakout result is not an edge (post-hoc analysis) [AFFECTED by 6.2 - not recomputed]
Donchian 55/20/ATR×3 on daily bars, 2003-06 → 2026-09, realistic costs: **−1.2% total over 23 years, 107 trades, PF 0.98, max drawdown −16.9%.**
- 2003–2017: 60 trades, avg R **+0.27**; 2018–2026: 47 trades, avg R **−0.29** (win rate 40% → 28%).
- By year: most of the old-era profit is **2014 (+9.3%) and 2015 (+4.6%)** (USD surge); remaining 13 old-era years net ≈ −1%.
- Harsh costs barely change it (−1.7%), so it is regime dependence / concentration in one episode, not costs.

### 7.5 Cost observations
At hourly frequency trading costs are material but are not the main problem (zero-cost runs also lose). At daily frequency costs hardly matter.

## 8. Conclusion (v6)

Simple single-pair, price-only rules on EUR/USD show **no demonstrated, persistent edge** at hourly and 4-hour frequency across 2003-2026 (these results are valid). At daily frequency the apparent edge (daily trend-following 2003-2017) was concentrated in one episode and reversed in 2018-2026, and the 8-market daily trend-following portfolio failed its pre-registered test in v5; **the 8-market portfolio conclusion has been confirmed on corrected bars (section 9.2: FAIL, Sharpe -0.06, halves +0.24 / -0.38). The daily single-pair results (7.2-7.4) were not recomputed but concern the same failed rule family.**

## 9. Current plan: pre-registered multi-market daily trend-following test

Rationale: documented trend-following returns (CTA-style) come from **diversification across many markets at low frequency**, not from one pair. This is the single remaining idea I consider worth one fair test. Everything below is **fixed before any multi-market data is looked at** and is hard-coded in `run_portfolio_test.py`.

- **Markets (8):** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD. Daily bars (22:00 UTC cut), 2003-06 → 2026-09. *(Caveat: seven of eight are USD pairs → strongly correlated through the dollar; diversification is limited. EUR/USD was already examined in 7.4, so the test is not fully independent of that.)*
- **Signal:** Donchian breakout, enter on a close beyond the prior 55-day high/low (long and short), exit on a close beyond the prior 20-day opposite extreme, ATR(14) × 3.0 stop, next-open execution, one position per market.
- **Sizing:** 0.5% of portfolio equity risked per position (distance to stop), shared equity pool, USD account, exact P&L formulas for USD-quote and USD-base pairs.
- **Costs:** per-market spread/slippage table in `run_portfolio_test.py` (EURUSD 1.0 pip, GBPUSD 1.3, USDJPY 1.0, AUDUSD 1.2, USDCAD/USDCHF/NZDUSD 1.5, XAUUSD $0.30; slippage ≈10% of spread per fill). Harsh = 2× plus 2%/yr financing drag.
- **PASS only if all three hold:** (1) realistic-cost full-period annualised Sharpe ≥ 0.50; (2) realistic Sharpe ≥ 0.20 in **each** half (2003–2014 and 2015–2026); (3) harsh-cost full-period Sharpe ≥ 0.30.
- A small table of alternative lookbacks (20/10 … 100/50) is printed **for information only**; it must not be used to switch the primary spec after the fact.
- **Status: v5 run on 2026-10-10 gave FAIL on all three criteria (section 9.1), but on defective daily bars (section 6.2). The specification is unchanged in v6 and was rerun once on corrected bars and gave the same FAIL (section 9.2).**

### 9.1 v5 result (run by the person on their machine, 2026-10-10; output pasted verbatim) - COMPUTED ON DEFECTIVE DAILY BARS, see 6.2

```
markets: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD
period : 2003-05-31 -> 2026-09-30

realistic costs, 2003-2026         Sharpe -0.05 | CAGR -0.7% | maxDD -33.8% | trades 821 | PF 0.93 | avg R -0.03
harsh costs + financing, 2003-2026 Sharpe -0.30 | CAGR -2.7% | maxDD -51.4% | trades 821 | PF 0.94 | avg R -0.03
realistic Sharpe by half: 2003-2014 +0.21 | 2015-2026 -0.35

return by year (%): {2003: 5.3, 2004: 2.4, 2005: -8.8, 2006: -0.1, 2007: 0.4, 2008: 9.7, 2009: -0.4, 2010: -1.1, 2011: -4.3, 2012: -1.1, 2013: 1.7, 2014: 15.1, 2015: -0.8, 2016: -3.6, 2017: -5.7, 2018: 2.9, 2019: -7.0, 2020: 2.4, 2021: -6.8, 2022: 1.2, 2023: -2.7, 2024: -2.3, 2025: -2.0, 2026: -8.0}

per-market contribution (realistic):
        trades  pnl_usd  avg_R  win_pct
AUDUSD     106 -1714.91  -0.03    32.08
EURUSD     107   681.54   0.03    34.58
GBPUSD     114 -9982.80  -0.16    28.07
NZDUSD     106 -3510.85  -0.06    35.85
USDCAD      95   538.26   0.02    30.53
USDCHF     101 -7922.29  -0.14    32.67
USDJPY     101 -2128.70  -0.03    32.67
XAUUSD      91  8491.91   0.21    31.87

1. realistic full-period Sharpe >= 0.50 : -0.05  NO
2. Sharpe >= 0.20 in each half          : +0.21 / -0.35  NO
3. harsh-cost Sharpe >= 0.30            : -0.30  NO
RESULT: FAIL

post-hoc (NOT used for the verdict) — Sharpe full / 2003-2014 / 2015-2026:
  Donchian 20/10: -0.16 / +0.11 / -0.46   maxDD -42%
  Donchian 40/20: -0.03 / +0.25 / -0.36   maxDD -37%
  Donchian 55/20: -0.05 / +0.21 / -0.35   maxDD -34%
  Donchian 80/40: +0.06 / +0.38 / -0.29   maxDD -34%
  Donchian 100/50: +0.11 / +0.40 / -0.21  maxDD -30%
```

**Reading of the result.**
- Clear FAIL: even the realistic-cost full-period Sharpe is slightly negative; total P&L is negative; the only half that clears the 0.20 bar is 2003–2014, and 2015–2026 is clearly negative (−0.35).
- Returns are concentrated: 2014 (+15.1%) and 2008 (+9.7%) account for most of the profit; in 2015–2026 only 2018, 2020 and 2022 were positive.
- Only gold made money (+$8.5k, avg R +0.21; its long-run uptrend over the period probably helped a long-biased trend rule); GBPUSD (−$10.0k) and USDCHF (−$7.9k) lost most. Seven USD pairs are highly correlated, so diversification was weaker than the 8-market count suggests.
- The post-hoc table shows the same shape for every lookback: modest positive Sharpe in 2003–2014, negative in 2015–2026 (longer lookbacks less negative). Under the pre-registration this is **not** grounds to switch to a longer lookback, but it is consistent with trend-following having worked in the early era and not since (a widely discussed pattern; this document does not independently verify the literature).
- Under the v5 data this was a clear FAIL. Because the bars were defective, the verdict is **provisional until section 9.2 is run**. Either way: no tuning of this family on this data.

### 9.2 v6 rerun on corrected bars (same specification, same pass rule, run once) - DONE 2026-10-10: FAIL, same verdict as v5

- Data audit: `check_data.py` passed for all 8 markets (no stub bars; min 5 candles per bar for FX, 11 for gold). Daily bars per pair fell from about 6,900-6,950 to about 6,030-6,080 (EURUSD 6,077), in line with the weekday count. Run by the person on their machine; output pasted verbatim below.

```
markets: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD
period : 2003-06-02 -> 2026-09-30

realistic costs, 2003-2026         Sharpe -0.06 | CAGR -0.7% | maxDD -32.3% | trades 741 | PF 0.93 | avg R -0.03
harsh costs + financing, 2003-2026 Sharpe -0.33 | CAGR -2.5% | maxDD -49.1% | trades 743 | PF 0.93 | avg R -0.04
realistic Sharpe by half: 2003-2014 +0.24 | 2015-2026 -0.38

return by year (%): {2003: 4.5, 2004: 1.6, 2005: -6.9, 2006: 0.5, 2007: -0.6, 2008: 12.9, 2009: -0.5, 2010: -1.0, 2011: -4.8, 2012: -1.2, 2013: 1.9, 2014: 12.9, 2015: -0.6, 2016: -1.9, 2017: -6.9, 2018: 3.8, 2019: -6.5, 2020: 2.6, 2021: -8.2, 2022: 2.1, 2023: -4.7, 2024: -4.9, 2025: 1.4, 2026: -7.6}

per-market contribution (realistic):
        trades   pnl_usd  avg_R  win_pct
AUDUSD      94   -193.23  -0.00    35.11
EURUSD      94    586.79   0.02    31.91
GBPUSD      98  -5909.17  -0.11    27.55
NZDUSD      91  -2721.12  -0.06    35.16
USDCAD      88  -3128.11  -0.07    32.95
USDCHF      95 -10590.10  -0.20    32.63
USDJPY      89   -174.63   0.00    37.08
XAUUSD      92   7589.34   0.19    31.52

1. realistic full-period Sharpe >= 0.50 : -0.06  NO
2. Sharpe >= 0.20 in each half          : +0.24 / -0.38  NO
3. harsh-cost Sharpe >= 0.30            : -0.33  NO
RESULT: FAIL

post-hoc (NOT used for the verdict) - Sharpe full / 2003-2014 / 2015-2026:
  Donchian 20/10: -0.10 / +0.18 / -0.40   maxDD -35%
  Donchian 40/20: +0.01 / +0.28 / -0.28   maxDD -28%
  Donchian 55/20: -0.06 / +0.24 / -0.38   maxDD -32%
  Donchian 80/40: +0.06 / +0.43 / -0.33   maxDD -35%
  Donchian 100/50: +0.08 / +0.37 / -0.23   maxDD -29%
```

**Comparison with v5 (defective bars):** full-period Sharpe -0.06 vs -0.05; halves +0.24 / -0.38 vs +0.21 / -0.35; harsh -0.33 vs -0.30; avg R -0.03 in both; trades 741 vs 821 (fewer whipsaws, as predicted); gold again the only clear winner (+$7.6k, avg R +0.19), USDCHF and GBPUSD the biggest losers; profit again concentrated in 2008 and 2014; the post-hoc lookback table has the same shape (positive 2003-2014, negative 2015-2026).

**Reading.** The bar defect was real but did not drive the result. The pre-registered FAIL is now robust to an independent data bug. The daily trend-following idea on this universe is rejected: no tuning of this family on this data. Gold, the market that was never affected by the stub bars, behaves the same in both runs, which is consistent with its profit coming from its long-run uptrend rather than from an edge in the rule.

**Not rerun:** the daily single-pair results (7.2 D1 families, 7.3 daily, 7.4) were not recomputed on corrected bars. They are low priority: they examined the same rule family that has now failed on 8 markets.

## 10. Independent review (v6) - answers to the reviewer questions

*This section was added by an independent reviewer (Claude) working from the full source. Section 11 turns it into a plan.*

1. **Engine realism.** No remaining look-ahead or fill-ordering bug of the stale-re-entry kind. Signals use bar j-1 and fill at bar j's open; rolling extremes are shifted by one bar; longs enter at the ask and stop on the bid, shorts stop on the ask; stop-wins-over-signal and gap-fills-at-open are the conservative choices; the entry-bar check looks only at the adverse side; re-entry after a gap stop at that open is correct because it is a real price; a flip (long entry implies short-exit) closes and opens on the same bar correctly. USD-base P&L `N(exit-entry)/exit` is right; the sizing `N = risk*equity*o/dist` is off by a negligible amount for USD-base pairs. The one real defect found was in the DATA (section 6.2), not the engine.
2. **Pass rule and sizing.** Reasonable but noisy. The standard error of an annualised Sharpe is about 1/sqrt(years): about 0.21 over 23 years and 0.29 per 11.5-year half. The rule is strong evidence against a true Sharpe near 0.5 and says little about 0.2-0.3, a level not worth trading after real costs and drawdowns anyway; the per-half >= 0.2 rule would reject some genuinely positive strategies. Sharpe is independent of the 0.5% risk level. Equal risk-per-stop is close to volatility targeting here because the stop is ATR-based; for a wider universe use explicit per-market volatility targeting.
3. **Costs.** At daily frequency cost per trade is about 0.006R (1.2 pips against a ~200-pip stop), so wider 2003-2010 spreads would not change a verdict. The real realism gap is **carry**: the data are spot only, whereas published FX trend results use forwards/futures that include it. A flat 2%/yr drag is a poor stand-in because swap depends on side and rate gap (long USD/JPY earned swap for years, short paid it) and brokers add a markup. Build directional swap from free policy-rate series (Stage 1).
4. **Statistics.** A negative result needs no significance machinery. If something ever passes: block bootstrap on daily returns, deflated Sharpe counting every configuration examined (~300 on EUR/USD plus the portfolio variants), and a reality check. Note the 55/20/x3 spec was chosen after seeing EUR/USD daily results, so selection bias favoured passing.
5. **Alternatives (free data only).** No candidate I would expect to survive retail costs. Untested: breadth (indices, commodities; Dukascopy has CFD data), directional carry, volatility targeting. Cross-sectional FX momentum, seasonality and volatility-regime filters are weak and heavily data-mined; each new variant raises the false-positive risk.
6. **Practicality if something passes.** A demo forward test validates execution only (fills, spreads, swaps, code), not an edge. Go live small with hard per-position and total-exposure caps and the drawdown kill switch. Daily strategies do not need a 24/7 Windows VPS (see section 11). Verify any Kenyan broker's licensing directly with the regulator before depositing.
7. **Meta.** If the aim is income, further search over free retail FX data has low expected value and each added variant raises the false-positive risk; stop at the Stage 1 budget. If the aim includes learning and building a credible engineering project, the work is already strong and worth finishing properly.

## 11. Roadmap (v6): best direction for the bot

**Direction:** a daily-timeframe, multi-market, trend-style system with strict risk limits, because it is the only idea tested that has a documented basis and low cost sensitivity. Intraday bots, ML price prediction and grid/martingale EAs are out.

### Stage 0 - fix and rerun (do first, nothing else before it)
1. Rebuild daily files: `python download_universe.py` (cached months are reused; no download). The EURUSD daily file is rebuilt from the two hourly CSVs if present.
2. `python check_data.py` must end `DATA CHECKS PASSED`; `python check_engine.py` and `python check_portfolio.py` must end `ALL CHECKS PASSED`.
3. `python run_portfolio_test.py` once. Paste output into 9.2. Rerun the daily parts of `research.py`/`research3.py` if the daily single-pair results (7.2-7.4) matter to you.
4. Decision: FAIL -> negative conclusion is robust, go to Stage 1 (budget of two tests, section 2 rule 7). PASS -> do not trade; go to Stage 1 and the Stage 2 significance work.
5. **Outcome (2026-10-10): steps 1-3 done, result FAIL (section 9.2). Stage 1 is now the decision point.**

### Stage 1 - one broader pre-registered test (see section 12 draft)
Add what the current test lacks: more independent markets, directional swap costs, per-market volatility targeting, a written pass rule fixed before looking. If it fails, stop searching for an edge.

### Stage 2 - only if something passes
1. Block bootstrap and deflated Sharpe (counting every configuration examined).
2. Demo trading for about 3 months to test execution (fills, spreads, swaps, code), not the edge.
3. Live with a very small account: caps on risk per position and total exposure, correlation cap across USD pairs, drawdown kill switch.

### Architecture to build regardless of the research outcome
- **Strategy and execution separated.** The strategy outputs target positions per market after the daily close; a thin execution layer turns them into orders, checks risk limits and logs everything.
- **Same signal code for backtest and live**, with data audits that fail loudly.
- **No 24/7 Windows VPS needed for daily signals.** Cron on the Fedora laptop computes signals; orders can go via MT5 (under Wine, test on demo first), a broker API, or manually on MT5 mobile at first.
- **Capital reality.** Diversified trend-following has historically been a modest-Sharpe strategy with drawdowns of 20-30% (reviewer's understanding, not verified here). On a small account, minimum lot sizes distort risk and dollar returns are small. Starting capital has not been stated; it decides whether the position sizes are even feasible.

## 12. Stage 1 pre-registration - DRAFT (not frozen; nothing here has been run or looked at on data)

To be completed and frozen **before** any new data is examined. Open items need the person's decision.

- **Universe:** the 8 current markets plus liquid indices and commodities offered as CFDs by the chosen broker and available on Dukascopy (instrument codes and history length to be confirmed; markets with under ~10 years of data excluded). Decide the count and list now.
- **Signal:** keep one fixed trend rule (the Stage 0 primary 55/20 Donchian, or a single pre-chosen alternative). Do not choose the lookback from results.
- **Sizing:** per-market volatility targeting (equal risk contribution at a fixed annualised volatility per market), shared equity pool, portfolio gross-exposure cap.
- **Costs:** per-market spread and slippage table as in `run_portfolio_test.py`; **directional swap** from free policy-rate series (side and rate gap, with a stated broker markup); harsh case = 2x spread/slippage plus doubled markup.
- **Pass rule (proposal, to confirm):** realistic Sharpe >= 0.40 full period; >= 0.15 in each half; harsh-cost Sharpe >= 0.25; no single market supplying more than half of total profit; at least N independent markets contributing (N to be set).
- **Budget:** this is the first of at most two further tests after Stage 0.
- **Open questions for the person:** starting capital; broker (and whether it offers the CFDs above); acceptable maximum drawdown.

## 13. Live pipeline - Phase A (v6.1): signal runner, no broker connection

**Purpose.** Test the execution plumbing on a demo account. The strategy inside is the pre-registered Donchian spec whose backtest FAILED (section 9.2); nothing in this pipeline is evidence of an edge, and no real money is involved. A daily demo run produces about 1 trade a month across 8 markets, so it cannot validate profitability.

**What exists**
- `mt5bot/live.py`: `decide()` turns CLOSED bars plus the current position into "close / open long / open short, with stop distance" for the next open, using the same `donchian_breakout` as the backtests; `closed_bars()` drops the still-forming bar; `lots_for()` sizes from risk, stop distance, contract size and the broker's minimum lot (it skips a trade rather than over-risk).
- `signal_runner.py`: `refresh` (download latest months, rebuild and audit daily files), `signals --equity N` (the daily sheet), `record` (store your actual fills and stops), `show`. Positions live in `state/positions.json`; every sheet is appended to `logs/signals.csv`.
- `check_live.py`: (A) no-peek test: signals from the last 800 closed bars equal the full-history backtest signals at random cut days; (B) replay: stepping through history one closed bar at a time with `decide()` reproduces the portfolio engine's trades exactly (entry/exit dates, side, reason, exit price). Mutation-tested: an injected look-ahead and a too-short indicator window were both caught. Passed on synthetic data in the build environment (52 vs 52 and 58 vs 58 trades); **the real-data replay has not yet been run on the person's machine** (`python check_live.py --all`).
- `download_universe.py`: the current month is no longer cached (it is still growing); `--no-csv` builds EURUSD from the monthly JSON too, which `refresh` needs.

**Daily routine (demo).** After the 17:00 New York close: `python signal_runner.py refresh`, then `python signal_runner.py signals --equity <demo balance>`. At the new day's open act on the sheet; every entry gets a real broker stop-loss at fill -/+ the sheet's stop distance; then `record` what actually happened.

**Known differences between the replay and real trading (to watch on demo)**
1. The backtest lets a stop beat a same-bar signal exit (conservative); live, the signal exit at the open fills first.
2. If a position is stopped by a gap at the open, the engine re-enters at that open when an entry signal was already standing; the daily sheet cannot know this in advance (rare).
3. Signals are computed on Dukascopy BID data; the broker's prices differ slightly, so a borderline breakout can differ. Record both and compare.
4. The runner infers a stop-out from bar highs/lows as a prompt only; the broker's record is the truth.
5. Swap/financing on held positions is not modelled; compare the demo account's swap with the backtest assumption.
6. Minimum lot may force skipped trades on a small account; the sheet says SKIP and shows the risk the minimum lot would carry.

**Not built yet:** Phase B (manual demo comparison, 4-8 weeks), Phase C (automated order placement via an MQL5 EA, a Wine-based MT5 Python bridge or a broker REST API; depends on the platform the person uses), Phase D (live money, only after a pre-registered test passes).

## Appendix A — how to run

```bash
python -m venv .venv && source .venv/bin/activate && pip install numpy pandas
python check_engine.py                 # must end with ALL CHECKS PASSED
python check_portfolio.py              # must end with ALL CHECKS PASSED
python check_data.py                   # must end with DATA CHECKS PASSED (also audits data/universe_daily/*.csv)
python fetch_dukascopy.py --start 2003-06 --end 2017-12 --out data/EURUSD_H1_old.csv   # resumable
python fetch_dukascopy.py --end 2026-09 --out data/EURUSD_H1.csv
python download_universe.py            # rebuilds all 8 daily files on the NY-17:00 roll from cached months
python check_data.py                   # audit the rebuilt files
python run_portfolio_test.py           # the pre-registered test and verdict (refuses to run on bad data)
python check_live.py --all             # must end ALL LIVE CHECKS PASSED (replays history through the live logic)

# daily demo routine (section 13)
python signal_runner.py refresh
python signal_runner.py signals --equity 10000
python signal_runner.py record --market EURUSD --side long --entry 1.0850 --stop 1.0700 --lots 0.10
python signal_runner.py record --market EURUSD --flat
python signal_runner.py show
```

## Appendix B — source code (verbatim, v6.1)

### `mt5bot/backtest.py`

```python
"""Cost-aware bar-by-bar backtester.

Conventions (kept deliberately conservative):
  * Signals are computed on the CLOSE of bar i and executed at the OPEN of bar i+1
    (no look-ahead).
  * Prices in the data are BID prices. Buying costs the spread on entry; shorts pay
    the spread when they are closed (buy back at ask).
  * Stop losses are checked intrabar. If the stop is hit, we fill at the stop price,
    or at the open if the bar gapped through it (worse for us). Slippage is added.
  * If a stop and a signal exit both occur on the same bar, the stop wins.
  * Position size = risk_pct of current equity / stop distance, rounded DOWN to
    lot_step. If that is below min_lot the trade is skipped (we never risk more
    than intended just to get a trade on).
  * Account currency is assumed to be the quote currency (USD for EURUSD,
    GBPUSD, XAUUSD, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Instrument:
    name: str = "EURUSD"
    contract_size: float = 100_000      # units per 1.0 lot (XAUUSD = 100 oz)
    spread: float = 0.00012             # in price units (1.2 pips for EURUSD)
    slippage: float = 0.00002           # per fill, price units, applied against us
    commission_per_lot: float = 7.0     # USD per lot, ROUND TURN (0 if built into spread)
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 50.0


@dataclass
class Config:
    initial_equity: float = 1000.0
    risk_pct: float = 0.01              # fraction of equity risked per trade
    max_leverage: float = 30.0          # cap notional / equity
    daily_loss_limit: float | None = 0.03   # stop opening trades for the day after -3%
    max_drawdown_kill: float | None = 0.25  # stop trading entirely after -25% from peak


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.Series
    config: Config
    instrument: Instrument
    stats: dict = field(default_factory=dict)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def run_backtest(df: pd.DataFrame, signals: dict, inst: Instrument, cfg: Config) -> Result:
    """Run the backtest.

    signals: dict of equal-length arrays aligned to df
        'long_entry', 'short_entry', 'long_exit', 'short_exit': bool
        'stop_dist': float, stop distance in price units at signal time (NaN = no trade)
    """
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); c = df["close"].to_numpy()
    idx = df.index
    n = len(df)

    le = np.asarray(signals["long_entry"], bool); se = np.asarray(signals["short_entry"], bool)
    lx = np.asarray(signals["long_exit"], bool); sx = np.asarray(signals["short_exit"], bool)
    sd = np.asarray(signals["stop_dist"], float)

    equity = cfg.initial_equity
    peak = equity
    killed = False
    day_start_equity = equity
    cur_day = idx[0].date()

    pos = 0            # +1 long, -1 short, 0 flat
    lots = 0.0
    entry_px = 0.0     # effective entry price incl. spread/slippage
    stop_px = 0.0
    entry_i = 0
    risk_cash = 0.0
    trades = []
    eq_curve = np.full(n, np.nan)

    def close_trade(i, exit_px, reason):
        nonlocal equity, pos, lots
        pnl_px = (exit_px - entry_px) if pos == 1 else (entry_px - exit_px)
        gross = pnl_px * lots * inst.contract_size
        comm = inst.commission_per_lot * lots
        net = gross - comm
        equity += net
        trades.append({
            "entry_time": idx[entry_i], "exit_time": idx[i], "side": "long" if pos == 1 else "short",
            "lots": lots, "entry": entry_px, "exit": exit_px, "stop": stop_px,
            "pnl": net, "r": net / risk_cash if risk_cash else np.nan, "reason": reason,
            "bars": i - entry_i,
        })
        pos = 0; lots = 0.0

    for i in range(1, n):
        d = idx[i].date()
        if d != cur_day:
            cur_day = d
            day_start_equity = equity

        # ---- 1. manage open position on this bar --------------------------------
        n_before = len(trades)
        if pos != 0:
            if pos == 1:
                # long exits at bid
                if o[i] <= stop_px:
                    close_trade(i, o[i] - inst.slippage, "stop_gap")
                elif l[i] <= stop_px:
                    close_trade(i, stop_px - inst.slippage, "stop")
                elif lx[i - 1]:
                    close_trade(i, o[i] - inst.slippage, "signal")
            else:
                # short exits at ask = bid + spread
                if o[i] + inst.spread >= stop_px:
                    close_trade(i, o[i] + inst.spread + inst.slippage, "stop_gap")
                elif h[i] + inst.spread >= stop_px:
                    close_trade(i, stop_px + inst.slippage, "stop")
                elif sx[i - 1]:
                    close_trade(i, o[i] + inst.spread + inst.slippage, "signal")

        # A stop that fires MID-bar means the market has already moved away from this bar's open,
        # so we must not re-enter at that stale open price (that would be trading in the past).
        # We wait and use the next bar's open instead.
        stopped_bar = len(trades) > n_before and trades[-1]["reason"] == "stop"

        # ---- 2. risk switches ---------------------------------------------------
        peak = max(peak, equity)
        if cfg.max_drawdown_kill is not None and equity < peak * (1 - cfg.max_drawdown_kill):
            killed = True
        day_blocked = cfg.daily_loss_limit is not None and equity < day_start_equity * (1 - cfg.daily_loss_limit)

        # ---- 3. open new position from previous bar's signal --------------------
        if pos == 0 and not killed and not day_blocked and not stopped_bar and np.isfinite(sd[i - 1]) and sd[i - 1] > 0:
            side = 1 if le[i - 1] else (-1 if se[i - 1] else 0)
            if side != 0:
                dist = sd[i - 1] + inst.spread + inst.slippage  # real stop distance incl. costs
                risk_amt = cfg.risk_pct * equity
                raw = risk_amt / (dist * inst.contract_size)
                raw = min(raw, cfg.max_leverage * equity / (o[i] * inst.contract_size), inst.max_lot)
                q = np.floor(raw / inst.lot_step + 1e-9) * inst.lot_step
                if q >= inst.min_lot:
                    pos = side; lots = round(q, 8); entry_i = i; risk_cash = lots * dist * inst.contract_size
                    if side == 1:
                        entry_px = o[i] + inst.spread + inst.slippage    # buy at ask
                        stop_px = o[i] - sd[i - 1]                        # triggers on bid <= stop
                    else:
                        entry_px = o[i] - inst.slippage                   # sell at bid
                        stop_px = o[i] + sd[i - 1]                        # compared against ask below

        # ---- 4. same-bar stop check for a just-opened position ------------------
        if pos != 0 and entry_i == i:
            if pos == 1 and l[i] <= stop_px:
                close_trade(i, stop_px - inst.slippage, "stop")
            elif pos == -1 and h[i] + inst.spread >= stop_px:
                close_trade(i, stop_px + inst.slippage, "stop")

        # ---- 5. mark to market --------------------------------------------------
        if pos == 0:
            eq_curve[i] = equity
        elif pos == 1:
            eq_curve[i] = equity + (c[i] - entry_px) * lots * inst.contract_size
        else:
            eq_curve[i] = equity + (entry_px - (c[i] + inst.spread)) * lots * inst.contract_size

    if pos != 0:  # close at the last close
        px = c[-1] - inst.slippage if pos == 1 else c[-1] + inst.spread + inst.slippage
        close_trade(n - 1, px, "end")
        eq_curve[-1] = equity

    eq = pd.Series(eq_curve, index=idx).ffill().fillna(cfg.initial_equity)
    tdf = pd.DataFrame(trades)
    res = Result(tdf, eq, cfg, inst)
    res.stats = metrics(res)
    return res


def metrics(res: Result) -> dict:
    eq, t = res.equity, res.trades
    days = max((eq.index[-1] - eq.index[0]).days, 1)
    years = days / 365.25
    start, end = res.config.initial_equity, float(eq.iloc[-1])
    dd = (eq / eq.cummax() - 1).min()
    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if len(daily) > 2 and daily.std() > 0 else np.nan
    out = {
        "start_equity": start, "end_equity": end,
        "return_pct": (end / start - 1) * 100,
        "cagr_pct": ((end / start) ** (1 / years) - 1) * 100 if end > 0 else -100.0,
        "max_drawdown_pct": dd * 100,
        "sharpe": sharpe,
        "years": years,
        "trades": int(len(t)),
    }
    if len(t):
        wins, losses = t.loc[t.pnl > 0, "pnl"], t.loc[t.pnl <= 0, "pnl"]
        out.update({
            "win_rate_pct": len(wins) / len(t) * 100,
            "profit_factor": wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf,
            "avg_R": t["r"].mean(),
            "avg_win": wins.mean() if len(wins) else 0.0,
            "avg_loss": losses.mean() if len(losses) else 0.0,
            "avg_bars_held": t["bars"].mean(),
        })
    return out


def format_stats(s: dict) -> str:
    lines = []
    for k, v in s.items():
        lines.append(f"  {k:<18} {v:>12.2f}" if isinstance(v, (float, np.floating)) else f"  {k:<18} {v:>12}")
    return "\n".join(lines)
```

### `mt5bot/portfolio.py`

```python
"""Multi-market daily portfolio backtester with ONE shared USD equity pool.

Same execution conventions as backtest.py (kept identical on purpose, and verified against it
in check_portfolio.py):
  * signals are computed on the CLOSE of bar j-1 and executed at the OPEN of bar j
  * data are BID prices; longs buy at ask (open + spread + slippage) and sell at bid;
    shorts sell at bid and buy back at ask
  * stops are checked intrabar against high/low; fills at the stop price (or at the open if it
    gapped through) plus slippage against us
  * if a stop fires inside a bar we do NOT re-enter at that bar's (stale) open  <- the bug fixed earlier
  * one position per market, risk_pct of CURRENT portfolio equity risked per position

Differences from the single-market engine (needed for a multi-currency portfolio):
  * account currency is USD for every market. P&L formulas:
        USD-quote pairs (EURUSD, GBPUSD, AUDUSD, NZDUSD, XAUUSD):  side * N * (exit/entry - 1)
        USD-base  pairs (USDJPY, USDCAD, USDCHF):                  side * N * (exit - entry) / exit
    where N is the position's notional in USD at entry.
  * sizing uses equity marked to market (cash + unrealised P&L), not just realised equity
  * optional financing drag (annual % of notional, accrued per calendar day while a position is held)
    as a crude stand-in for swap/rollover, which the data do not contain.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Market:
    name: str
    df: pd.DataFrame            # daily OHLC (bid), DatetimeIndex
    sig: dict                   # arrays aligned to df: long_entry, short_entry, long_exit, short_exit, stop_dist
    spread: float               # price units, paid once per round trip
    slippage: float             # price units, per fill, against us
    usd_base: bool = False      # True for USDJPY / USDCAD / USDCHF


@dataclass
class PConfig:
    initial_equity: float = 100_000.0
    risk_pct: float = 0.005           # fraction of equity risked per position
    max_gross_leverage: float = 10.0  # cap on total notional / equity (rarely binds)
    financing_rate: float = 0.0       # per year, on notional held (stress scenario only)


@dataclass
class PResult:
    equity: pd.Series
    trades: pd.DataFrame
    config: PConfig
    stats: dict = field(default_factory=dict)


def _pnl_usd(n: float, entry: float, exit_: float, side: int, usd_base: bool) -> float:
    if usd_base:
        return side * n * (exit_ - entry) / exit_
    return side * n * (exit_ / entry - 1.0)


def run_portfolio(markets: list[Market], cfg: PConfig) -> PResult:
    idx = markets[0].df.index
    for mk in markets[1:]:
        idx = idx.union(mk.df.index)
    idx = idx.sort_values()
    T, M = len(idx), len(markets)

    own = [mk.df.index.get_indexer(idx) for mk in markets]          # -1 where the market has no bar that day
    O = [mk.df["open"].to_numpy() for mk in markets]
    H = [mk.df["high"].to_numpy() for mk in markets]
    L = [mk.df["low"].to_numpy() for mk in markets]
    C = [mk.df["close"].to_numpy() for mk in markets]
    le = [np.asarray(mk.sig["long_entry"], bool) for mk in markets]
    se = [np.asarray(mk.sig["short_entry"], bool) for mk in markets]
    lx = [np.asarray(mk.sig["long_exit"], bool) for mk in markets]
    sx = [np.asarray(mk.sig["short_exit"], bool) for mk in markets]
    sd = [np.asarray(mk.sig["stop_dist"], float) for mk in markets]

    cash = cfg.initial_equity
    pos = [0] * M
    notional = [0.0] * M
    epx = [0.0] * M
    spx = [0.0] * M
    ebar = [0] * M
    etime = [None] * M
    riskc = [0.0] * M
    last_close = [np.nan] * M
    trades: list[dict] = []
    eq = np.full(T, np.nan)

    def mtm(m: int) -> float:
        if pos[m] == 0 or not np.isfinite(last_close[m]):
            return 0.0
        mk = markets[m]
        px = last_close[m] if pos[m] == 1 else last_close[m] + mk.spread   # shorts are marked at the ask
        return _pnl_usd(notional[m], epx[m], px, pos[m], mk.usd_base)

    def equity_now() -> float:
        return cash + sum(mtm(m) for m in range(M) if pos[m] != 0)

    def close_trade(m: int, i: int, px: float, reason: str) -> None:
        nonlocal cash
        mk = markets[m]
        pnl = _pnl_usd(notional[m], epx[m], px, pos[m], mk.usd_base)
        cash += pnl
        trades.append({
            "market": mk.name, "side": "long" if pos[m] == 1 else "short",
            "entry_time": etime[m], "exit_time": idx[i], "notional": notional[m],
            "entry": epx[m], "exit": px, "stop": spx[m], "pnl": pnl,
            "r": pnl / riskc[m] if riskc[m] else np.nan, "reason": reason, "bars": i - ebar[m],
        })
        pos[m] = 0
        notional[m] = 0.0

    for i in range(T):
        ts = idx[i]
        for m in range(M):
            j = own[m][i]
            if j < 0:
                continue                      # market closed / no data today
            mk = markets[m]
            o, h, l, c = O[m][j], H[m][j], L[m][j], C[m][j]
            if j >= 1:
                n_before = len(trades)
                if pos[m] == 1:
                    if o <= spx[m]:
                        close_trade(m, i, o - mk.slippage, "stop_gap")
                    elif l <= spx[m]:
                        close_trade(m, i, spx[m] - mk.slippage, "stop")
                    elif lx[m][j - 1]:
                        close_trade(m, i, o - mk.slippage, "signal")
                elif pos[m] == -1:
                    if o + mk.spread >= spx[m]:
                        close_trade(m, i, o + mk.spread + mk.slippage, "stop_gap")
                    elif h + mk.spread >= spx[m]:
                        close_trade(m, i, spx[m] + mk.slippage, "stop")
                    elif sx[m][j - 1]:
                        close_trade(m, i, o + mk.spread + mk.slippage, "signal")
                stopped_bar = len(trades) > n_before and trades[-1]["reason"] == "stop"

                if pos[m] == 0 and not stopped_bar and np.isfinite(sd[m][j - 1]) and sd[m][j - 1] > 0:
                    side = 1 if le[m][j - 1] else (-1 if se[m][j - 1] else 0)
                    if side != 0:
                        dist = sd[m][j - 1] + mk.spread + mk.slippage
                        eq_now = equity_now()
                        n_new = cfg.risk_pct * eq_now * o / dist
                        gross = sum(notional[k] for k in range(M) if pos[k] != 0)
                        n_new = min(n_new, max(0.0, cfg.max_gross_leverage * eq_now - gross))
                        if n_new > 1e-9 and eq_now > 0:
                            pos[m], notional[m], ebar[m], etime[m] = side, n_new, i, ts
                            riskc[m] = n_new * dist / o
                            if side == 1:
                                epx[m] = o + mk.spread + mk.slippage
                                spx[m] = o - sd[m][j - 1]
                                if l <= spx[m]:
                                    close_trade(m, i, spx[m] - mk.slippage, "stop")
                            else:
                                epx[m] = o - mk.slippage
                                spx[m] = o + sd[m][j - 1]
                                if h + mk.spread >= spx[m]:
                                    close_trade(m, i, spx[m] + mk.slippage, "stop")
            last_close[m] = c

        if cfg.financing_rate and i > 0:
            days = (ts - idx[i - 1]).days
            drag = sum(notional[m] for m in range(M) if pos[m] != 0) * cfg.financing_rate * days / 365.0
            cash -= drag
        eq[i] = equity_now()

    for m in range(M):                         # close whatever is still open at the last close
        if pos[m] != 0:
            mk = markets[m]
            j_last = int(np.max(np.nonzero(own[m] >= 0)[0]))
            c = last_close[m]
            px = c - mk.slippage if pos[m] == 1 else c + mk.spread + mk.slippage
            close_trade(m, j_last, px, "end")
    eq[-1] = cash if all(p == 0 for p in pos) else eq[-1]

    equity = pd.Series(eq, index=idx).ffill()
    tdf = pd.DataFrame(trades)
    res = PResult(equity, tdf, cfg)
    res.stats = portfolio_stats(res)
    return res


def sharpe_of(equity: pd.Series, start=None, end=None) -> float:
    e = equity.loc[start:end]
    r = e.pct_change().dropna()
    if len(r) < 20 or r.std() == 0:
        return float("nan")
    return float(r.mean() / r.std() * np.sqrt(252))


def portfolio_stats(res: PResult) -> dict:
    eq, t, init = res.equity, res.trades, res.config.initial_equity
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    end = float(eq.iloc[-1])
    out = {
        "end_equity": end,
        "return_pct": (end / init - 1) * 100,
        "cagr_pct": ((end / init) ** (1 / years) - 1) * 100 if end > 0 else -100.0,
        "max_drawdown_pct": float((eq / eq.cummax() - 1).min() * 100),
        "sharpe": sharpe_of(eq),
        "years": years,
        "trades": int(len(t)),
    }
    if len(t):
        w, lo = t.loc[t.pnl > 0, "pnl"], t.loc[t.pnl <= 0, "pnl"]
        out["profit_factor"] = float(w.sum() / abs(lo.sum())) if len(lo) and lo.sum() != 0 else float("inf")
        out["win_rate_pct"] = float(len(w) / len(t) * 100)
        out["avg_R"] = float(t["r"].mean())
    return out
```

### `mt5bot/strategies.py`

```python
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
```

### `mt5bot/data.py`

```python
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
```

### `mt5bot/live.py`

```python
"""Live-style daily signal logic (Phase A: no broker connection).

Design rules
  * ONE source of truth for signals: mt5bot.strategies.donchian_breakout, the same function the
    backtests use. This module only decides what to do at the NEXT open from CLOSED bars.
  * decide() never sees anything but bars that have closed (the caller must drop the partial bar).
  * Indicators are computed on the last WINDOW bars. ATR is an exponential average whose memory is
    ~(13/14)^800 ~ 1e-26 at that length, so this equals the full-history value to float precision
    (check_live.py proves it), and it keeps the daily run fast.
  * Stops are ALWAYS placed at the broker as real stop orders, never only inside this script.
  * The signal spec below is the pre-registered primary spec. Its backtest FAILED (see HANDOFF.md
    section 9.2); it is used here as a test harness for the execution plumbing, not as a proven edge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategies import donchian_breakout

SPEC = dict(entry_n=55, exit_n=20, atr_n=14, atr_stop=3.0)
WINDOW = 800

# contract size (units per 1.0 lot), whether the pair is USD-base, default lot limits.
# Lot limits and contract sizes are broker-specific: confirm them in the MT5 symbol specification.
MARKET_SPECS = {
    "EURUSD": dict(contract=100_000, usd_base=False), "GBPUSD": dict(contract=100_000, usd_base=False),
    "AUDUSD": dict(contract=100_000, usd_base=False), "NZDUSD": dict(contract=100_000, usd_base=False),
    "USDJPY": dict(contract=100_000, usd_base=True),  "USDCAD": dict(contract=100_000, usd_base=True),
    "USDCHF": dict(contract=100_000, usd_base=True),  "XAUUSD": dict(contract=100, usd_base=False),
}


@dataclass
class Position:
    side: int            # +1 long, -1 short
    entry: float         # effective entry price (what you were filled at)
    stop: float          # broker stop-loss price
    lots: float = 0.0
    opened: str = ""     # label of the bar the trade was opened on


@dataclass
class Decision:
    asof: pd.Timestamp   # label of the last CLOSED bar the decision is based on
    close_position: bool # exit signal for the open position (act at the next open)
    entry_side: int      # side signalled for the next open: +1, -1 or 0 (applies if flat at that open)
    stop_dist: float     # stop distance in price units (NaN if none)
    note: str


def closed_bars(d: pd.DataFrame, now_utc: pd.Timestamp | None = None) -> pd.DataFrame:
    """Drop the bar that is still forming. A bar is labelled with the date on which it closes
    (17:00 New York), so a bar is complete only once the 17:00-NY-shifted clock has passed its label."""
    now = pd.Timestamp.now(tz="UTC") if now_utc is None else pd.Timestamp(now_utc)
    now = now.tz_localize("UTC") if now.tzinfo is None else now
    ny_wall = now.tz_convert("America/New_York").tz_localize(None)
    current_label = (ny_wall + pd.Timedelta(hours=7)).normalize()   # label of the bar now forming
    return d[d.index < current_label]


def decide(df_closed: pd.DataFrame, pos: Position | None, spec: dict = SPEC) -> Decision:
    """What to do at the next open, given only closed bars and the current position (or None)."""
    w = df_closed.iloc[-WINDOW:]
    s = donchian_breakout(w, **spec)
    le, se, lx, sx = (bool(s[k][-1]) for k in ("long_entry", "short_entry", "long_exit", "short_exit"))
    sd = float(s["stop_dist"][-1])
    close = pos is not None and ((pos.side == 1 and lx) or (pos.side == -1 and sx))
    side = 1 if le else (-1 if se else 0)
    if not (math.isfinite(sd) and sd > 0):
        side, sd = 0, float("nan")
    parts = []
    if close:
        parts.append("exit signal")
    if side:
        parts.append(f"{'long' if side == 1 else 'short'} entry signal")
    return Decision(df_closed.index[-1], close, side, sd, ", ".join(parts) or "no signal")


def stop_hit(pos: Position, bar: pd.Series, spread: float) -> bool:
    """Was the broker stop touched during this closed bar? (long: bid low; short: ask = high + spread)"""
    return bar["low"] <= pos.stop if pos.side == 1 else bar["high"] + spread >= pos.stop


def lots_for(market: str, equity: float, risk_pct: float, stop_dist: float, price: float,
             spread: float = 0.0, slippage: float = 0.0, min_lot: float = 0.01, lot_step: float = 0.01,
             max_lot: float = 50.0) -> tuple[float, float]:
    """(lots, actual_risk_cash). Rounds DOWN; returns 0 lots if even the minimum lot would risk more
    than intended (we never over-risk just to get a trade on, same rule as the backtest)."""
    spec = MARKET_SPECS[market]
    dist = stop_dist + spread + slippage
    per_lot = dist * spec["contract"] / (price if spec["usd_base"] else 1.0)   # USD lost per 1.0 lot at the stop
    if per_lot <= 0:
        return 0.0, 0.0
    raw = min(risk_pct * equity / per_lot, max_lot)
    q = math.floor(raw / lot_step + 1e-9) * lot_step
    if q < min_lot:
        return 0.0, min_lot * per_lot       # second value: what the minimum lot WOULD risk
    return round(q, 8), q * per_lot
```

### `run_portfolio_test.py`

```python
#!/usr/bin/env python3
"""PRE-REGISTERED multi-market daily trend-following test.  python run_portfolio_test.py

The specification below was fixed BEFORE any multi-market data was looked at. Do not edit it after
seeing results - if you want to explore variants, add them to the clearly-labelled post-hoc section.

PRIMARY SPEC
  markets   : EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD XAUUSD  (daily bars on the 17:00 New York FX roll, v6 data)
  signal    : Donchian breakout, enter on a close beyond the prior 55-day high/low (long and short),
              exit on a close beyond the prior 20-day opposite extreme, ATR(14) x 3.0 stop
  execution : next bar's open; costs below; one position per market
  sizing    : 0.5% of portfolio equity risked per position (stop distance), shared equity pool
  costs     : "realistic" = typical modern retail spread + 10% slippage per fill
              "harsh"     = 2x spread and slippage + 2%/yr financing drag on notional (stand-in for swap)
PASS RULE (all three must hold)
  1. realistic-cost full-period Sharpe >= 0.50
  2. realistic-cost Sharpe >= 0.20 in EACH half (2003-2014 and 2015-2026)
  3. harsh-cost full-period Sharpe >= 0.30
"""
from __future__ import annotations
import argparse, os, sys
import numpy as np, pandas as pd
from mt5bot.portfolio import Market, PConfig, run_portfolio, sharpe_of
from mt5bot.data import validate_daily
from mt5bot.strategies import donchian_breakout

# name: (spread, slippage, usd_base)   prices in quote units; spread is paid once per round trip
COSTS = {
    "EURUSD": (0.00010, 0.00001, False), "GBPUSD": (0.00013, 0.00001, False),
    "USDJPY": (0.010, 0.001, True),      "AUDUSD": (0.00012, 0.00001, False),
    "USDCAD": (0.00015, 0.00002, True),  "USDCHF": (0.00015, 0.00002, True),
    "NZDUSD": (0.00015, 0.00002, False), "XAUUSD": (0.30, 0.05, False),
}
HALF_SPLIT = "2014-12-31"


def load(data_dir: str) -> dict:
    out = {}
    for name in COSTS:
        p = os.path.join(data_dir, f"{name}_D1.csv")
        if os.path.exists(p):
            d = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
            if not d.index.is_monotonic_increasing or d.index[-1] > pd.Timestamp.now() + pd.Timedelta(days=2):
                sys.exit(f"{name}: dates look wrong - refusing to run")
            issues = validate_daily(d, name)
            if issues:
                sys.exit("DATA PROBLEM - refusing to run:\n  " + "\n  ".join(issues) +
                         "\nRebuild the daily files with:  python download_universe.py   (v6 to_daily)")
            out[name] = d
        else:
            print(f"WARNING: {p} not found - {name} skipped")
    return out


def build(data: dict, entry_n=55, exit_n=20, atr_stop=3.0, cost_mult=1.0):
    mk = []
    for name, d in data.items():
        sp, sl, ub = COSTS[name]
        mk.append(Market(name, d, donchian_breakout(d, entry_n, exit_n, 14, atr_stop), sp * cost_mult, sl * cost_mult, ub))
    return mk


def describe(label, r):
    s = r.stats
    print(f"{label:34s} Sharpe {s['sharpe']:+.2f} | CAGR {s['cagr_pct']:+.1f}% | maxDD {s['max_drawdown_pct']:.1f}% | "
          f"trades {s['trades']} | PF {s.get('profit_factor', float('nan')):.2f} | avg R {s.get('avg_R', float('nan')):+.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/universe_daily")
    ap.add_argument("--risk", type=float, default=0.005)
    a = ap.parse_args()
    data = load(a.data_dir)
    if not data:
        sys.exit("no data files found")
    print(f"markets: {', '.join(data)}")
    if len(data) < len(COSTS):
        print(f"NOTE: the pre-registered universe has {len(COSTS)} markets; with only {len(data)} the verdict below is NOT the official one.")
    print(f"period : {min(d.index[0] for d in data.values()).date()} -> {max(d.index[-1] for d in data.values()).date()}\n")

    cfg_real = PConfig(initial_equity=100_000, risk_pct=a.risk)
    cfg_harsh = PConfig(initial_equity=100_000, risk_pct=a.risk, financing_rate=0.02)
    real = run_portfolio(build(data), cfg_real)
    harsh = run_portfolio(build(data, cost_mult=2.0), cfg_harsh)

    print("=== PRIMARY SPEC (pre-registered) ===")
    describe("realistic costs, 2003-2026", real)
    describe("harsh costs + financing, 2003-2026", harsh)
    s_full = real.stats["sharpe"]
    s1, s2 = sharpe_of(real.equity, None, HALF_SPLIT), sharpe_of(real.equity, "2015-01-01", None)
    s_h = harsh.stats["sharpe"]
    print(f"realistic Sharpe by half: 2003-2014 {s1:+.2f} | 2015-2026 {s2:+.2f}")

    yr = real.equity.resample("YE").last().pct_change() * 100
    yr.iloc[0] = (real.equity.resample("YE").last().iloc[0] / cfg_real.initial_equity - 1) * 100
    print("\nreturn by year (%):", {int(i.year): round(v, 1) for i, v in yr.items()})

    t = real.trades
    if len(t):
        g = t.groupby("market").agg(trades=("pnl", "size"), pnl_usd=("pnl", "sum"), avg_R=("r", "mean"),
                                    win_pct=("pnl", lambda x: 100 * (x > 0).mean()))
        print("\nper-market contribution (realistic):"); print(g.round(2).to_string())
        top = g.pnl_usd.sort_values(ascending=False)
        total = t.pnl.sum()
        if total > 0:
            print(f"share of total profit from the single best market: {100 * top.iloc[0] / total:.0f}% ({top.index[0]})")
        else:
            print(f"total P&L is not positive, so no profit to attribute (best single market: {top.index[0]})")

    ok1, ok2, ok3 = s_full >= 0.50, (s1 >= 0.20 and s2 >= 0.20), s_h >= 0.30
    print("\n=== PRE-REGISTERED VERDICT ===")
    print(f"1. realistic full-period Sharpe >= 0.50 : {s_full:+.2f}  {'ok' if ok1 else 'NO'}")
    print(f"2. Sharpe >= 0.20 in each half          : {s1:+.2f} / {s2:+.2f}  {'ok' if ok2 else 'NO'}")
    print(f"3. harsh-cost Sharpe >= 0.30            : {s_h:+.2f}  {'ok' if ok3 else 'NO'}")
    print("RESULT:", "PASS" if (ok1 and ok2 and ok3) else "FAIL")

    print("\n=== POST-HOC ROBUSTNESS (NOT used for the verdict; for information only) ===")
    print("realistic costs, Sharpe full / 2003-2014 / 2015-2026:")
    for en, ex in ((20, 10), (40, 20), (55, 20), (80, 40), (100, 50)):
        r = run_portfolio(build(data, en, ex), cfg_real)
        print(f"  Donchian {en}/{ex}, stop x3: {r.stats['sharpe']:+.2f} / {sharpe_of(r.equity, None, HALF_SPLIT):+.2f} / "
              f"{sharpe_of(r.equity, '2015-01-01', None):+.2f}   maxDD {r.stats['max_drawdown_pct']:.0f}%")

    real.equity.to_csv("portfolio_equity.csv"); real.trades.to_csv("portfolio_trades.csv", index=False)
    print("\nsaved portfolio_equity.csv and portfolio_trades.csv")


if __name__ == "__main__":
    main()
```

### `signal_runner.py`

```python
#!/usr/bin/env python3
"""Daily signal sheet (Phase A - no broker connection, nothing is traded by this script).

    python signal_runner.py refresh                 # download the latest months, rebuild daily files, audit them
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
    sub.add_parser("show")
    a = ap.parse_args()
    {"refresh": cmd_refresh, "signals": cmd_signals, "record": cmd_record, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    main()
```

### `check_engine.py`

```python
"""Engine self-test. Run after ANY change to mt5bot/backtest.py:   python check_engine.py

On random-walk data with ZERO costs no strategy can have an edge, so every strategy's
average result must be statistically indistinguishable from zero. We also compare the
engine against an independent bare-bones simulator that watches every price step.
Prints PASS/FAIL per check; any FAIL means do not trust backtest results.
"""
from __future__ import annotations
import numpy as np, pandas as pd
from mt5bot.backtest import Config, Instrument, run_backtest
from mt5bot.strategies import donchian_breakout, mean_reversion

ZERO = Instrument("EURUSD", 100_000, 0.0, 0.0, 0.0)
CFG = Config(initial_equity=10_000, max_drawdown_kill=None, daily_loss_limit=None)


def true_path(n=30_000, m=30, seed=0, start=1.10, annual_vol=0.07):
    """Hourly candles built from a genuine m-step-per-hour random walk with volatility
    clustering: every high/low is a price the path really visited."""
    rng = np.random.default_rng(seed)
    base = annual_vol / np.sqrt(24 * 252)
    lv = np.zeros(n)
    for i in range(1, n):
        lv[i] = 0.98 * lv[i - 1] + 0.15 * rng.standard_normal()
    vol = base * np.exp(lv - lv.var() / 2)
    steps = rng.standard_normal((n, m)) * (vol[:, None] / np.sqrt(m))
    logp = np.log(start) + np.cumsum(steps.ravel()).reshape(n, m)
    prev_end = np.concatenate([[np.log(start)], logp[:-1, -1]])
    p = np.exp(np.concatenate([prev_end[:, None], logp], axis=1))
    df = pd.DataFrame({"open": p[:, 0], "high": p.max(1), "low": p.min(1), "close": p[:, -1]},
                      index=pd.date_range("2018-01-01", periods=n, freq="1h"))
    return df, p


def reference_long_only(p, sig):
    """Independent simulator (long only): walks every sub-step, exits on stop or on the exit
    signal at the bar close, never re-enters inside the bar in which it was stopped."""
    n = p.shape[0]
    le, lx, sd = sig["long_entry"], sig["long_exit"], sig["stop_dist"]
    out, pos, entry, stop = [], False, 0.0, 0.0
    for h in range(1, n):
        if not pos and le[h - 1] and np.isfinite(sd[h - 1]):
            pos, entry, stop = True, p[h, 0], p[h, 0] - sd[h - 1]
        if pos:
            if (p[h] <= stop).any():
                out.append((stop - entry) * 1e4); pos = False; continue
            if lx[h]:
                out.append((p[h, -1] - entry) * 1e4); pos = False
    return np.array(out)


def main():
    ok = True
    # 1) engine vs independent reference
    ref, eng = [], []
    for s in range(8):
        df, p = true_path(seed=900 + s)
        sig = mean_reversion(df, 50, 2.0, 14, 3.0, allow_short=False)
        ref.append(reference_long_only(p, sig))
        t = run_backtest(df, sig, ZERO, CFG).trades
        eng.append(((t.exit - t.entry) * 1e4).to_numpy())
    ref, eng = np.concatenate(ref), np.concatenate(eng)
    print(f"engine vs reference (mean-reversion, long only): trades {len(eng)} vs {len(ref)}, "
          f"mean pips {eng.mean():+.2f} vs {ref.mean():+.2f}")
    good = abs(len(eng) - len(ref)) / len(ref) < 0.03 and abs(eng.mean() - ref.mean()) < 3 * max(eng.std(), ref.std()) / np.sqrt(len(ref))
    print("  PASS" if good else "  FAIL"); ok &= good

    # 2) zero-cost random walk: average R must be ~0 for every strategy
    res = {"donchian": [], "meanrev": [], "random-entries": []}
    for s in range(40):
        df, _ = true_path(n=20_000, seed=500 + s)
        for name, sg in (("donchian", donchian_breakout(df, 40, 20, 14, 2.0)),
                         ("meanrev", mean_reversion(df, 50, 2.0, 14, 3.0))):
            r = run_backtest(df, sg, ZERO, CFG); res[name].append((r.stats["avg_R"], r.stats["profit_factor"]))
        rng = np.random.default_rng(s); u = rng.random(len(df)); sg = dict(donchian_breakout(df, 40, 20, 14, 2.0))
        sg["long_entry"], sg["short_entry"] = u < 0.01, u > 0.99
        sg["long_exit"], sg["short_exit"] = rng.random(len(df)) < 0.05, rng.random(len(df)) < 0.05
        r = run_backtest(df, sg, ZERO, CFG); res["random-entries"].append((r.stats["avg_R"], r.stats["profit_factor"]))
    print("\nzero-cost random walk, 40 runs each (want avg R ~ 0: within 3 s.e. or within +/-0.02R;")
    print("a real engine bug shows up as -0.04R or worse):")
    for k, v in res.items():
        a = np.array(v); m, se = a[:, 0].mean(), a[:, 0].std() / np.sqrt(len(a))
        good = abs(m) < 3 * se or abs(m) < 0.02
        print(f"  {k:15s} avg R {m:+.3f} (s.e. {se:.3f})  PF {a[:, 1].mean():.2f}   {'PASS' if good else 'FAIL'}")
        ok &= good
    print("\nOVERALL:", "ALL CHECKS PASSED" if ok else "SOMETHING IS WRONG - do not trust backtests")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### `check_portfolio.py`

```python
"""Portfolio-simulator self-test.  Run after ANY change to mt5bot/portfolio.py:  python check_portfolio.py

A) trade-for-trade equivalence with the already-verified single-market engine (backtest.py)
B) zero-cost random walks across 8 markets: no edge may appear (Sharpe ~ 0, avg R ~ 0)
C) (if the data files exist) real EURUSD daily: same trades as the single-market engine
"""
from __future__ import annotations
import os
import numpy as np, pandas as pd
from mt5bot.backtest import Config, Instrument, run_backtest
from mt5bot.portfolio import Market, PConfig, run_portfolio, sharpe_of
from mt5bot.strategies import donchian_breakout


def true_path_daily(n=6000, m=24, seed=0, start=1.10, annual_vol=0.08):
    """Daily candles from a genuine m-step random walk with volatility clustering."""
    rng = np.random.default_rng(seed)
    base = annual_vol / np.sqrt(252)
    lv = np.zeros(n)
    for i in range(1, n):
        lv[i] = 0.98 * lv[i - 1] + 0.15 * rng.standard_normal()
    vol = base * np.exp(lv - lv.var() / 2)
    steps = rng.standard_normal((n, m)) * (vol[:, None] / np.sqrt(m))
    logp = np.log(start) + np.cumsum(steps.ravel()).reshape(n, m)
    prev_end = np.concatenate([[np.log(start)], logp[:-1, -1]])
    p = np.exp(np.concatenate([prev_end[:, None], logp], axis=1))
    return pd.DataFrame({"open": p[:, 0], "high": p.max(1), "low": p.min(1), "close": p[:, -1]},
                        index=pd.date_range("2003-06-02", periods=n, freq="D"))


def sig_for(df):
    return donchian_breakout(df, 55, 20, 14, 3.0)


def check_equivalence():
    """Single market, USD-quote, nonzero costs, huge equity (so lot rounding can't matter)."""
    bad = 0; n_tr = 0
    for seed in range(6):
        df = true_path_daily(n=4000, seed=seed)
        sig = sig_for(df)
        inst = Instrument("X", 100_000, 0.0002, 0.00003, 0.0, min_lot=1e-9, lot_step=1e-9, max_lot=1e12)
        a = run_backtest(df, sig, inst, Config(initial_equity=1e9, risk_pct=0.005, max_leverage=1e9,
                                               daily_loss_limit=None, max_drawdown_kill=None)).trades
        b = run_portfolio([Market("X", df, sig, 0.0002, 0.00003)], PConfig(initial_equity=1e9)).trades
        n_tr += len(a)
        if len(a) != len(b):
            bad += 1; print(f"  seed {seed}: trade count {len(a)} vs {len(b)}"); continue
        same = (a.entry_time.values == b.entry_time.values).all() and (a.exit_time.values == b.exit_time.values).all() \
            and np.allclose(a.exit.values, b.exit.values, atol=1e-12) and (a.side.values == b.side.values).all() \
            and (a.reason.values == b.reason.values).all()
        if not same:
            bad += 1; print(f"  seed {seed}: trades differ")
    print(f"A) equivalence with single-market engine: {n_tr} trades over 6 runs, {bad} runs differ")
    return bad == 0


def check_neutrality():
    zero = [(0.0, 0.0, False), (0.0, 0.0, True)]
    sharpes, rs = [], []
    for s in range(30):
        mk = []
        for k in range(8):
            df = true_path_daily(n=6000, seed=1000 + 10 * s + k, start=1.1 if k % 4 else 110.0)
            mk.append(Market(f"M{k}", df, sig_for(df), 0.0, 0.0, usd_base=(k % 4 == 3)))
        r = run_portfolio(mk, PConfig(initial_equity=100_000, risk_pct=0.005))
        sharpes.append(r.stats["sharpe"]); rs.append(r.stats["avg_R"])
    sh, rr = np.array(sharpes), np.array(rs)
    sh_se, r_se = sh.std() / np.sqrt(len(sh)), rr.std() / np.sqrt(len(rr))
    ok1 = abs(sh.mean()) < 3 * sh_se or abs(sh.mean()) < 0.10
    ok2 = abs(rr.mean()) < 3 * r_se or abs(rr.mean()) < 0.03
    print(f"B) zero-cost random walks, 30 portfolios x 8 markets x 6000 days: "
          f"Sharpe {sh.mean():+.3f} (s.e. {sh_se:.3f}) | avg R {rr.mean():+.3f} (s.e. {r_se:.3f})  "
          f"{'PASS' if ok1 and ok2 else 'FAIL'}")
    return ok1 and ok2


def check_real_eurusd():
    f1, f2 = "data/EURUSD_H1_old.csv", "data/EURUSD_H1.csv"
    if not (os.path.exists(f1) and os.path.exists(f2)):
        print("C) real EURUSD cross-check skipped (data files not found)"); return True
    from mt5bot.data import load_csv, to_daily
    h = pd.concat([load_csv(f1), load_csv(f2)]); h = h[~h.index.duplicated()].sort_index()
    d = to_daily(h)
    sig = sig_for(d)
    inst = Instrument("EURUSD", 100_000, 0.00010, 0.00001, 0.0, min_lot=1e-9, lot_step=1e-9, max_lot=1e12)
    a = run_backtest(d, sig, inst, Config(initial_equity=1e9, risk_pct=0.005, max_leverage=1e9,
                                          daily_loss_limit=None, max_drawdown_kill=None)).trades
    b = run_portfolio([Market("EURUSD", d, sig, 0.00010, 0.00001)], PConfig(initial_equity=1e9)).trades
    ok = len(a) == len(b) and (a.exit_time.values == b.exit_time.values).all() and np.allclose(a.exit.values, b.exit.values, atol=1e-12)
    print(f"C) real EURUSD daily, 2003-2026: {len(a)} vs {len(b)} trades, identical timing and prices: {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    ok = True
    r = check_equivalence(); print("   PASS" if r else "   FAIL"); ok &= r
    ok &= check_neutrality()
    ok &= check_real_eurusd()
    print("\nOVERALL:", "ALL CHECKS PASSED" if ok else "SOMETHING IS WRONG - do not trust portfolio results")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### `check_data.py`

```python
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
```

### `check_live.py`

```python
"""Live-logic self-test.   python check_live.py [--all]   (run after ANY change to mt5bot/live.py)

A) NO-PEEK: signals computed from the last WINDOW closed bars up to day t must equal the signals the
   full-history backtest has for day t. Catches look-ahead and window/warm-up differences.
B) REPLAY: step through history one closed bar at a time, call decide() on ONLY the bars known at that
   moment, keep a paper position, and compare the resulting trades (entry/exit dates, side, reason,
   exit price) with the portfolio backtest engine. They must be identical.

The paper broker below deliberately follows the SAME fill conventions as mt5bot/portfolio.py (stop wins
over a same-bar signal exit, gap fills at the open, no re-entry on a bar where a stop fired mid-bar).
Real data (data/universe_daily) is used if present: EURUSD and XAUUSD by default, every market with --all.
"""
from __future__ import annotations
import argparse, os, sys, time
import numpy as np, pandas as pd
from check_portfolio import true_path_daily
from mt5bot.live import SPEC, WINDOW, Position, decide
from mt5bot.portfolio import Market, PConfig, run_portfolio
from mt5bot.strategies import donchian_breakout

SPREAD, SLIP = 0.0002, 0.00003


def check_no_peek(df, name, n_cuts=150, seed=0):
    full = donchian_breakout(df, **SPEC)
    rng = np.random.default_rng(seed)
    cuts = rng.integers(60, len(df), n_cuts)
    bad = 0
    for t in cuts:
        w = donchian_breakout(df.iloc[:t + 1].iloc[-WINDOW:], **SPEC)
        for k in ("long_entry", "short_entry", "long_exit", "short_exit"):
            bad += int(w[k][-1] != full[k][t])
        a, b = w["stop_dist"][-1], full["stop_dist"][t]
        bad += int(not ((np.isnan(a) and np.isnan(b)) or np.isclose(a, b, rtol=1e-9, atol=0)))
    print(f"A) no-peek {name:8s}: {len(cuts)} cut points, {bad} mismatches  {'PASS' if bad == 0 else 'FAIL'}")
    return bad == 0


def replay(df, spread=SPREAD, slip=SLIP):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    idx = df.index
    pos, trades = None, []

    def close(j, px, reason):
        nonlocal pos
        trades.append(dict(entry_time=pos.opened, exit_time=idx[j], side="long" if pos.side == 1 else "short",
                           exit=px, reason=reason))
        pos = None

    for j in range(1, len(df)):
        dec = decide(df.iloc[:j], pos)          # ONLY bars 0..j-1 are known here
        n0, stopped = len(trades), False
        if pos is not None:
            if pos.side == 1:
                if o[j] <= pos.stop: close(j, o[j] - slip, "stop_gap")
                elif l[j] <= pos.stop: close(j, pos.stop - slip, "stop")
                elif dec.close_position: close(j, o[j] - slip, "signal")
            else:
                if o[j] + spread >= pos.stop: close(j, o[j] + spread + slip, "stop_gap")
                elif h[j] + spread >= pos.stop: close(j, pos.stop + slip, "stop")
                elif dec.close_position: close(j, o[j] + spread + slip, "signal")
            stopped = len(trades) > n0 and trades[-1]["reason"] == "stop"
        if pos is None and not stopped and dec.entry_side != 0:
            s = dec.entry_side
            pos = Position(s, o[j] + spread + slip if s == 1 else o[j] - slip,
                           o[j] - dec.stop_dist if s == 1 else o[j] + dec.stop_dist, 0.0, idx[j])
            if s == 1 and l[j] <= pos.stop: close(j, pos.stop - slip, "stop")
            elif s == -1 and h[j] + spread >= pos.stop: close(j, pos.stop + slip, "stop")
    return pd.DataFrame(trades)


def check_replay(df, name):
    t0 = time.time()
    mine = replay(df)
    eng = run_portfolio([Market(name, df, donchian_breakout(df, **SPEC), SPREAD, SLIP)],
                        PConfig(initial_equity=1e9)).trades
    eng = eng[eng.reason != "end"].reset_index(drop=True)
    ok = len(mine) == len(eng)
    if ok and len(mine):
        ok = ((mine.entry_time.values == eng.entry_time.values).all() and (mine.exit_time.values == eng.exit_time.values).all()
              and (mine.side.values == eng.side.values).all() and (mine.reason.values == eng.reason.values).all()
              and np.allclose(mine.exit.values, eng.exit.values, atol=1e-9))
    print(f"B) replay  {name:8s}: live-style {len(mine)} vs engine {len(eng)} trades, identical: {'PASS' if ok else 'FAIL'}  ({time.time() - t0:.0f}s)")
    if not ok:
        n = min(len(mine), len(eng))
        for i in range(n):
            if not (mine.entry_time[i] == eng.entry_time[i] and mine.exit_time[i] == eng.exit_time[i] and mine.reason[i] == eng.reason[i]):
                print("   first difference:\n", mine.iloc[i].to_dict(), "\n", eng.iloc[i][["entry_time", "exit_time", "side", "reason", "exit"]].to_dict()); break
    return ok


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--all", action="store_true")
    ap.add_argument("--data-dir", default="data/universe_daily"); a = ap.parse_args()
    ok = True
    for seed in (1, 2):
        df = true_path_daily(n=3000, seed=seed)
        ok &= check_no_peek(df, f"synth{seed}"); ok &= check_replay(df, f"synth{seed}")
    names = ["EURUSD", "XAUUSD"] if not a.all else ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"]
    found = False
    for n in names:
        p = os.path.join(a.data_dir, f"{n}_D1.csv")
        if os.path.exists(p):
            found = True
            d = pd.read_csv(p, index_col=0, parse_dates=True)
            ok &= check_no_peek(d, n); ok &= check_replay(d, n)
    if not found:
        print("   (no real data files found - real-data checks skipped)")
    print("\nOVERALL:", "ALL LIVE CHECKS PASSED" if ok else "SOMETHING IS WRONG - do not trust the signal runner")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### `fetch_dukascopy.py`

```python
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
```

### `download_universe.py`

```python
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
```

### `research.py`

```python
"""Experiment 1: breakout vs mean-reversion x timeframe x filters, realistic costs.

Rules that keep this honest:
  * one fixed split date; every config is evaluated on BOTH halves, nothing is picked using the test half
  * signals are computed on the full history then cut (no indicator warm-up artefacts)
  * risk limits are switched off so we see the raw signal quality (they are a live-trading safety, not an edge)
"""
from __future__ import annotations
import itertools, sys, time
import numpy as np, pandas as pd
from mt5bot.backtest import Config, Instrument, run_backtest
from mt5bot.data import load_csv, resample, to_daily
from mt5bot.strategies import donchian_breakout, mean_reversion, with_session, with_trend

CSV = sys.argv[1] if len(sys.argv) > 1 else "data/EURUSD_H1.csv"
# Standard retail account: 1.0 pip spread, 0.1 pip slippage per fill, no commission  (~1.2 pips round trip)
STD = Instrument("EURUSD", 100_000, 0.00010, 0.00001, 0.0)
# What my first run used (~2.3 pips round trip): stress test only
HARSH = Instrument("EURUSD", 100_000, 0.00012, 0.00002, 7.0)
CFG = Config(max_drawdown_kill=None, daily_loss_limit=None)

h1 = load_csv(CSV)
SPLIT = h1.index[int(len(h1) * 0.6)]
# Daily bars on the 17:00 New York FX roll (v6 fix; the old fixed 22:00 UTC cut created spurious Sunday stub bars)
D1 = to_daily(h1)
FRAMES = {"H1": h1, "H4": resample(h1, "4h"), "D1": D1}

def seg(sig, a, b): return {k: v[a:b] for k, v in sig.items()}

def stats(df, sig, inst, a, b):
    r = run_backtest(df.iloc[a:b], seg(sig, a, b), inst, CFG)
    s, t = r.stats, r.trades
    n = s["trades"]
    tstat = np.nan
    if n >= 5 and t["r"].std() > 0:
        tstat = t["r"].mean() / (t["r"].std() / np.sqrt(n))
    return dict(ret=s["return_pct"], n=n, pf=s.get("profit_factor", np.nan), avgR=s.get("avg_R", np.nan),
                dd=s["max_drawdown_pct"], t=tstat)

def grid(d): return [dict(zip(d, v)) for v in itertools.product(*d.values())]

DON = grid({"entry_n": [20, 40, 55, 80], "exit_n": [10, 20], "atr_stop": [2.0, 3.0]})
DON = [p for p in DON if p["exit_n"] < p["entry_n"]]
MR = grid({"n": [20, 50, 100], "k": [1.5, 2.0, 2.5, 3.0], "atr_stop": [2.0, 3.0, 4.0]})

def families():
    for tf in ("H1", "H4", "D1"):
        for filt in ("none", "session", "trend"):
            if filt == "session" and tf == "D1": continue
            yield "donchian", tf, filt, DON
            yield "meanrev", tf, filt, MR

def build(name, df, p, filt):
    sig = donchian_breakout(df, **p) if name == "donchian" else mean_reversion(df, **p)
    if filt == "session": sig = with_session(sig, df)
    if filt == "trend": sig = with_trend(sig, df)
    return sig

if __name__ == "__main__":
    rows, t0 = [], time.time()
    for name, tf, filt, G in families():
        if name == "meanrev" and filt == "trend": continue  # trend filter fights mean reversion by design
        df = FRAMES[tf]; a = df.index.searchsorted(SPLIT); n = len(df)
        for p in G:
            sig = build(name, df, p, filt)
            tr, te = stats(df, sig, STD, 0, a), stats(df, sig, STD, a, n)
            rows.append(dict(strategy=name, tf=tf, filt=filt, params=str(p),
                             **{f"tr_{k}": v for k, v in tr.items()}, **{f"te_{k}": v for k, v in te.items()}))
        print(f"{name:9s} {tf} {filt:8s} done ({time.time()-t0:.0f}s)", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv("results_exp1.csv", index=False)
    print("split date:", SPLIT, "| configs:", len(res))
```

