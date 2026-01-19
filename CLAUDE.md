# High Intent Stock Signal Scanner

## Project Overview

A streamlined system that identifies stocks showing high-intent trading signals and synthesizes relevant news into actionable narratives. The scanner runs daily to surface stocks with technical breakouts, unusual volume, or momentum shifts - then uses LLM to explain what's driving the movement.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DAILY SCANNER                                 │
└─────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌───────────────┐        ┌─────────────────┐        ┌─────────────────┐
│ SIGNAL        │        │ NEWS            │        │ NARRATIVE       │
│ DETECTION     │   ──►  │ AGGREGATION     │   ──►  │ SYNTHESIS       │
│ (Python/API)  │        │ (FMP API)       │        │ (LLM)           │
└───────────────┘        └─────────────────┘        └─────────────────┘
```

### Flow

1. **Signal Detection** (no LLM) - Scan for high-intent technical signals
2. **News Aggregation** (no LLM) - Fetch recent news for flagged stocks
3. **Narrative Synthesis** (LLM) - Turn raw news into coherent story

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
├── config/
│   ├── __init__.py
│   ├── settings.py           # Configuration (FMP key, LLM provider)
│   └── sp500_list.py         # S&P 500 ticker list
├── scanner/
│   ├── __init__.py
│   ├── signals.py            # Signal definitions and detection logic
│   └── scanner.py            # Main scanner orchestration
├── synthesis/
│   ├── __init__.py
│   ├── news_synthesizer.py   # LLM-based narrative generation
│   └── prompts/
│       └── news_synthesis.md # Synthesis prompt template
├── data/
│   ├── __init__.py
│   ├── fmp_client.py         # FMP API client
│   └── cache/                # Response caching
├── output/
│   ├── __init__.py
│   └── formatter.py          # JSON/report formatting
├── llm/                      # LLM provider abstraction (kept from original)
│   ├── __init__.py
│   ├── base.py
│   ├── factory.py
│   └── [providers].py
├── utils/
│   ├── __init__.py
│   └── logging.py
├── reports/
│   └── output/               # Daily signal reports
└── main.py                   # Entry point
```

## Output Format

Each daily scan produces a report with:

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
      "narrative": "Apple surged 5.2% on Tuesday, breaking to new all-time highs on triple normal volume. The rally was driven by..."
    }
  ]
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

## Running the Scanner

```bash
# Run daily scan (S&P 500)
python main.py

# Scan specific tickers
python main.py --tickers AAPL,MSFT,GOOGL

# Scan with custom signal thresholds
python main.py --volume-threshold 2.5 --ath-threshold 0.98

# Output to specific file
python main.py --output reports/output/2025-01-19.json
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
- Run scanner at market close (4 PM ET) for best signal detection
- News fetched for last 7 days to capture relevant context

## Cost Estimate

| Component | Cost per Scan |
|-----------|---------------|
| FMP API calls | ~100-200 calls (within free tier limits) |
| LLM synthesis | ~$0.01-0.05 (10-20 stocks × Haiku pricing) |
| **Total** | ~$0.05 per daily scan |

## Future Enhancements

- Email/webhook delivery of daily digest
- Web dashboard for viewing signals
- Historical signal tracking and backtesting
- Sector-specific scanning
- Custom watchlist support
