"""Same grid, $10k account (so daily-chart stops can be sized), at ZERO cost vs realistic cost.
Zero cost tells us whether any raw edge exists before the broker takes its cut."""
import sys; sys.argv = ["x", "data/EURUSD_H1.csv"]
import pandas as pd, numpy as np
import research as R
from mt5bot.backtest import Config, Instrument
R.CFG = Config(initial_equity=10_000, max_drawdown_kill=None, daily_loss_limit=None)
ZERO = Instrument("EURUSD", 100_000, 0.0, 0.0, 0.0)
rows = []
for name, tf, filt, G in R.families():
    if name == "meanrev" and filt == "trend": continue
    df = R.FRAMES[tf]; a = df.index.searchsorted(R.SPLIT); n = len(df)
    for p in G:
        sig = R.build(name, df, p, filt)
        for label, inst in (("zero", ZERO), ("std", R.STD)):
            tr, te = R.stats(df, sig, inst, 0, a), R.stats(df, sig, inst, a, n)
            rows.append(dict(strategy=name, tf=tf, filt=filt, params=str(p), cost=label,
                             **{f"tr_{k}": v for k, v in tr.items()}, **{f"te_{k}": v for k, v in te.items()}))
pd.DataFrame(rows).to_csv("results_exp2.csv", index=False)
print("done", len(rows))
