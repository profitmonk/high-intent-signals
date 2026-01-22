# High Intent Stock Signal Scanner

## Project Overview

A streamlined system that identifies stocks showing high-intent trading signals and synthesizes relevant news into actionable narratives. The scanner runs weekly to surface stocks with technical breakouts, unusual volume, or momentum shifts - then uses LLM to explain what's driving the movement.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        WEEKLY SCANNER                                │
└─────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌───────────────┐        ┌─────────────────┐        ┌─────────────────┐
│ SIGNAL        │        │ NEWS            │        │ NARRATIVE       │
│ DETECTION     │   ──►  │ AGGREGATION     │   ──►  │ SYNTHESIS       │
│ (Python/API)  │        │ (FMP API)       │        │ (LLM)           │
└───────────────┘        └─────────────────┘        └─────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PORTFOLIO VISUALIZATION                           │
│  (Chart.js equity curve, drawdowns, monthly returns, holdings)       │
└─────────────────────────────────────────────────────────────────────┘
```

### Flow

1. **Signal Detection** (no LLM) - Scan for high-intent technical signals
2. **News Aggregation** (no LLM) - Fetch recent news for flagged stocks
3. **Narrative Synthesis** (LLM) - Turn raw news into coherent story
4. **Portfolio Simulation** - Backtest signals with position sizing
5. **Visualization** - Generate interactive charts for Jekyll site

## Dataset Options (IMPORTANT)

All scripts default to **$1B+ Market Cap** to match the research paper methodology.

| Dataset | File | Description | CAGR |
|---------|------|-------------|------|
| **`1b`** (default) | `data/signals_history_1b_2023.json` | $1B+ Market Cap | 61.6% |
| `small-cap` | `data/signals_history_small_cap.json` | $1B-$5B | 31.3% |
| `micro-small` | `data/signals_history_micro_small.json` | $500M-$2B | 35.4% |

**Usage:**
```bash
# All scripts default to $1B+ dataset
python portfolio_simulator.py                    # Uses 1b
python generate_portfolio_data.py                # Uses 1b
python portfolio_simulator.py --dataset small-cap    # Override
python generate_portfolio_data.py --dataset micro-small
```

## High Intent Signals

| Signal | Detection Method | Why It Matters |
|--------|------------------|----------------|
| **ATH Breakout** | Price > 95% of 52-week high | No overhead resistance, new price discovery |
| **Volume Spike** | Volume > 2x 20-day average | Institutional activity |
| **Gap Up** | Open > 5% above prior close on high volume | News/catalyst driving real buying |
| **Trend Reversal** | Price crosses above 50-SMA after being below | Accumulation phase starting |
| **Momentum** | In top gainers list | Active buying pressure |

## Data Source

**Financial Modeling Prep API** - Single data source for simplicity:

```
# Signal Detection
/stable/biggest-gainers          # Today's biggest movers
/stable/most-actives             # Highest volume stocks
/api/v3/quote/{symbol}           # Price, 52wk high/low, volume
/stable/technical-indicators/sma # Moving averages

# News
/stable/news/stock?symbols=AAPL  # Stock-specific news
```

## Directory Structure

```
sp500-scanner/
├── CLAUDE.md                 # This file
├── requirements.txt          # Python dependencies
├── .env                      # API keys (gitignored)
├── run_weekly.sh             # Weekly update script (run every Friday)
│
├── config/
│   ├── settings.py           # Configuration (FMP key, LLM provider)
│   └── sp500_list.py         # S&P 500 ticker list
│
├── scanner/
│   ├── signals.py            # Signal definitions and detection logic
│   ├── scanner.py            # Main scanner orchestration
│   ├── historical.py         # Historical signal scanning
│   └── historical_universe.py # Market cap universe management
│
├── data/
│   ├── fmp_client.py         # FMP API client
│   ├── signals_history_1b_2023.json      # $1B+ signals (DEFAULT)
│   ├── signals_history_small_cap.json    # $1B-$5B signals
│   ├── signals_history_micro_small.json  # $500M-$2B signals
│   └── cache/                # Response caching + price history
│
├── synthesis/
│   ├── news_synthesizer.py   # LLM-based narrative generation
│   └── prompts/
│       └── news_synthesis.md # Synthesis prompt template
│
├── llm/                      # LLM provider abstraction
│   ├── base.py
│   ├── factory.py
│   └── [providers].py
│
├── docs/                     # Jekyll GitHub Pages site
│   ├── _config.yml           # Jekyll config
│   ├── _data/
│   │   └── portfolio_state.json  # Generated portfolio data
│   ├── index.md              # This week's signals
│   ├── performance.md        # Return tracking table
│   ├── portfolio.md          # Interactive charts (Chart.js)
│   ├── research.md           # Monte Carlo analysis
│   ├── archive/              # Historical weekly reports
│   └── assets/
│       ├── css/
│       │   ├── style.scss    # Main styles
│       │   └── portfolio.css # Portfolio page styles
│       └── js/
│           └── portfolio-charts.js  # Chart.js visualizations
│
├── generate_report.py        # Weekly signal report generator
├── generate_portfolio_data.py # Portfolio visualization data generator
├── portfolio_simulator.py    # Backtest simulator
├── backtest_signals.py       # Historical signal backtesting
├── monte_carlo_simulation.py # Monte Carlo analysis
└── main.py                   # Entry point
```

## Weekly Update Workflow

Run `./run_weekly.sh` every Friday after market close:

```bash
./run_weekly.sh
```

This script:
1. **Generates weekly signals** with news synthesis → `docs/index.md`
2. **Updates return tracking** (3M/6M/12M) → `docs/performance.md`, `docs/archive/`
3. **Generates portfolio data** → `docs/_data/portfolio_state.json`
4. **Commits and pushes** to GitHub Pages

## Key Scripts

### generate_report.py
Generates this week's signals with LLM news synthesis.
```bash
python generate_report.py --min-score 5 --limit 20
```

### backtest_signals.py
Updates historical returns for all signals.
```bash
python backtest_signals.py --start 2023-01-01     # Add new + update returns
python backtest_signals.py --update               # Only update returns
python backtest_signals.py --start 2023-01-01 --force  # Full rebuild
```

### generate_portfolio_data.py
Generates JSON data for portfolio visualization.
```bash
python generate_portfolio_data.py                 # $1B+ dataset (default)
python generate_portfolio_data.py --dataset small-cap
python generate_portfolio_data.py --stop-loss 0.50 --min-score 6
```

### portfolio_simulator.py
Runs backtest simulations with various strategies.
```bash
python portfolio_simulator.py                     # Default strategies
python portfolio_simulator.py --dataset 1b        # Explicit dataset
python portfolio_simulator.py --rolling           # Rolling start analysis
```

## Portfolio Simulation Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Dataset | `1b` | $1B+ market cap signals |
| Stop Loss | 60% | Exit if position drops 60% |
| Holding Period | 365 days | 12-month hold |
| Score Range | 5-7 | Moderate conviction signals |
| Max Position | 4% | Per-position size limit |
| Max Positions | 40 | Portfolio concentration limit |

## Output Format

Each weekly scan produces a report with:

```json
{
  "scan_date": "2025-01-19",
  "signals_detected": 12,
  "stocks": [
    {
      "ticker": "AAPL",
      "company": "Apple Inc.",
      "signals": ["ATH_BREAKOUT", "VOLUME_SPIKE"],
      "price": 245.50,
      "change_pct": 5.2,
      "volume_vs_avg": 3.1,
      "distance_to_52wk_high_pct": 0.5,
      "narrative": "Apple surged 5.2% on Tuesday..."
    }
  ]
}
```

## Portfolio Visualization Data

`docs/_data/portfolio_state.json` contains:

```json
{
  "generated_at": "2026-01-22T...",
  "dataset": "$1B+ Market Cap",
  "summary_metrics": {
    "final_value": 346080,
    "total_return": 2.461,
    "cagr": 0.616,
    "max_drawdown": 0.246,
    "sharpe_ratio": 1.63,
    "sortino_ratio": 1.74,
    "win_rate": 0.693
  },
  "equity_curve": [...],
  "drawdown_series": [...],
  "monthly_returns": [...],
  "current_holdings": [...],
  "closed_positions": [...]
}
```

## API Keys Required

Store in `.env` file:

```
# Required
FMP_API_KEY=your_financial_modeling_prep_key

# For narrative synthesis (one of these)
LLM_PROVIDER=anthropic  # or openai, gemini, ollama
ANTHROPIC_API_KEY=your_key
OPENAI_API_KEY=your_key
GEMINI_API_KEY=your_key
```

## Signal Thresholds (Configurable)

| Signal | Default Threshold |
|--------|-------------------|
| ATH proximity | > 95% of 52-week high |
| Volume spike | > 2x 20-day average |
| Gap up | > 5% from prior close |
| Daily gain | > 3% |

## LLM Usage

**Single use case:** Synthesizing news into narrative

- Input: Stock ticker, signals detected, 5-10 recent news articles
- Output: 2-3 paragraph narrative explaining the movement
- Model: Fast model (Haiku/GPT-4o-mini) - doesn't need deep reasoning

## Development Notes

- Use `asyncio` for parallel API calls
- Cache FMP responses for 1 hour (avoid redundant calls during same scan)
- Run scanner at market close (4 PM ET Friday) for best signal detection
- News fetched for last 7 days to capture relevant context
- **Always use `--dataset 1b`** (or default) for research-consistent results

## GitHub Pages Site

The site is deployed at: https://profitmonk.github.io/high-intent-signals/

| Page | Description |
|------|-------------|
| `index.html` | This week's signals with news |
| `portfolio.html` | Interactive equity curve, drawdowns, holdings |
| `performance.html` | All-time return tracking table |
| `research.html` | Monte Carlo analysis methodology |
| `archive/` | Historical weekly reports |

## Cost Estimate

| Component | Cost per Scan |
|-----------|---------------|
| FMP API calls | ~100-200 calls (within free tier limits) |
| LLM synthesis | ~$0.01-0.05 (10-20 stocks × Haiku pricing) |
| **Total** | ~$0.05 per weekly scan |
