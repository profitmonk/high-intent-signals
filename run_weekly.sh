#!/bin/bash
#
# Weekly Signal Report Generator
# Run this every Friday after market close (or over the weekend)
#
# Usage: ./run_weekly.sh
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
# =============================================================================
#

set -e  # Exit on error

echo "=========================================="
echo "High Intent Signal Scanner - Weekly Update"
echo "=========================================="
echo ""

cd "$(dirname "$0")"

# 1. Generate this week's report with news synthesis
echo "[1/4] Generating weekly report with news synthesis..."
python generate_report.py --min-score 5 --limit 20

# 2. Update backtest (adds new week + updates all returns)
echo ""
echo "[2/4] Updating performance tracking (this may take a few minutes)..."
python backtest_signals.py --start 2023-01-01

# 3. Stage all changes
echo ""
echo "[3/4] Staging changes..."
git add docs/
git add data/signals_history.json

# 4. Commit and push
echo ""
echo "[4/4] Committing and pushing to GitHub..."
WEEK_DATE=$(date +%Y-%m-%d)
git commit -m "Weekly update - ${WEEK_DATE}" || echo "No changes to commit"
git push || echo "Push failed - check your git credentials"

echo ""
echo "=========================================="
echo "Done! Check your site at:"
echo "https://profitmonk.github.io/high-intent-signals/"
echo "=========================================="
