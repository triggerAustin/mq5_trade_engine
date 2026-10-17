# mq5_trade_engine

A research and automation framework for algorithmic trading on MetaTrader 5 (MT5), built for Linux. It combines a Python backtesting engine, a pre-registered testing process, and a bridge to an MT5 demo account so that strategies are validated offline before any order is placed.

The project is currently in a research and demo-testing phase. No strategy in this repository has passed its out-of-sample test, and nothing here is financial advice or a claim of profitability.

## Goals

- Build an automated trading bot that runs on MetaTrader 5.
- Test strategies honestly: costs are always charged, and pass/fail criteria are written down before results are viewed.
- Keep the whole workflow runnable on a Linux laptop (Fedora, MT5 under Wine) without a Windows VPS.

## Ground rules

1. No live money until a strategy passes a pre-specified out-of-sample test.
2. Transaction costs are always included in every backtest.
3. Pass/fail criteria are fixed before looking at results (pre-registration).
4. Failed strategy families are not tuned until they pass.

## Repository layout

| Path | Purpose |
| --- | --- |
| `mt5bot_v6/` | Main Python project (version 6): backtester, data checks, live-style replay and the MT5 bridge |
| `docs/` | Project documentation: handoff notes and the demo automation plan |
| `mt5linux.sh` | Script for installing MetaTrader 5 on Linux under Wine |
| `mt5setup.exe` | MetaTrader 5 Windows installer used by the Linux setup |
| `webview2.exe` | Microsoft WebView2 runtime installer (optional; the MT5 installer may report a failure here while MT5 itself still works) |

## How it works

**Data.** Research uses Dukascopy hourly bid candles for EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD and XAUUSD, covering 2003 to 2026-09. Daily bars are rebuilt on the 17:00 New York roll, which avoids the spurious Sunday stub bars produced by a fixed 22:00 UTC cut.

**Backtesting.** A Python (numpy, pandas) engine runs pre-registered tests across the market set, with half-sample splits reported alongside full-sample results.

**Live-style replay.** A replay check confirms that the daily signal runner produces the same results as the backtest engine, so the code that trades is the code that was tested.

**Demo automation.** A Python "brain" computes signals and an MQL5 Expert Advisor acts as a file-based bridge to MT5. The design includes safety layers intended to limit downside. This is for testing execution on a demo account only.

## Requirements

- Linux (developed on Fedora)
- Python 3 with numpy and pandas
- MetaTrader 5, installed under Wine
- A broker or MetaQuotes demo account

## Setup

Install MetaTrader 5 on Linux:

```bash
chmod +x mt5linux.sh
./mt5linux.sh
```

Then open MT5, create a demo account, and compile and attach the export-only Expert Advisor (`MT5BotExport.mq5`) to a chart.

Set up the Python side from inside the project directory:

```bash
cd mt5bot_v6
python3 -m venv .venv
source .venv/bin/activate
pip install numpy pandas
```

## Usage

Run these from `mt5bot_v6/`. Exact script locations may differ; check the directory.

```bash
# Validate the rebuilt daily data files
python check_data.py

# Confirm the live-style replay matches the backtest engine on all markets
python check_live.py --all

# Sync data between the Python side and the MT5 EA
python bridge_sync.py
```

## Status

- Pre-registered 8-market daily Donchian 55/20 trend-following test: failed all criteria, including after rebuilding daily bars on the corrected 17:00 New York roll (full-sample Sharpe about -0.06; only gold was profitable).
- Daily mean-reversion and single-pair EURUSD families: rejected earlier.
- Live-style replay: matches the backtest engine on all 8 markets.
- Data limitation: Dukascopy serves completed months only, so recent days need another source, most likely MT5 broker daily bars.
- Next: demo-account trading to test execution (not strategy edge), then at most a small number of further pre-registered tests.

## Disclaimer

This software is for research and education. Trading leveraged instruments carries a high risk of loss. Use demo accounts only unless a strategy has passed its pre-registered test, and even then size positions to losses you can afford.

## License

No license has been specified yet.
