# Data Files Reference

This document describes all data files referenced in the research paper.

## Signal Databases

Located in `data/`:

| File | Description | Signals | Tickers |
|------|-------------|---------|---------|
| `signals_history_1b_2023.json` | $1B+ market cap signals | 1,127 | 570 |
| `signals_history_small_cap.json` | Small-cap ($1B-$5B) signals | 1,564 | 589 |
| `signals_history_micro_small.json` | Micro-small ($500M-$2B) signals | 1,561 | 544 |

### Signal Format

```json
{
  "ticker": "AAPL",
  "signal_date": "2024-01-15",
  "entry_date": "2024-01-17",
  "entry_price": 185.50,
  "score": 6,
  "signals": ["ATH_BREAKOUT", "VOLUME_SPIKE"],
  "return_3m": 0.15,
  "return_6m": 0.25,
  "return_12m": 0.45
}
```

## Monte Carlo Results

Located in `simulation_results/`:

| File | Dataset | Simulations | Generated |
|------|---------|-------------|-----------|
| `monte_carlo_1b_20260121_1956.json` | $1B+ | 23 | 2026-01-21 |
| `monte_carlo_micro-small_20260121_2004.json` | Micro-Small | 23 | 2026-01-21 |
| `monte_carlo_small-cap_20260121_2004.json` | Small-Cap | 23 | 2026-01-21 |

### Monte Carlo Results Format

```json
{
  "generated_at": "2026-01-21T19:56:31",
  "statistics": {
    "num_simulations": 23,
    "date_range": "2023-01-01 to 2025-11-16",
    "total_return": {
      "mean": 1.27,
      "std": 0.82,
      "median": 1.08,
      "min": 0.11,
      "max": 2.46
    },
    "cagr": {...},
    "max_drawdown": {...},
    "win_rate": {...}
  },
  "individual_runs": [...]
}
```

## Trade Lists

Located in project root:

| File | Description | Trades |
|------|-------------|--------|
| `portfolio_trades_1b_60pct.txt` | $1B+ portfolio trades, 12M hold, -60% stop | 88 |
| `portfolio_trades_1b_3M_60pct.txt` | $1B+ portfolio trades, 3M hold, -60% stop | 350 |
| `portfolio_trades_1b_6M_60pct.txt` | $1B+ portfolio trades, 6M hold, -60% stop | 177 |
| `trades_1b_60pct_stoploss.txt` | Individual signal analysis (all 960 signals) | 960 |

### Trade List Format (CSV)

```
Entry Date,Exit Date,Ticker,Score,Entry Price,Exit Price,Shares,Cost,Proceeds,P&L,P&L %,Days Held,Exit Reason
2023-06-14,2024-06-13,SMCI,6,24.78,87.11,161,3990,14025,10035,+251.5%,365,time
```

## Price Data Cache

Located in `data/cache/`:

Historical OHLCV data for all tickers in JSON format:
- `_historical-price-full_{TICKER}_from=2014-01-23_to=2026-01-20.json`

### Price Data Format

```json
{
  "symbol": "AAPL",
  "historical": [
    {
      "date": "2024-01-15",
      "open": 185.50,
      "high": 187.20,
      "low": 184.80,
      "close": 186.90,
      "volume": 45000000
    }
  ]
}
```

## Reproducibility

All results can be reproduced using the following commands:

```bash
# Monte Carlo simulation
python monte_carlo_simulation.py --dataset 1b --stop-loss 0.60
python monte_carlo_simulation.py --dataset micro-small --stop-loss 0.60
python monte_carlo_simulation.py --dataset small-cap --stop-loss 0.60

# Portfolio simulation with trade list
python list_trades.py --dataset 1b --stop-loss 0.60 --holding-period 365
python list_trades.py --dataset 1b --stop-loss 0.60 --holding-period 180
python list_trades.py --dataset 1b --stop-loss 0.60 --holding-period 90

# Individual signal analysis
python strict_portfolio_analyzer.py --dataset 1b --stop-loss 0.60 --print-trades
```

## Key Scripts

| Script | Purpose |
|--------|---------|
| `monte_carlo_simulation.py` | Run Monte Carlo validation across start dates |
| `portfolio_simulator.py` | Full portfolio simulation with position sizing |
| `strict_portfolio_analyzer.py` | Individual signal analysis |
| `list_trades.py` | Generate trade lists with configurable parameters |
| `detailed_drop_analysis.py` | Analyze why signals are dropped |

---

*Generated: January 21, 2026*
