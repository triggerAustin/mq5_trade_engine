# Demo forward run (written before it starts)

**Purpose.** Prove the plumbing and measure real costs on the demo feed. Not a profit test.
**Rules.** The H4 candle rules of test #6 on EURUSD, GBPUSD, USDJPY, AUDUSD. Variant A = the locked rules (expected to lose, per the backtest). B = 1 pullback candle, C = no trend filter, D = 1.5R target. Fixed 0.01 lot, one position per symbol per variant, max 3 per variant, 20-candle time exit, stop and target set on the server.
**Known differences from the backtest.** (1) The broker's H4 candles are cut on server time, not 00/04/08 UTC, so candle shapes differ slightly. (2) The demo server's spreads, swaps and fills are not a real broker's. (3) No 20% drawdown halt or 3% daily-loss rule in the EA; a demo safety stop at 50% of starting equity only.
**Plumbing checks (look after about one week).** Every signal row is either TRADED or has a stated skip reason. Every position has a stop and a target. Time exits fire after 20 candles. Failed orders = 0. No unmatched closed positions. Snapshot spreads close to the backtest assumption.
**Results review.** Not before 100 closed trades for variant A (or three months, whichever is later). Variants B to D are information only. Nothing changes in the rules during the run. A good-looking result on fewer trades than that is not evidence.
**Setup.** Copy PA_Forward.mq5 to the terminal's MQL5/Experts folder, compile in MetaEditor (F7), attach to any one chart, tick Allow Algo Trading, keep the laptop awake and MT5 open.
