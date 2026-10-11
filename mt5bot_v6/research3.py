"""Pre-registered out-of-era test: the SAME 292 configs, nothing re-tuned, on 2003-2017 data
that no setting was ever chosen on. $10k account (so daily stops can be sized)."""
import sys; sys.argv = ["x", "data/EURUSD_H1_old.csv"]
import numpy as np, pandas as pd
import research as R
from mt5bot.backtest import Config
R.CFG = Config(initial_equity=10_000, max_drawdown_kill=None, daily_loss_limit=None)
rows = []
for name, tf, filt, G in R.families():
    if name == "meanrev" and filt == "trend": continue
    df = R.FRAMES[tf]; n = len(df)
    for p in G:
        sig = R.build(name, df, p, filt)
        for label, inst in (("std", R.STD), ("harsh", R.HARSH)):
            s = R.stats(df, sig, inst, 0, n)
            rows.append(dict(strategy=name, tf=tf, filt=filt, params=str(p), cost=label, **s))
    print(name, tf, filt, "done", flush=True)
pd.DataFrame(rows).to_csv("results_exp3.csv", index=False)
print({k: len(v) for k, v in R.FRAMES.items()}, "bars by timeframe")
