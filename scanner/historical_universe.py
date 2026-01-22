"""
Point-in-time market cap universe reconstruction for survivorship-bias-free backtesting.

This module provides functions to determine which stocks met market cap thresholds
at any historical date, avoiding survivorship bias.

Dynamic thresholds:
- 2016-01-01 to 2019-12-31: >$3B market cap
- 2020-01-01 onwards: >$5B market cap
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

from data.fmp_client import FMPClient

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache/historical")


@dataclass
class MarketCapThreshold:
    """Dynamic market cap threshold configuration."""
    start_date: str
    end_date: str
    min_market_cap: int

    def applies_to(self, date: str) -> bool:
        """Check if this threshold applies to a given date."""
        return self.start_date <= date <= self.end_date


# Default thresholds: $3B for 2016-2019, $5B for 2020+
DEFAULT_THRESHOLDS = [
    MarketCapThreshold("2015-01-01", "2019-12-31", 3_000_000_000),  # $3B
    MarketCapThreshold("2020-01-01", "2030-12-31", 5_000_000_000),  # $5B
]


class HistoricalMarketCapUniverse:
    """
    Manages point-in-time market cap filtering for survivorship-bias-free backtesting.

    Uses annual market cap data from enterprise-values endpoint to determine
    which stocks met the market cap threshold at any historical date.
    """

    def __init__(self, thresholds: Optional[List[MarketCapThreshold]] = None):
        self.fmp = FMPClient()
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        self._tickers: Optional[List[str]] = None
        self._market_cap_history: Dict[str, List[Dict]] = {}  # ticker -> [{date, marketCap}, ...]
        self._cache_file = CACHE_DIR / "market_cap_history.json"
        self._tickers_file = CACHE_DIR / "universe_1b_tickers.json"

    def get_threshold_for_date(self, date: str) -> int:
        """Get the market cap threshold for a specific date."""
        for threshold in self.thresholds:
            if threshold.applies_to(date):
                return threshold.min_market_cap
        # Default to $5B if no threshold matches
        return 5_000_000_000

    async def load(self, force_refresh: bool = False) -> None:
        """Load market cap history (from cache or API)."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Load ticker list
        if self._tickers_file.exists():
            with open(self._tickers_file) as f:
                self._tickers = json.load(f)
            logger.info(f"Loaded {len(self._tickers)} tickers from cache")
        else:
            logger.info("Fetching ticker universe from screener...")
            await self._fetch_ticker_universe()

        # Check cache freshness (refresh weekly)
        cache_valid = False
        if not force_refresh and self._cache_file.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(
                self._cache_file.stat().st_mtime
            )
            cache_valid = cache_age < timedelta(days=7)

        if cache_valid:
            logger.info("Loading market cap history from cache...")
            with open(self._cache_file) as f:
                self._market_cap_history = json.load(f)
            logger.info(f"Loaded market cap history for {len(self._market_cap_history)} tickers")
        else:
            logger.info("Fetching market cap history from API (this may take a while)...")
            await self._fetch_all_market_caps()

    async def _fetch_ticker_universe(self) -> None:
        """Fetch all stocks >$1B market cap."""
        stocks = await self.fmp.get_stock_screener(
            market_cap_min=1_000_000_000,
            is_etf=False,
            is_actively_trading=True,
            limit=10000,
        )
        self._tickers = [s['symbol'] for s in stocks if s.get('symbol')]

        with open(self._tickers_file, 'w') as f:
            json.dump(self._tickers, f)
        logger.info(f"Saved {len(self._tickers)} tickers to cache")

    async def _fetch_market_cap_for_ticker(self, ticker: str) -> Optional[List[Dict]]:
        """Fetch historical market cap for a single ticker."""
        try:
            data = await self.fmp._request(
                f'/enterprise-values/{ticker}',
                params={'period': 'annual', 'limit': 20}
            )
            if data:
                # Extract just date and market cap
                return [
                    {'date': d['date'], 'marketCap': d.get('marketCapitalization', 0)}
                    for d in data
                    if d.get('date') and d.get('marketCapitalization')
                ]
        except Exception as e:
            logger.debug(f"Failed to get market cap for {ticker}: {e}")
        return None

    async def _fetch_all_market_caps(self, max_concurrent: int = 10) -> None:
        """Fetch historical market cap for all tickers."""
        if not self._tickers:
            raise RuntimeError("No tickers loaded")

        total = len(self._tickers)
        self._market_cap_history = {}

        # Process in batches
        batch_size = max_concurrent
        for i in range(0, total, batch_size):
            batch = self._tickers[i:i + batch_size]

            tasks = [self._fetch_market_cap_for_ticker(t) for t in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for ticker, result in zip(batch, results):
                if isinstance(result, list) and result:
                    self._market_cap_history[ticker] = result

            # Progress update
            progress = min(i + batch_size, total)
            if progress % 100 == 0 or progress == total:
                logger.info(f"Fetched market cap: {progress}/{total} ({len(self._market_cap_history)} with data)")

            # Rate limiting
            await asyncio.sleep(0.5)

        # Save cache
        with open(self._cache_file, 'w') as f:
            json.dump(self._market_cap_history, f)
        logger.info(f"Saved market cap history for {len(self._market_cap_history)} tickers")

    def get_market_cap_on_date(self, ticker: str, target_date: str) -> Optional[int]:
        """
        Get the market cap for a ticker at a specific date.

        Uses the most recent annual report data that is <= target_date.
        """
        if ticker not in self._market_cap_history:
            return None

        history = self._market_cap_history[ticker]

        # Find the most recent market cap <= target_date
        valid_entries = [h for h in history if h['date'] <= target_date]

        if not valid_entries:
            # If target_date is before all records, use the oldest available
            # (stock existed but we don't have earlier data)
            return None

        # Get the most recent one
        most_recent = max(valid_entries, key=lambda x: x['date'])
        return most_recent['marketCap']

    def get_members_on_date(
        self,
        target_date: str,
        min_cap: Optional[int] = None,
        max_cap: Optional[int] = None,
    ) -> Set[str]:
        """
        Get all tickers that met the market cap threshold on a specific date.

        Args:
            target_date: Date in YYYY-MM-DD format
            min_cap: Override minimum market cap (uses dynamic threshold if None)
            max_cap: Maximum market cap filter (no max if None)

        Returns:
            Set of ticker symbols that met the threshold on that date
        """
        # Use provided min_cap or fall back to dynamic threshold
        threshold = min_cap if min_cap is not None else self.get_threshold_for_date(target_date)
        members = set()

        for ticker in self._market_cap_history:
            market_cap = self.get_market_cap_on_date(ticker, target_date)
            if market_cap and market_cap >= threshold:
                # Apply max cap filter if specified
                if max_cap is None or market_cap <= max_cap:
                    members.add(ticker)

        return members

    def get_members_with_stats(self, target_date: str) -> Tuple[Set[str], Dict]:
        """
        Get members on date with statistics.

        Returns:
            Tuple of (set of tickers, stats dict)
        """
        threshold = self.get_threshold_for_date(target_date)
        members = self.get_members_on_date(target_date)

        stats = {
            'target_date': target_date,
            'threshold': threshold,
            'threshold_str': f"${threshold/1e9:.0f}B",
            'total_members': len(members),
            'total_universe': len(self._market_cap_history),
        }

        return members, stats

    async def close(self):
        """Clean up resources."""
        await self.fmp.close()


async def test_historical_universe():
    """Test the historical universe reconstruction."""
    universe = HistoricalMarketCapUniverse()
    await universe.load()

    # Test a few dates with different thresholds
    test_dates = [
        ("2016-01-15", "$3B threshold"),
        ("2018-06-15", "$3B threshold"),
        ("2020-01-15", "$5B threshold"),
        ("2024-01-15", "$5B threshold"),
    ]

    print("\nHistorical Market Cap Universe Test")
    print("=" * 60)

    for date, desc in test_dates:
        members, stats = universe.get_members_with_stats(date)
        print(f"\n{date} ({desc}):")
        print(f"  Threshold: {stats['threshold_str']}")
        print(f"  Members meeting threshold: {stats['total_members']}")
        print(f"  Sample tickers: {list(members)[:10]}")

    await universe.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_historical_universe())
