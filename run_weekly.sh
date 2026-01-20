#!/bin/bash
#
# Weekly Signal Report Generator
# Run this every Friday after market close (or over the weekend)
#
# Usage: ./run_weekly.sh
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
python backtest_signals.py --update

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
