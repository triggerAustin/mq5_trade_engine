# Pre-registration #4 (DRAFT, not yet locked): daily trend-pullback on FX majors, $500 account

*Nothing has been run. This is locked only when the user says so; after that no edits, and variants go in a labelled post-hoc section.*

## Why FX majors only
On a $500 account with 1% risk per trade ($5), only FX at the 0.01 minimum lot can be sized sensibly: a 0.01-lot EURUSD position has about $0.10 per pip, so a 50-pip stop risks $5. Gold (1 oz = about $4,200 notional), the index CFDs (min 0.1 lot, about $780 to $5,000 notional) and the ETFs do not fit. This is a feasibility fact, not a preference.
Honest prior: two earlier trend tests on these pairs failed. Pullback entries are a different rule, but the probability of a pass is low. If it fails, FX at this account size is a dead end.

## Instruments and data
EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD; daily bars cut at 22:00 UTC (the Dukascopy files already in the project), 2003-06 onward.

## Rules (ONE specification, no parameter search)
- **Trend filter:** long only if the close is above its 200-day simple average; short only if below.
- **Entry (pullback resumes):** in an uptrend, the close was below the 20-day exponential average at some point in the last 5 days and today's close is back above it (mirror for shorts). Enter at the next day's open.
- **Stop:** 2 x ATR(14) from the entry price, fixed at entry.
- **Exit:** the close crosses the 20-day average against the trade (exit at the next open), or the stop is hit (assume the stop price, or the open if it gaps through it).
- **Risk per trade:** 1% of current equity, sized with the stop distance, rounded DOWN to 0.01-lot steps. A trade that would need less than 0.01 lot is taken at 0.01 only if it risks at most 2% of equity; otherwise it is skipped and counted.
- **Limits:** one position per pair, at most 3 open positions, trading stops for the day if equity is down 3% on the day, and the whole strategy stops (counted as failure) at a 20% drawdown from peak.
- Starting equity $500, USD account.

## Costs (always charged)
- **Spread** per round trip: the typical spreads used before (EURUSD 1.0 pip, GBPUSD 1.3, USDJPY 1.0, AUDUSD 1.2, USDCAD 1.5, USDCHF 1.5, NZDUSD 1.5) plus slippage at each fill. The demo spreads from the swap dump are used as a cross-check.
- **Swap** per night held, from the measured demo values (EURUSD long -0.70 and short -1.00 points per lot per day, and so on for each pair, with triple swap on the weekend rollover day).
- **Harsh case:** 2x spread, 2x slippage, 2x swap.

## Windows (locked box)
- **Stage A, development:** 2003-06 to 2018-12-31. Self-tests and one run of the primary spec.
- **Stage B, sealed:** 2019-01-01 to the end of the data (about 7.8 years). Run once, only if Stage A passes.

## Pass rule
Stage A, realistic costs, all must hold:
1. At least 150 trades.
2. Average net result per trade of at least +0.10 R (R = the amount risked), with a bootstrap 95% lower bound above -0.05 R.
3. Profit factor of at least 1.20.
4. Max drawdown of at most 20% on the $500 account, with lot rounding included.
5. Harsh-cost average result per trade of at least 0 R.
6. Both halves of Stage A have a positive average result per trade.
7. No single pair provides more than 40% of the profit.

Stage B passes if: average net result per trade of at least +0.05 R, drawdown of at most 20%, and not negative after harsh costs. A pass means "not rejected", never "proven".

## Engine validation required first
Random-walk data must show no profit (zero costs, many seeds). Independent reference implementation matches the engine. A deliberate look-ahead (peek at the same day's close) must be detected. Lot rounding, stop gaps and swap are unit-tested by hand-computed trades.

## Small-account feasibility is built in
The simulation runs on a $500 balance with real 0.01 lot steps, so the result already includes what the account can really hold.
