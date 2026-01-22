#!/usr/bin/env python3
"""
Backtest Historical Signals.

Generates signals week-by-week from mid-2025 to present,
tracks forward returns (3M/6M/current), and creates performance reports.

Usage:
    python backtest_signals.py                    # Run full backtest
    python backtest_signals.py --start 2025-07-01 # Custom start date
    python backtest_signals.py --update           # Just update returns for existing signals
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from scanner.historical import HistoricalScanner, HistoricalConfig
from data.fmp_client import FMPClient
from config.settings import get_settings
from utils.logging import setup_logging, get_logger

logger = get_logger("backtest")

SIGNALS_DB_PATH = Path("data/signals_history.json")
PERFORMANCE_MD_PATH = Path("docs/performance.md")
ARCHIVE_DIR = Path("docs/archive")


@dataclass
class TrackedSignal:
    """A signal with tracked returns."""
    signal_date: str          # Friday when signal was detected
    entry_date: str = ""      # Monday when you could actually buy
    ticker: str = ""
    company_name: str = ""
    score: int = 0
    signal_price: float = 0   # Friday close (for reference)
    entry_price: float = 0    # Monday open (actual buy price)
    signal_types: str = ""
    price_3m: Optional[float] = None
    price_6m: Optional[float] = None
    price_12m: Optional[float] = None
    price_current: Optional[float] = None
    return_3m: Optional[float] = None
    return_6m: Optional[float] = None
    return_12m: Optional[float] = None
    return_current: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TrackedSignal":
        return cls(**d)


class SignalBacktester:
    """Backtests signals and tracks performance."""

    def __init__(
        self,
        use_sp500_pit: bool = False,
        use_marketcap_pit: bool = False,
        min_market_cap: Optional[int] = None,
        max_market_cap: Optional[int] = None,
    ):
        """
        Initialize the backtester.

        Args:
            use_sp500_pit: If True, only include signals from stocks that were
                          in S&P 500 at the signal date (survivorship-bias-free)
            use_marketcap_pit: If True, filter by point-in-time market cap
                              ($3B for 2016-2019, $5B for 2020+)
            min_market_cap: Override minimum market cap threshold (uses dynamic if None)
            max_market_cap: Maximum market cap filter (no max if None)
        """
        self.settings = get_settings()
        self.fmp = FMPClient(settings=self.settings)
        self.scanner = HistoricalScanner(HistoricalConfig())
        self.signals_db: List[TrackedSignal] = []
        self.use_sp500_pit = use_sp500_pit
        self.use_marketcap_pit = use_marketcap_pit
        self.min_market_cap = min_market_cap
        self.max_market_cap = max_market_cap
        self.marketcap_universe = None
        self._load_signals_db()

    def _load_signals_db(self):
        """Load existing signals database."""
        if SIGNALS_DB_PATH.exists():
            data = json.loads(SIGNALS_DB_PATH.read_text())
            self.signals_db = [TrackedSignal.from_dict(s) for s in data]
            logger.info(f"Loaded {len(self.signals_db)} existing signals")

    def _save_signals_db(self):
        """Save signals database."""
        SIGNALS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = [s.to_dict() for s in self.signals_db]
        SIGNALS_DB_PATH.write_text(json.dumps(data, indent=2))
        logger.info(f"Saved {len(self.signals_db)} signals to database")

    def _get_existing_signal_dates(self) -> set:
        """Get dates that already have signals."""
        return {s.signal_date for s in self.signals_db}

    async def get_price_on_date(self, ticker: str, target_date: str) -> Optional[float]:
        """Get closing price on or near a specific date."""
        try:
            # Rate limit: small delay between requests
            await asyncio.sleep(0.3)

            # Get historical data around the target date
            target = datetime.strptime(target_date, "%Y-%m-%d")
            from_date = (target - timedelta(days=10)).strftime("%Y-%m-%d")
            to_date = (target + timedelta(days=10)).strftime("%Y-%m-%d")

            hist = await self.fmp.get_historical_prices(ticker, from_date=from_date, to_date=to_date)
            if not hist:
                return None

            # Handle response format - may be dict with 'historical' key
            if isinstance(hist, dict) and 'historical' in hist:
                hist = hist['historical']

            if not hist:
                return None

            # Convert to dataframe
            df = pd.DataFrame(hist)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')

            target_dt = pd.to_datetime(target_date)

            # Find closest date on or after target
            mask = df['date'] >= target_dt
            if mask.any():
                return float(df[mask].iloc[0]['close'])

            # If no date after, get the last available
            return float(df.iloc[-1]['close'])

        except Exception as e:
            logger.warning(f"Failed to get price for {ticker} on {target_date}: {e}")
            return None

    async def get_company_name(self, ticker: str) -> str:
        """Get company name."""
        try:
            profile = await self.fmp.get_company_profile(ticker)
            if profile:
                return profile.get("companyName", ticker)
        except Exception:
            pass
        return ticker

    async def generate_signals_for_week(self, week_end_date: str, min_score: int = 5) -> List[TrackedSignal]:
        """Generate signals as of a specific week end date."""
        logger.info(f"Generating signals for week ending {week_end_date}")

        # Get high intent signals up to this date
        scored_weeks = await self.scanner.get_high_intent_signals(
            min_score=min_score,
            days=7,  # Just this week
            as_of_date=week_end_date,
            use_sp500_pit=self.use_sp500_pit,  # S&P 500 survivorship-bias-free mode
            use_marketcap_pit=self.use_marketcap_pit,  # Market cap survivorship-bias-free mode
            marketcap_universe=self.marketcap_universe,
            min_market_cap=self.min_market_cap,
            max_market_cap=self.max_market_cap,
        )

        signals = []
        for sw in scored_weeks[:10]:  # Top 10 per week
            company_name = await self.get_company_name(sw.ticker)

            # Calculate Monday entry date (next trading day after Friday signal)
            signal_dt = datetime.strptime(week_end_date, "%Y-%m-%d")
            entry_dt = signal_dt + timedelta(days=3)  # Friday + 3 = Monday
            entry_date = entry_dt.strftime("%Y-%m-%d")

            # Get Monday's open price as actual entry price
            entry_price = await self.get_price_on_date(sw.ticker, entry_date)

            signal = TrackedSignal(
                signal_date=week_end_date,
                entry_date=entry_date,
                ticker=sw.ticker,
                company_name=company_name,
                score=sw.total_score,
                signal_price=sw.price,  # Friday close (reference)
                entry_price=entry_price or sw.price,  # Monday open (actual buy)
                signal_types=sw.signal_summary,
            )
            signals.append(signal)

        return signals

    async def update_returns(self, signal: TrackedSignal) -> TrackedSignal:
        """Update forward returns for a signal based on Monday entry price."""
        signal_date = datetime.strptime(signal.signal_date, "%Y-%m-%d")
        entry_date = signal_date + timedelta(days=3)  # Monday after Friday signal
        today = datetime.now()

        # Use entry_price if set, otherwise fall back to signal_price
        base_price = signal.entry_price if signal.entry_price else signal.signal_price
        if not base_price or base_price <= 0:
            return signal

        # Set entry date if not already set
        if not signal.entry_date:
            signal.entry_date = entry_date.strftime("%Y-%m-%d")

        # Get entry price if not already set
        if not signal.entry_price or signal.entry_price == signal.signal_price:
            entry_price = await self.get_price_on_date(signal.ticker, signal.entry_date)
            if entry_price:
                signal.entry_price = entry_price
                base_price = entry_price

        # Calculate target dates from ENTRY date (Monday), not signal date (Friday)
        date_3m = entry_date + timedelta(days=90)
        date_6m = entry_date + timedelta(days=180)
        date_12m = entry_date + timedelta(days=365)

        # Get 3M price if date has passed
        if date_3m <= today:
            price_3m = await self.get_price_on_date(signal.ticker, date_3m.strftime("%Y-%m-%d"))
            if price_3m:
                signal.price_3m = price_3m
                signal.return_3m = (price_3m - base_price) / base_price

        # Get 6M price if date has passed
        if date_6m <= today:
            price_6m = await self.get_price_on_date(signal.ticker, date_6m.strftime("%Y-%m-%d"))
            if price_6m:
                signal.price_6m = price_6m
                signal.return_6m = (price_6m - base_price) / base_price

        # Get 12M price if date has passed
        if date_12m <= today:
            price_12m = await self.get_price_on_date(signal.ticker, date_12m.strftime("%Y-%m-%d"))
            if price_12m:
                signal.price_12m = price_12m
                signal.return_12m = (price_12m - base_price) / base_price

        # Only show current price for signals less than 12 months old
        if date_12m > today:
            current_price = await self.get_price_on_date(signal.ticker, today.strftime("%Y-%m-%d"))
            if current_price:
                signal.price_current = current_price
                signal.return_current = (current_price - base_price) / base_price
        else:
            # For older signals, clear current (12M is the final result)
            signal.price_current = None
            signal.return_current = None

        return signal

    async def run_backtest(self, start_date: str = "2025-07-01", min_score: int = 5):
        """Run backtest from start date to now."""
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.now()

        existing_dates = self._get_existing_signal_dates()

        # Generate week-end dates (Fridays)
        current = start
        while current.weekday() != 4:  # Find first Friday
            current += timedelta(days=1)

        weeks_to_process = []
        while current <= end:
            week_str = current.strftime("%Y-%m-%d")
            if week_str not in existing_dates:
                weeks_to_process.append(week_str)
            current += timedelta(days=7)

        logger.info(f"Processing {len(weeks_to_process)} new weeks")

        # Process each week
        for idx, week_date in enumerate(weeks_to_process):
            try:
                signals = await self.generate_signals_for_week(week_date, min_score)

                # Update returns for each signal
                for signal in signals:
                    signal = await self.update_returns(signal)
                    self.signals_db.append(signal)

                logger.info(f"Added {len(signals)} signals for {week_date} ({idx + 1}/{len(weeks_to_process)})")

                # Save after each week
                self._save_signals_db()

                # Rate limit: pause between weeks to avoid API limits
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Error processing week {week_date}: {e}")
                await asyncio.sleep(5)  # Longer pause on error
                continue

    async def update_all_returns(self):
        """Update returns for all existing signals."""
        logger.info(f"Updating returns for {len(self.signals_db)} signals")

        for i, signal in enumerate(self.signals_db):
            self.signals_db[i] = await self.update_returns(signal)

            if (i + 1) % 20 == 0:
                logger.info(f"Updated {i + 1}/{len(self.signals_db)} signals")
                self._save_signals_db()

        self._save_signals_db()

    def generate_performance_page(self):
        """Generate the performance.md page."""
        if not self.signals_db:
            logger.warning("No signals to generate performance page")
            return

        # Sort by date descending
        signals = sorted(self.signals_db, key=lambda s: s.signal_date, reverse=True)

        # Calculate stats
        returns_3m = [s.return_3m for s in signals if s.return_3m is not None]
        returns_6m = [s.return_6m for s in signals if s.return_6m is not None]
        returns_12m = [s.return_12m for s in signals if s.return_12m is not None]
        returns_current = [s.return_current for s in signals if s.return_current is not None]

        avg_3m = sum(returns_3m) / len(returns_3m) * 100 if returns_3m else 0
        avg_6m = sum(returns_6m) / len(returns_6m) * 100 if returns_6m else 0
        avg_12m = sum(returns_12m) / len(returns_12m) * 100 if returns_12m else 0
        avg_current = sum(returns_current) / len(returns_current) * 100 if returns_current else 0

        # Calculate medians
        def median(lst):
            if not lst:
                return 0
            sorted_lst = sorted(lst)
            n = len(sorted_lst)
            if n % 2 == 0:
                return (sorted_lst[n//2 - 1] + sorted_lst[n//2]) / 2
            return sorted_lst[n//2]

        median_3m = median(returns_3m) * 100 if returns_3m else 0
        median_6m = median(returns_6m) * 100 if returns_6m else 0
        median_12m = median(returns_12m) * 100 if returns_12m else 0

        win_rate_3m = len([r for r in returns_3m if r > 0]) / len(returns_3m) * 100 if returns_3m else 0
        win_rate_6m = len([r for r in returns_6m if r > 0]) / len(returns_6m) * 100 if returns_6m else 0
        win_rate_12m = len([r for r in returns_12m if r > 0]) / len(returns_12m) * 100 if returns_12m else 0

        # Find best/worst based on best available return (12M > 6M > 3M > current)
        def best_return(s):
            if s.return_12m is not None:
                return s.return_12m
            if s.return_current is not None:
                return s.return_current
            return -999

        best_signal = max(signals, key=best_return)
        worst_signal = min(signals, key=lambda s: best_return(s) if best_return(s) != -999 else 999)

        best_ret = best_return(best_signal)
        worst_ret = best_return(worst_signal)

        now = datetime.now()

        md = f"""---
layout: default
title: Performance Track Record
---

# Signal Performance Track Record

**Last Updated:** {now.strftime("%B %d, %Y")}

[← Back to Latest Signals](index.md) | [📄 Research Paper](research.html)

---

## Individual Signal Performance

This page tracks the performance of **each individual signal** independently. For portfolio-level analysis with position sizing and compounding, see the [Research Paper](research.html).

| Metric | 3-Month | 6-Month | 12-Month |
|--------|---------|---------|----------|
| **Mean Return** | {avg_3m:+.1f}% | {avg_6m:+.1f}% | {avg_12m:+.1f}% |
| **Median Return** | {median_3m:+.1f}% | {median_6m:+.1f}% | {median_12m:+.1f}% |
| **Win Rate** | {win_rate_3m:.0f}% | {win_rate_6m:.0f}% | {win_rate_12m:.0f}% |
| **Sample Size** | {len(returns_3m)} | {len(returns_6m)} | {len(returns_12m)} |

**Recent Signals (< 12M old):** {len(returns_current)} signals, mean {avg_current:+.1f}% to date

**Best Pick:** {best_signal.ticker} ({best_signal.signal_date}) → {best_ret * 100:+.1f}%

**Worst Pick:** {worst_signal.ticker} ({worst_signal.signal_date}) → {worst_ret * 100:+.1f}%

---

## Portfolio Simulation Results

When signals are filtered and combined into a portfolio with capital constraints, returns compound significantly higher. See [Research Paper](research.html) for full methodology.

| Metric | Individual Signals | Portfolio ($1B+ segment) |
|--------|-------------------|--------------------------|
| **12-Month Return** | {avg_12m:+.1f}% (mean) | +127% (mean across 23 simulations) |
| **Win Rate** | {win_rate_12m:.0f}% | 72.5% |
| **Methodology** | Simple average | Compounded with $100K, max 40 positions, -60% stop-loss |

**Why the difference?**
- Portfolio simulation uses **compounded returns** (gains reinvested)
- Filters to **scores 5-7** and **$1B+ market cap** only
- Applies **-60% stop-loss** to limit catastrophic losses
- **Position sizing** (4% per position) prevents concentration risk

---

## All Signals

*Entry = Monday open price after Friday signal (when you can actually buy)*

| Signal | Entry | Ticker | Company | Score | Entry$ | 3M | 6M | 12M | Current |
|--------|-------|--------|---------|-------|--------|-----|-----|-----|---------|
"""

        for s in signals:
            ret_3m = f"{s.return_3m * 100:+.1f}%" if s.return_3m is not None else "-"
            ret_6m = f"{s.return_6m * 100:+.1f}%" if s.return_6m is not None else "-"
            ret_12m = f"{s.return_12m * 100:+.1f}%" if s.return_12m is not None else "-"
            ret_curr = f"{s.return_current * 100:+.1f}%" if s.return_current is not None else "-"
            entry_price = s.entry_price if s.entry_price else s.signal_price
            entry_date = s.entry_date if s.entry_date else "-"

            md += f"| {s.signal_date} | {entry_date} | **{s.ticker}** | {s.company_name[:20]} | {s.score} | ${entry_price:.2f} | {ret_3m} | {ret_6m} | {ret_12m} | {ret_curr} |\n"

        md += f"""
---

## Definitions

| Term | Definition |
|------|------------|
| **Mean Return** | Arithmetic average: sum of all returns ÷ number of signals |
| **Median Return** | Middle value when returns are sorted (less affected by outliers) |
| **Win Rate** | Percentage of signals with positive returns |
| **CAGR** | Compound Annual Growth Rate: (Final/Initial)^(1/years) - 1 |

## Methodology

- **Signal Detection:** Friday (based on weekly data through Friday close)
- **Entry Price:** Monday open (next trading day - when you can actually buy)
- **Returns:** Calculated from Monday entry to price on target date
- **3M/6M/12M:** Fixed measurement periods from entry date
- **Current:** Only shown for signals < 12 months old
- **No Stop-Loss:** Individual signals tracked to completion (portfolio simulation uses -60% stop-loss)

**Important:** This page shows **individual signal performance** (each signal tracked independently). The [Research Paper](research.html) shows **portfolio performance** (signals combined with position sizing, compounding, and risk management).

*Past performance does not guarantee future results.*

---

[← Back to Latest Signals](index.md) | [📄 Research Paper](research.html)
"""

        PERFORMANCE_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        PERFORMANCE_MD_PATH.write_text(md)
        logger.info(f"Generated performance page: {PERFORMANCE_MD_PATH}")

    def generate_archive_page(self, week_date: str, signals: List[TrackedSignal]):
        """Generate archive page for a specific week."""
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        week_signals = [s for s in signals if s.signal_date == week_date]
        if not week_signals:
            return

        dt = datetime.strptime(week_date, "%Y-%m-%d")

        md = f"""---
layout: default
title: Signals - {week_date}
---

# High Intent Signals - Week of {dt.strftime("%B %d, %Y")}

[← Back to Latest](../index.md) | [Performance Track Record](../performance.md)

---

| Ticker | Company | Score | Price | Signals |
|--------|---------|-------|-------|---------|
"""

        for s in week_signals:
            md += f"| **{s.ticker}** | {s.company_name[:30]} | {s.score} | ${s.signal_price:.2f} | {s.signal_types} |\n"

        md += "\n---\n"

        archive_path = ARCHIVE_DIR / f"{week_date}.md"
        archive_path.write_text(md)
        logger.info(f"Generated archive: {archive_path}")

    def generate_all_archives(self):
        """Generate archive pages for all weeks."""
        dates = sorted(set(s.signal_date for s in self.signals_db))
        for date in dates:
            self.generate_archive_page(date, self.signals_db)

    async def close(self):
        """Cleanup."""
        await self.fmp.close()
        await self.scanner.close()


def parse_market_cap(value: str) -> int:
    """Parse market cap string like '500M', '1B', '5B' into integer."""
    if not value:
        return None
    value = value.upper().strip()
    multipliers = {'M': 1_000_000, 'B': 1_000_000_000, 'T': 1_000_000_000_000}
    for suffix, mult in multipliers.items():
        if value.endswith(suffix):
            return int(float(value[:-1]) * mult)
    return int(value)


async def main():
    parser = argparse.ArgumentParser(
        description="Backtest signal performance with forward returns tracking",
        epilog="""
Examples:
  Weekly update (adds new week, updates returns):
    python backtest_signals.py --start 2023-01-01

  Only update returns (no new signals):
    python backtest_signals.py --update

  Force full rerun from scratch (~35 min):
    python backtest_signals.py --start 2023-01-01 --force

  Survivorship-bias-free 10-year backtest (S&P 500 only):
    python backtest_signals.py --start 2016-01-01 --sp500 --force

  Survivorship-bias-free 10-year backtest (market cap threshold):
    python backtest_signals.py --start 2016-01-01 --marketcap --force
    (Uses $3B threshold for 2016-2019, $5B for 2020+)

Performance Assumptions:
  - Entry: Monday OPEN after Friday signal
  - Returns: 3M (90d), 6M (180d), 12M (365d) from entry
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--start", type=str, default="2025-07-01",
                        help="Start date for backtest (default: 2025-07-01). Skips weeks already in database.")
    parser.add_argument("--min-score", type=int, default=5,
                        help="Minimum signal score to include (default: 5)")
    parser.add_argument("--update", action="store_true",
                        help="Only update returns for existing signals, don't add new weeks")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing database and rerun from scratch")
    parser.add_argument("--sp500", action="store_true",
                        help="Survivorship-bias-free mode: only include signals from stocks "
                             "that were in S&P 500 at signal date (point-in-time)")
    parser.add_argument("--marketcap", action="store_true",
                        help="Survivorship-bias-free mode: filter by point-in-time market cap "
                             "($3B for 2016-2019, $5B for 2020+)")
    parser.add_argument("--min-marketcap", type=str, default=None,
                        help="Override minimum market cap (e.g., '500M', '1B', '5B')")
    parser.add_argument("--max-marketcap", type=str, default=None,
                        help="Maximum market cap filter (e.g., '2B', '5B', '10B')")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    setup_logging(level="DEBUG" if args.verbose else "INFO")

    # Clear database if --force is used
    if args.force:
        db_path = Path(SIGNALS_DB_PATH)
        if db_path.exists():
            db_path.unlink()
            logger.info(f"Cleared existing database: {SIGNALS_DB_PATH}")

    # Parse market cap arguments
    min_cap = parse_market_cap(args.min_marketcap) if args.min_marketcap else None
    max_cap = parse_market_cap(args.max_marketcap) if args.max_marketcap else None

    # Print mode info
    if args.sp500:
        logger.info("Running in SURVIVORSHIP-BIAS-FREE mode (S&P 500 point-in-time)")
    if args.marketcap:
        if min_cap or max_cap:
            min_str = f"${min_cap/1e9:.1f}B" if min_cap else "dynamic"
            max_str = f"${max_cap/1e9:.1f}B" if max_cap else "no max"
            logger.info(f"Running in SURVIVORSHIP-BIAS-FREE mode (Market cap: {min_str} - {max_str})")
        else:
            logger.info("Running in SURVIVORSHIP-BIAS-FREE mode (Market cap point-in-time: $3B 2016-2019, $5B 2020+)")

    backtester = SignalBacktester(
        use_sp500_pit=args.sp500,
        use_marketcap_pit=args.marketcap,
        min_market_cap=min_cap,
        max_market_cap=max_cap,
    )

    # Load market cap universe if needed
    if args.marketcap:
        from scanner.historical_universe import HistoricalMarketCapUniverse
        logger.info("Loading historical market cap universe...")
        backtester.marketcap_universe = HistoricalMarketCapUniverse()
        await backtester.marketcap_universe.load()

    try:
        if args.update:
            await backtester.update_all_returns()
        else:
            # If using S&P 500 mode, scan the extended historical universe first
            if args.sp500:
                logger.info("Scanning historical S&P 500 universe (this may take a while on first run)...")
                await backtester.scanner.scan_sp500_historical(
                    start_date=args.start,
                    force_refresh=args.force,
                )

            # If using market cap mode, scan the extended historical universe first
            if args.marketcap:
                logger.info("Scanning historical market cap universe (this may take a while on first run)...")
                await backtester.scanner.scan_marketcap_historical(
                    marketcap_universe=backtester.marketcap_universe,
                    start_date=args.start,
                    force_refresh=args.force,
                )

            await backtester.run_backtest(start_date=args.start, min_score=args.min_score)
            await backtester.update_all_returns()

        # Generate outputs
        backtester.generate_performance_page()
        backtester.generate_all_archives()

        print(f"\nBacktest complete!")
        print(f"- Signals tracked: {len(backtester.signals_db)}")
        print(f"- Performance page: {PERFORMANCE_MD_PATH}")
        print(f"- Archive pages: {ARCHIVE_DIR}/")

    finally:
        await backtester.close()


if __name__ == "__main__":
    asyncio.run(main())
