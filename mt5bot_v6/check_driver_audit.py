#!/usr/bin/env python3
"""Self-test of the audit machinery on fake data (run BEFORE trusting run_driver_audit.py):  python check_driver_audit.py
Proves: the t-statistic maths, the 1-day lag / forward-return alignment, that a planted effect is found, that pure noise is not,
and that data after 2018-12-31 is ignored."""
import sys

import numpy as np
import pandas as pd

from run_driver_audit import DEV_END, H, Z_CRIT, build_xy, evaluate, hac_t, log, tz

fails = []


def ok(name, cond, extra=""):
    log(f"{'PASS' if cond else 'FAIL'}  {name} {extra}")
    if not cond:
        fails.append(name)


# 1. hand-worked t: x = [1,2,3,4,10] -> mean 4, population variance 10, t = 4 / sqrt(10/5)
m, t = hac_t([1, 2, 3, 4, 10], L=0)
ok("t-statistic by hand", abs(m - 4) < 1e-12 and abs(t - 4 / np.sqrt(2)) < 1e-9, f"(t={t:.4f}, expected {4 / np.sqrt(2):.4f})")

# 2. alignment: feature = row number; feature used on row i must be the value from row i-1; return = log(close[i+H]/close[i])
idx = pd.bdate_range("2005-01-03", periods=60)
close = pd.Series(100 + np.arange(60) ** 1.5, index=idx)
feat = pd.Series(np.arange(60, dtype=float), index=idx)
d = build_xy(close, feat)
i = 20
ok("feature is lagged one row", d.s.loc[idx[i]] == i - 1, f"(got {d.s.loc[idx[i]]}, expected {i - 1})")
ok("forward return is close[t] -> close[t+H]", abs(d.r.loc[idx[i]] - np.log(close.iloc[i + H] / close.iloc[i])) < 1e-12)
ok("last H rows dropped (no future)", d.index[-1] == idx[60 - 1 - H])

# 3. planted effect found, in both signs
def fake(seed, beta, n=4200):
    rg = np.random.default_rng(seed)
    ix = pd.bdate_range("2003-06-02", periods=n)
    drv = pd.Series(rg.normal(size=n).cumsum(), index=ix)                  # driver level (random walk)
    z = tz(drv.diff(20))
    ret = beta * z.shift(1).fillna(0) + rg.normal(0, 0.006, n)           # pair return partly caused by the driver
    return pd.Series(100 * np.exp(ret.cumsum().values), index=ix), z

for beta in (0.002, -0.002):
    c, z = fake(1, beta)
    r = evaluate(c, z)
    ok(f"planted effect beta={beta:+} detected", np.sign(r["t"]) == np.sign(beta) and abs(r["t"]) > Z_CRIT and abs(r["t_h1"]) > 1 and abs(r["t_h2"]) > 1,
       f"(t={r['t']:+.1f}, halves {r['t_h1']:+.1f}, {r['t_h2']:+.1f})")

# 4. pure noise: false-positive rate must be about what the maths says
ts = []
for s in range(60):
    c, z = fake(100 + s, 0.0)
    ts.append(evaluate(c, z)["t"])
ts = np.array(ts)
f196, fz = float((abs(ts) >= 1.96).mean()), float((abs(ts) >= Z_CRIT).mean())
ok("noise: |t|>=1.96 about 5% of the time", f196 <= 0.15, f"({f196 * 100:.0f}% of 60 runs)")
ok(f"noise: |t|>={Z_CRIT:.2f} almost never", fz <= 0.04, f"({fz * 100:.0f}% of 60 runs)")
ok("noise: mean t near 0", abs(ts.mean()) < 0.5 and 0.7 < ts.std() < 1.4, f"(mean {ts.mean():+.2f}, sd {ts.std():.2f}; expect ~0 and ~1)")

# 5. sealed data: a series running to 2022 must be cut at the development end
c, z = fake(7, 0.002, n=5200)
ok("fake series really runs past the cut", c.index[-1] > pd.Timestamp(DEV_END))
d = build_xy(c, z)
ok("nothing after 2018-12-31 is used", d.index[-1] <= pd.Timestamp(DEV_END), f"(last row {d.index[-1].date()})")

log("ALL CHECKS PASSED" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
