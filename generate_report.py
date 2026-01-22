#!/usr/bin/env python3
"""
Generate High Intent Report for GitHub Pages.

Fetches high-intent signals, synthesizes news, and outputs Markdown
with source links for publishing to GitHub Pages.

Usage:
    python generate_report.py                    # Generate today's report
    python generate_report.py --days 7           # Signals from last 7 days
    python generate_report.py --min-score 5      # Higher threshold
    python generate_report.py --dry-run          # Preview without saving
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))

from scanner.historical import HistoricalScanner, HistoricalConfig, ScoredStockWeek
from data.fmp_client import FMPClient
from synthesis.news_synthesizer import NewsSynthesizer
from config.settings import get_settings
from utils.logging import setup_logging, get_logger

logger = get_logger("report_generator")


class ReportGenerator:
    """Generates high-intent signal reports with news synthesis."""

    def __init__(self, min_score: int = 4, days: int = 30):
        self.min_score = min_score
        self.days = days
        self.settings = get_settings()
        self.fmp = FMPClient(settings=self.settings)
        self.synthesizer = NewsSynthesizer(settings=self.settings)
        self.scanner = HistoricalScanner(HistoricalConfig())

    async def fetch_signals(self) -> List[ScoredStockWeek]:
        """Fetch high-intent signals."""
        signals = await self.scanner.scan_universe(force_refresh=False)
        scored = await self.scanner.get_high_intent_signals(
            min_score=self.min_score,
            days=self.days,
        )
        return scored

    async def fetch_news_for_stock(self, ticker: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch recent news for a stock."""
        try:
            news = await self.fmp.get_news(ticker, limit=limit)
            return news or []
        except Exception as e:
            logger.warning(f"Failed to fetch news for {ticker}: {e}")
            return []

    async def synthesize_narrative(
        self,
        ticker: str,
        company_name: str,
        scored_week: ScoredStockWeek,
        news: List[Dict[str, Any]],
    ) -> str:
        """Generate narrative for a stock."""
        signal_details = [
            {"type": sig.signal_type, "strength": sig.strength, "description": sig.description}
            for sig in scored_week.signals
        ]

        narrative = await self.synthesizer.synthesize(
            ticker=ticker,
            company_name=company_name,
            price=scored_week.price,
            change_pct=scored_week.change_pct or 0,
            signals=[sig.signal_type for sig in scored_week.signals],
            signal_details=signal_details,
            news=news,
        )
        return narrative

    async def get_company_name(self, ticker: str) -> str:
        """Get company name from profile."""
        try:
            profile = await self.fmp.get_company_profile(ticker)
            if profile:
                return profile.get("companyName", ticker)
        except Exception:
            pass
        return ticker

    async def generate_stock_section(
        self,
        scored_week: ScoredStockWeek,
        rank: int,
    ) -> str:
        """Generate markdown section for a single stock."""
        ticker = scored_week.ticker

        # Fetch company name and news in parallel
        company_name, news = await asyncio.gather(
            self.get_company_name(ticker),
            self.fetch_news_for_stock(ticker, limit=5),
        )

        # Generate narrative
        narrative = await self.synthesize_narrative(
            ticker, company_name, scored_week, news
        )

        # Format change
        change_str = f"+{scored_week.change_pct * 100:.1f}%" if scored_week.change_pct and scored_week.change_pct > 0 else f"{scored_week.change_pct * 100:.1f}%" if scored_week.change_pct else "N/A"

        # Build markdown
        md = f"""### {rank}. {ticker} - {company_name}

**Score:** {scored_week.total_score} | **Price:** ${scored_week.price:.2f} | **Change:** {change_str} | **Date:** {scored_week.date}

**Signals:** {scored_week.signal_summary}{"  *(+confluence)*" if scored_week.has_confluence else ""}

{narrative}

"""
        # Add source links
        if news:
            md += "**Sources:**\n"
            for article in news[:3]:
                title = article.get("title", "News")
                url = article.get("url", "")
                site = article.get("site", "")
                if url:
                    # Escape special characters in URL that break markdown
                    url_escaped = url.replace("|", "%7C").replace("(", "%28").replace(")", "%29")
                    # Escape brackets in title
                    title_escaped = title.replace("[", "\\[").replace("]", "\\]")
                    md += f"- [{title_escaped}]({url_escaped}) *({site})*\n"
            md += "\n"

        md += "---\n\n"
        return md

    async def generate_report(self, limit: int = 20) -> str:
        """Generate the full report."""
        logger.info(f"Fetching high-intent signals (score >= {self.min_score}, last {self.days} days)")

        scored_weeks = await self.fetch_signals()

        if not scored_weeks:
            return self._generate_empty_report()

        # Limit to top N
        scored_weeks = scored_weeks[:limit]

        # Generate header
        now = datetime.now()
        report = f"""---
layout: default
title: High Intent Signals
---

# High Intent Stock Signals

**Generated:** {now.strftime("%B %d, %Y at %I:%M %p")}

<div style="background: linear-gradient(135deg, #1a472a 0%, #2d5a3d 100%); border-radius: 8px; padding: 16px 20px; margin: 20px 0;">
<strong style="font-size: 1.1em;">📊 <a href="performance.html" style="color: #4ade80;">View Performance Track Record →</a></strong>
<p style="margin: 8px 0 0 0; color: #9ca3af; font-size: 0.9em;">See historical returns: 3M, 6M, and current performance for all signals</p>
</div>

**Criteria:** Score >= {self.min_score} | Last {self.days} days | {len(scored_weeks)} signals

| [📈 Performance](performance.html) | [📁 Archive](archive/) |

---

## Scoring System

| Signal | Points |
|--------|--------|
| New 52-week High (breakout) | 3 |
| Volume >= 5x average | 3 |
| Volume >= 3x average | 2 |
| Momentum >= 15% weekly | 2 |
| Momentum 10-15% weekly | 1 |
| SMA200 crossover | 2 |
| SMA50 crossover | 1 |
| Confluence bonus (2+ types) | +1 |

---

## Top Signals

"""
        # Generate sections for each stock
        for i, sw in enumerate(scored_weeks, 1):
            logger.info(f"Processing {i}/{len(scored_weeks)}: {sw.ticker}")
            section = await self.generate_stock_section(sw, i)
            report += section

        # Add footer
        report += f"""
## About

This report is auto-generated by the [High Intent Stock Scanner](https://github.com/profitmonk/high-intent-signals).

Signals are detected using technical analysis:
- **ATH Breakout**: Stock breaking to new 52-week highs
- **Volume Spike**: Unusual trading volume (3-5x+ average)
- **Momentum**: Strong weekly price gains (10-15%+)
- **SMA Crossover**: Price crossing above key moving averages

*Not financial advice. Do your own research.*

---

*Last updated: {now.strftime("%Y-%m-%d %H:%M:%S")}*
"""
        return report

    def _generate_empty_report(self) -> str:
        """Generate report when no signals found."""
        now = datetime.now()
        return f"""---
layout: default
title: High Intent Signals
---

# High Intent Stock Signals

**Generated:** {now.strftime("%B %d, %Y at %I:%M %p")}

No high-intent signals found matching criteria (score >= {self.min_score}, last {self.days} days).

Check back later or lower the minimum score threshold.
"""

    async def close(self):
        """Clean up resources."""
        await self.fmp.close()
        await self.scanner.close()


async def main():
    parser = argparse.ArgumentParser(description="Generate high-intent signal report")
    parser.add_argument("--min-score", type=int, default=5, help="Minimum score threshold (default: 5)")
    parser.add_argument("--days", type=int, default=30, help="Days to look back (default: 30)")
    parser.add_argument("--limit", type=int, default=20, help="Max stocks to include (default: 20)")
    parser.add_argument("--output", type=str, default="docs/index.md", help="Output file path")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of saving")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    setup_logging(level="DEBUG" if args.verbose else "INFO")

    generator = ReportGenerator(min_score=args.min_score, days=args.days)

    try:
        report = await generator.generate_report(limit=args.limit)

        if args.dry_run:
            print(report)
        else:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report)
            print(f"Report saved to {output_path}")
            print(f"To view locally: cd docs && python -m http.server 8000")

    finally:
        await generator.close()


if __name__ == "__main__":
    asyncio.run(main())
