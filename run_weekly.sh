#!/bin/bash
#
# Weekly Signal Report Generator
# Run this every Friday after market close (or over the weekend)
#
# Usage: ./run_weekly.sh
#
# =============================================================================
# WHAT THIS SCRIPT DOES:
# =============================================================================
# 1. Generate this week's signals with news synthesis (docs/index.md)
# 2. Update backtest returns for all historical signals
# 3. Generate portfolio visualization data (docs/_data/portfolio_state.json)
# 4. Commit and push all changes to GitHub
#
# =============================================================================
# DATASET: $1B+ Market Cap (default)
# =============================================================================
# All scripts now default to $1B+ market cap universe to match research paper.
# To use different datasets, run scripts manually with --dataset flag:
#   python backtest_signals.py --dataset small-cap
#   python generate_portfolio_data.py --dataset micro-small
#
# =============================================================================
# BACKTEST OPTIONS (for manual runs):
# =============================================================================
#
# 1. WEEKLY UPDATE (default - what this script does):
#    python backtest_signals.py --start 2023-01-01
#    - Adds new week's signals (skips existing weeks)
#    - Updates 3M/6M/12M returns for all signals
#    - Regenerates performance.md and archive pages
#
# 2. ONLY UPDATE RETURNS (no new signals):
#    python backtest_signals.py --update
#    - Recalculates returns for existing signals only
#    - Use when you just want fresh return numbers
#
# 3. FORCE FULL RERUN (nuclear option):
#    python backtest_signals.py --start 2023-01-01 --force
#    - Deletes existing database and rebuilds from scratch
#    - Takes ~35 minutes for 3 years of data
#    - Only use if data is corrupted or you changed signal logic
#
# =============================================================================
# PERFORMANCE ASSUMPTIONS:
# =============================================================================
# - Signal detected: Friday at market close
# - Entry price: Monday OPEN (next trading day)
# - Returns: Calculated at 3M (90 days), 6M (180 days), 12M (365 days)
# - Recent signals (<12M old): Also show current return
# - Stop loss: 60% (matching research methodology)
# =============================================================================
#

set -e  # Exit on error

echo "=========================================="
echo "High Intent Signal Scanner - Weekly Update"
echo "Dataset: \$1B+ Market Cap"
echo "=========================================="
echo ""

cd "$(dirname "$0")"

# 1. Generate this week's report with news synthesis
echo "[1/5] Generating weekly report with news synthesis..."
python generate_report.py --min-score 5 --limit 20
echo "      -> Created docs/index.md"

# 2. Update backtest (adds new week + updates all returns)
echo ""
echo "[2/5] Updating performance tracking (this may take a few minutes)..."
python backtest_signals.py --start 2023-01-01
echo "      -> Updated docs/performance.md"
echo "      -> Updated docs/archive/*.md"
echo "      -> Updated data/signals_history_1b_2023.json"

# 3. Generate portfolio visualization data
echo ""
echo "[3/5] Generating portfolio visualization data..."
python generate_portfolio_data.py
echo "      -> Created docs/_data/portfolio_state.json"

# 4. Stage all changes
echo ""
echo "[4/5] Staging changes..."
git add docs/
git add data/signals_history_1b_2023.json

# Show what's being committed
echo ""
echo "Files staged for commit:"
git diff --cached --stat || true

# 5. Commit and push
echo ""
echo "[5/5] Committing and pushing to GitHub..."
WEEK_DATE=$(date +%Y-%m-%d)
git commit -m "Weekly update - ${WEEK_DATE}

- Updated signals and news synthesis
- Refreshed performance returns (3M/6M/12M)
- Regenerated portfolio visualization data" || echo "No changes to commit"

git push || echo "Push failed - check your git credentials"

echo ""
echo "=========================================="
echo "Done! Check your site at:"
echo "https://profitmonk.github.io/high-intent-signals/"
echo ""
echo "Pages updated:"
echo "  - index.html (this week's signals)"
echo "  - performance.html (return tracking)"
echo "  - portfolio.html (interactive charts)"
echo "  - archive/ (historical signals)"
echo "=========================================="
