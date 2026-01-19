# High Intent Stock Signals - GitHub Pages

This folder contains the auto-generated signal reports for GitHub Pages.

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

## Generating Reports

```bash
# Generate today's report
python generate_report.py

# Custom options
python generate_report.py --min-score 5 --limit 20 --days 30
```

## Local Preview

```bash
cd docs
python -m http.server 8000
# Open http://localhost:8000
```

## Automation (Optional)

Add a GitHub Action to auto-generate daily reports:

Create `.github/workflows/daily-report.yml`:

```yaml
name: Daily Signal Report

on:
  schedule:
    - cron: '0 22 * * 1-5'  # 10 PM UTC, Mon-Fri (after market close)
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

      - name: Generate report
        env:
          FMP_API_KEY: ${{ secrets.FMP_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python generate_report.py --min-score 5 --limit 20

      - name: Commit and push
        run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
          git add docs/
          git commit -m "Update daily signal report" || exit 0
          git push
```

Then add `FMP_API_KEY` and `ANTHROPIC_API_KEY` to your repository secrets.
