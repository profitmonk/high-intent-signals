"""
Point-in-time S&P 500 universe reconstruction for survivorship-bias-free backtesting.

This module provides functions to reconstruct what the S&P 500 looked like
at any historical date, avoiding survivorship bias.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from data.fmp_client import FMPClient

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache")


@dataclass
class UniverseStats:
    """Statistics about the reconstructed universe."""
    target_date: str
    total_members: int
    members_with_data: int
    members_missing_data: int
    missing_tickers: List[str]


class SP500Universe:
    """
    Manages point-in-time S&P 500 membership reconstruction.

    Uses historical constituent changes to determine which stocks
    were in the S&P 500 at any given historical date.
    """

    def __init__(self):
        self.fmp = FMPClient()
        self._current_members: Optional[Set[str]] = None
        self._changes: Optional[List[Dict]] = None
        self._changes_cache_file = CACHE_DIR / "sp500_changes.json"
        self._members_cache_file = CACHE_DIR / "sp500_current_members.json"

    async def load(self, force_refresh: bool = False) -> None:
        """Load S&P 500 data (current members and historical changes)."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Check cache freshness (refresh weekly)
        cache_valid = False
        if not force_refresh and self._changes_cache_file.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(
                self._changes_cache_file.stat().st_mtime
            )
            cache_valid = cache_age < timedelta(days=7)

        if cache_valid:
            logger.info("Loading S&P 500 data from cache...")
            with open(self._changes_cache_file) as f:
                self._changes = json.load(f)
            with open(self._members_cache_file) as f:
                self._current_members = set(json.load(f))
        else:
            logger.info("Fetching S&P 500 data from API...")

            # Fetch current members and changes in parallel
            current_raw, changes_raw = await asyncio.gather(
                self.fmp.get_sp500_constituents(),
                self.fmp.get_historical_sp500_constituents(),
            )

            self._current_members = {c['symbol'] for c in current_raw if c.get('symbol')}
            self._changes = changes_raw

            # Cache
            with open(self._changes_cache_file, 'w') as f:
                json.dump(self._changes, f)
            with open(self._members_cache_file, 'w') as f:
                json.dump(list(self._current_members), f)

        logger.info(f"Loaded {len(self._current_members)} current members, "
                    f"{len(self._changes)} historical changes")

    def get_members_on_date(self, target_date: str) -> Set[str]:
        """
        Reconstruct S&P 500 membership as of a specific date.

        Args:
            target_date: Date in YYYY-MM-DD format

        Returns:
            Set of ticker symbols that were in S&P 500 on that date
        """
        if self._current_members is None or self._changes is None:
            raise RuntimeError("Call load() first")

        # Start with current members
        members = set(self._current_members)

        # Process changes in reverse chronological order
        # For each change that happened AFTER target_date, reverse it
        for change in self._changes:
            change_date = change.get('date', '')

            if not change_date or change_date <= target_date:
                continue  # This change had already happened by target_date

            # This change happened AFTER target_date, so reverse it
            added_ticker = change.get('symbol', '')
            removed_ticker = change.get('removedTicker', '')

            # Reverse: remove the stock that was added after target_date
            if added_ticker:
                members.discard(added_ticker)

            # Reverse: add back the stock that was removed after target_date
            if removed_ticker:
                members.add(removed_ticker)

        return members

    async def get_members_with_data(
        self,
        target_date: str,
        check_price_availability: bool = True,
    ) -> Tuple[Set[str], UniverseStats]:
        """
        Get S&P 500 members on a date, filtered to those with price data.

        Args:
            target_date: Date in YYYY-MM-DD format
            check_price_availability: If True, verify each stock has price data

        Returns:
            Tuple of (set of valid tickers, statistics)
        """
        members = self.get_members_on_date(target_date)

        if not check_price_availability:
            stats = UniverseStats(
                target_date=target_date,
                total_members=len(members),
                members_with_data=len(members),
                members_missing_data=0,
                missing_tickers=[],
            )
            return members, stats

        # Check which stocks have price data around target_date
        valid_members = set()
        missing_tickers = []

        # Check in batches to avoid overwhelming the API
        members_list = list(members)
        batch_size = 20

        for i in range(0, len(members_list), batch_size):
            batch = members_list[i:i + batch_size]

            tasks = [
                self._check_price_data(ticker, target_date)
                for ticker in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for ticker, result in zip(batch, results):
                if isinstance(result, Exception):
                    missing_tickers.append(ticker)
                elif result:
                    valid_members.add(ticker)
                else:
                    missing_tickers.append(ticker)

            # Small delay between batches
            if i + batch_size < len(members_list):
                await asyncio.sleep(0.5)

        stats = UniverseStats(
            target_date=target_date,
            total_members=len(members),
            members_with_data=len(valid_members),
            members_missing_data=len(missing_tickers),
            missing_tickers=missing_tickers,
        )

        if missing_tickers:
            logger.warning(f"Missing price data for {len(missing_tickers)} stocks on {target_date}: "
                          f"{missing_tickers[:10]}{'...' if len(missing_tickers) > 10 else ''}")

        return valid_members, stats

    async def _check_price_data(self, ticker: str, target_date: str) -> bool:
        """Check if a stock has price data around the target date."""
        try:
            # Check for data in a window around the target date
            start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
            end = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")

            data = await self.fmp.get_historical_prices(ticker, start, end)

            if data and 'historical' in data and len(data['historical']) > 0:
                return True
            return False
        except Exception:
            return False

    def get_all_historical_members(self, start_date: str, end_date: str) -> Set[str]:
        """
        Get all stocks that were in S&P 500 at any point in the date range.

        Useful for pre-downloading all necessary price data.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Set of all tickers that were ever in S&P 500 during the period
        """
        if self._current_members is None or self._changes is None:
            raise RuntimeError("Call load() first")

        # Start with current members
        all_members = set(self._current_members)

        # Add any stock that was removed during or after the period
        for change in self._changes:
            change_date = change.get('date', '')
            removed_ticker = change.get('removedTicker', '')

            if removed_ticker and change_date >= start_date:
                all_members.add(removed_ticker)

        return all_members

    async def close(self):
        """Clean up resources."""
        await self.fmp.close()


async def test_universe():
    """Test the universe reconstruction."""
    universe = SP500Universe()
    await universe.load()

    # Test a few dates
    test_dates = [
        "2026-01-15",  # Recent
        "2024-01-15",  # 2 years ago
        "2020-01-15",  # 6 years ago
        "2016-01-15",  # 10 years ago
    ]

    print("\nS&P 500 Membership Reconstruction Test")
    print("=" * 60)

    for date in test_dates:
        members = universe.get_members_on_date(date)
        print(f"\n{date}: {len(members)} members")

        # Show some stocks that were in S&P 500 then but not now (if any)
        current = universe._current_members
        removed_since = members - current
        added_since = current - members

        if removed_since:
            print(f"  Removed since: {list(removed_since)[:5]}...")
        if added_since:
            print(f"  Added since: {list(added_since)[:5]}...")

    # Get all historical members for 10-year backtest
    all_members = universe.get_all_historical_members("2016-01-01", "2026-01-20")
    print(f"\nTotal unique stocks in S&P 500 (2016-2026): {len(all_members)}")

    await universe.close()


if __name__ == "__main__":
    asyncio.run(test_universe())
