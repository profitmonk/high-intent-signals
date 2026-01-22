# High Intent Stock Signals - GitHub Pages

This folder contains the auto-generated signal reports for GitHub Pages.

**Live Site:** https://profitmonk.github.io/high-intent-signals/

## Pages

| Page | Description |
|------|-------------|
| `index.md` | This week's signals with news synthesis |
| `portfolio.md` | Interactive portfolio visualization (Chart.js) |
| `performance.md` | Return tracking table (3M/6M/12M) |
| `research.md` | Monte Carlo analysis methodology |
| `archive/` | Historical weekly signal reports |

## Dataset (IMPORTANT)

All scripts default to **$1B+ Market Cap** to match the research paper.

| Dataset | CAGR | Description |
|---------|------|-------------|
| **`1b`** (default) | 61.6% | $1B+ Market Cap |
| `small-cap` | 31.3% | $1B-$5B |
| `micro-small` | 35.4% | $500M-$2B |

## Setup Instructions

### 1. Initialize Git Repository (if not already)

```bash
git init
git add .
git commit -m "Initial commit with high intent scanner"
```

### 2. Push to GitHub

```bash
# Create a new repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

### 3. Enable GitHub Pages

1. Go to your repository on GitHub
2. Click **Settings** (top menu)
3. Click **Pages** (left sidebar)
4. Under "Source", select:
   - **Branch:** `main`
   - **Folder:** `/docs`
5. Click **Save**

Your site will be live at: `https://YOUR_USERNAME.github.io/YOUR_REPO/`

## Weekly Update (Recommended)

Run this every Friday after market close:

```bash
./run_weekly.sh
```

This script:
1. Generates this week's signal report with news synthesis → `docs/index.md`
2. Updates return tracking (3M/6M/12M) → `docs/performance.md`, `docs/archive/`
3. Generates portfolio visualization data → `docs/_data/portfolio_state.json`
4. Commits and pushes to GitHub

## Generating Reports

```bash
# Generate today's report
python generate_report.py

# Custom options
python generate_report.py --min-score 5 --limit 20 --days 30
```

## Portfolio Visualization

```bash
# Generate portfolio data (uses $1B+ by default)
python generate_portfolio_data.py

# Use different dataset
python generate_portfolio_data.py --dataset small-cap

# Custom parameters
python generate_portfolio_data.py --stop-loss 0.50 --min-score 6
```

Output: `docs/_data/portfolio_state.json` - consumed by `portfolio.md` with Chart.js.

## Performance Tracking (Backtest)

### Backtest Options

```bash
# 1. WEEKLY UPDATE (adds new week, updates returns - skips existing weeks)
python backtest_signals.py --start 2023-01-01

# 2. ONLY UPDATE RETURNS (no new signals)
python backtest_signals.py --update

# 3. FORCE FULL RERUN (deletes database, rebuilds from scratch ~35 min)
python backtest_signals.py --start 2023-01-01 --force
```

### Performance Assumptions

| Step | Description |
|------|-------------|
| **Signal** | Detected Friday at market close |
| **Entry** | Monday OPEN price (next trading day) |
| **3M Return** | Price at 90 days vs entry |
| **6M Return** | Price at 180 days vs entry |
| **12M Return** | Price at 365 days vs entry |
| **Current** | Only shown for signals < 12 months old |

## Local Preview

```bash
cd docs
python -m http.server 8000
# Open http://localhost:8000
```

## Directory Structure

```
docs/
├── _config.yml           # Jekyll configuration
├── _data/
│   └── portfolio_state.json  # Generated portfolio data
├── index.md              # This week's signals
├── portfolio.md          # Interactive charts
├── performance.md        # Return tracking
├── research.md           # Monte Carlo paper
├── archive/              # Historical reports
│   └── YYYY-MM-DD.md
└── assets/
    ├── css/
    │   ├── style.scss    # Main styles
    │   └── portfolio.css # Portfolio page styles
    └── js/
        └── portfolio-charts.js  # Chart.js code
```

## Automation (Optional)

Add a GitHub Action to auto-generate weekly reports:

Create `.github/workflows/weekly-report.yml`:

```yaml
name: Weekly Signal Report

on:
  schedule:
    - cron: '0 22 * * 5'  # 10 PM UTC, Friday (after market close)
  workflow_dispatch:  # Manual trigger

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Generate weekly report
        env:
          FMP_API_KEY: ${{ secrets.FMP_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python generate_report.py --min-score 5 --limit 20
          python backtest_signals.py --start 2023-01-01
          python generate_portfolio_data.py

      - name: Commit and push
        run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
          git add docs/
          git add data/signals_history_1b_2023.json
          git commit -m "Weekly update - $(date +%Y-%m-%d)" || exit 0
          git push
```

Then add `FMP_API_KEY` and `ANTHROPIC_API_KEY` to your repository secrets.
