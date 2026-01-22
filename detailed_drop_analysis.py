#!/usr/bin/env python3
"""
Detailed Drop Analysis - Shows exactly why each signal was dropped.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict

PRICE_CACHE_DIR = Path("data/cache")
DATA_DIR = Path("data")


class DetailedDropAnalyzer:
    """Analyzes why signals are dropped with detailed explanations."""

    def __init__(self):
        self.price_data: Dict[str, Dict[str, Dict]] = {}
        self.price_file_used: Dict[str, str] = {}  # ticker -> filename
        self.tickers_not_in_cache: Set[str] = set()

    def load_price_cache(self, tickers: Set[str]) -> None:
        """Load price data for tickers."""
        for ticker in tickers:
            patterns = [f"_historical-price-full_{ticker}_*.json"]

            cache_file = None
            for pattern in patterns:
                matches = list(PRICE_CACHE_DIR.glob(pattern))
                if matches:
                    matches.sort(key=lambda x: x.stat().st_size, reverse=True)
                    cache_file = matches[0]
                    break

            if cache_file and cache_file.exists():
                try:
                    with open(cache_file) as f:
                        data = json.load(f)
                        if isinstance(data, dict) and 'historical' in data:
                            self.price_data[ticker] = {}
                            for day in data['historical']:
                                date = day.get('date', '')
                                if date:
                                    self.price_data[ticker][date] = {
                                        'open': day.get('open'),
                                        'high': day.get('high'),
                                        'low': day.get('low'),
                                        'close': day.get('close'),
                                    }
                            self.price_file_used[ticker] = cache_file.name
                except Exception as e:
                    print(f"  Warning: Failed to load {ticker}: {e}")
            else:
                self.tickers_not_in_cache.add(ticker)

    def get_close_within_days(self, ticker: str, target_date: str, max_days: int = 5) -> Tuple[Optional[float], Optional[str]]:
        """Get closing price within max_days of target date."""
        if ticker not in self.price_data:
            return None, None

        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        if target_date in self.price_data[ticker]:
            return self.price_data[ticker][target_date].get('close'), target_date

        for offset in range(1, max_days + 1):
            later_date = (target_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            if later_date in self.price_data[ticker]:
                return self.price_data[ticker][later_date].get('close'), later_date

            earlier_date = (target_dt - timedelta(days=offset)).strftime("%Y-%m-%d")
            if earlier_date in self.price_data[ticker]:
                return self.price_data[ticker][earlier_date].get('close'), earlier_date

        return None, None

    def get_price_data_range(self, ticker: str) -> Tuple[Optional[str], Optional[str]]:
        """Get the date range of price data for a ticker."""
        if ticker not in self.price_data:
            return None, None
        dates = sorted(self.price_data[ticker].keys())
        if dates:
            return dates[0], dates[-1]
        return None, None

    def count_coverage(self, ticker: str, start_date: str, end_date: str) -> Tuple[int, int, float]:
        """Count price data coverage for a period."""
        if ticker not in self.price_data:
            return 0, 0, 0.0

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        total_days = (end_dt - start_dt).days
        expected_trading_days = int(total_days * 5 / 7)

        actual_days = 0
        current_dt = start_dt
        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            if date_str in self.price_data[ticker]:
                actual_days += 1
            current_dt += timedelta(days=1)

        coverage = actual_days / max(expected_trading_days, 1)
        return actual_days, expected_trading_days, coverage

    def analyze(self, signals_file: Path, holding_days: int = 365, min_score: int = 5, max_score: int = 7):
        """Run detailed drop analysis - only drops signals with REAL data gaps."""

        print(f"\n{'='*100}")
        print(f"DETAILED DROP ANALYSIS (Data Gaps Only)")
        print(f"{'='*100}")
        print(f"\nSignals file: {signals_file}")
        print(f"Full path: {signals_file.absolute()}")

        # Load signals
        with open(signals_file) as f:
            all_signals = json.load(f)

        print(f"Total signals in file: {len(all_signals)}")

        # Filter by score
        signals = [s for s in all_signals if min_score <= s.get('score', 0) <= max_score]
        print(f"Signals after score filter ({min_score}-{max_score}): {len(signals)}")

        # Load price data
        tickers = set(s.get('ticker', '') for s in signals if s.get('ticker'))
        print(f"Unique tickers: {len(tickers)}")
        self.load_price_cache(tickers)
        print(f"Tickers with price data: {len(self.price_data)}")
        print(f"Tickers NOT in cache: {len(self.tickers_not_in_cache)}")

        # Categorize drops - only real data gaps
        dropped_no_cache = []
        dropped_no_entry = []
        dropped_data_gaps = []  # Real gaps in the middle of holding period
        valid_closed = []
        valid_open = []

        for signal in signals:
            ticker = signal.get('ticker', '')
            entry_date = signal.get('entry_date', signal.get('signal_date', ''))
            score = signal.get('score', 0)

            if not ticker or not entry_date:
                continue

            entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
            exit_dt = entry_dt + timedelta(days=holding_days)
            exit_date = exit_dt.strftime("%Y-%m-%d")

            # Check 1: Is ticker in cache at all?
            if ticker not in self.price_data:
                dropped_no_cache.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'score': score,
                    'reason': 'Ticker not in price cache',
                    'detail': f"No file matching _historical-price-full_{ticker}_*.json found"
                })
                continue

            # Check 2: Can we get entry price?
            entry_price, actual_entry_date = self.get_close_within_days(ticker, entry_date, max_days=5)
            if entry_price is None:
                data_start, data_end = self.get_price_data_range(ticker)
                dropped_no_entry.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'score': score,
                    'reason': 'No entry price found',
                    'detail': f"Needed: {entry_date} (±5 days). Data range: {data_start} to {data_end}",
                    'cache_file': self.price_file_used.get(ticker, 'N/A')
                })
                continue

            # Update dates if we used nearby date
            if actual_entry_date != entry_date:
                entry_date = actual_entry_date
                entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
                exit_dt = entry_dt + timedelta(days=holding_days)
                exit_date = exit_dt.strftime("%Y-%m-%d")

            # Get latest available price date
            data_start, data_end = self.get_price_data_range(ticker)

            # Effective end date is min of exit date or latest data
            effective_end_date = min(exit_date, data_end) if data_end else exit_date

            # Check 3: Sufficient coverage from entry to effective end?
            # This catches REAL data gaps (delisted, missing data in middle)
            actual_days, expected_days, coverage = self.count_coverage(ticker, entry_date, effective_end_date)
            if coverage < 0.3:
                dropped_data_gaps.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'exit_date': exit_date,
                    'effective_end': effective_end_date,
                    'score': score,
                    'reason': 'Data gap in holding period',
                    'detail': f"Coverage: {actual_days}/{expected_days} days ({coverage:.1%}). Need 30%. Data range: {data_start} to {data_end}",
                    'cache_file': self.price_file_used.get(ticker, 'N/A')
                })
                continue

            # Check if trade is closed or still open
            exit_price, actual_exit_date = self.get_close_within_days(ticker, exit_date, max_days=5)
            if exit_price is not None:
                valid_closed.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'exit_date': actual_exit_date,
                    'score': score,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'status': 'closed'
                })
            else:
                # Open position - use latest price
                valid_open.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'exit_date': exit_date,
                    'latest_date': data_end,
                    'score': score,
                    'entry_price': entry_price,
                    'status': 'open'
                })

        # Print results
        print(f"\n{'='*100}")
        print(f"RESULTS SUMMARY")
        print(f"{'='*100}")
        print(f"Valid - Closed:             {len(valid_closed)}")
        print(f"Valid - Open (using latest): {len(valid_open)}")
        print(f"Total valid:                {len(valid_closed) + len(valid_open)}")
        print(f"Dropped - No cache:         {len(dropped_no_cache)}")
        print(f"Dropped - No entry price:   {len(dropped_no_entry)}")
        print(f"Dropped - Data gaps:        {len(dropped_data_gaps)} <-- REAL data issues")
        total_dropped = len(dropped_no_cache) + len(dropped_no_entry) + len(dropped_data_gaps)
        print(f"Total dropped:              {total_dropped}")

        # Print detailed drops - only the ones with real data gaps
        if dropped_no_cache:
            print(f"\n{'='*100}")
            print(f"DROPPED: NO PRICE CACHE ({len(dropped_no_cache)} signals)")
            print(f"{'='*100}")
            print(f"These tickers have NO price data file in data/cache/")
            print(f"\n{'Ticker':<10} {'Entry Date':<12} {'Score':>6}  {'Detail'}")
            print("-" * 90)
            for d in sorted(dropped_no_cache, key=lambda x: x['ticker']):
                print(f"{d['ticker']:<10} {d['entry_date']:<12} {d['score']:>6}  {d['detail']}")

        if dropped_no_entry:
            print(f"\n{'='*100}")
            print(f"DROPPED: NO ENTRY PRICE ({len(dropped_no_entry)} signals)")
            print(f"{'='*100}")
            print(f"These tickers have price data, but not for the signal date (±5 days)")
            print(f"\n{'Ticker':<10} {'Entry Date':<12} {'Score':>6}  {'Detail'}")
            print("-" * 90)
            for d in sorted(dropped_no_entry, key=lambda x: (x['ticker'], x['entry_date'])):
                print(f"{d['ticker']:<10} {d['entry_date']:<12} {d['score']:>6}  {d['detail']}")
                print(f"           Cache file: {d['cache_file']}")

        if dropped_data_gaps:
            print(f"\n{'='*100}")
            print(f"DROPPED: DATA GAPS IN HOLDING PERIOD ({len(dropped_data_gaps)} signals)")
            print(f"{'='*100}")
            print(f"These tickers have <30% price data coverage from entry to effective end date")
            print(f"This indicates REAL data issues (delisted, ticker changed, missing data)")
            print(f"\n{'Ticker':<10} {'Entry':<12} {'Eff.End':<12} {'Score':>6}  {'Detail'}")
            print("-" * 110)
            for d in sorted(dropped_data_gaps, key=lambda x: (x['ticker'], x['entry_date'])):
                print(f"{d['ticker']:<10} {d['entry_date']:<12} {d['effective_end']:<12} {d['score']:>6}  {d['detail']}")
                print(f"           Cache file: {d['cache_file']}")

        # Print cache files used
        print(f"\n{'='*100}")
        print(f"FILES USED")
        print(f"{'='*100}")
        print(f"Signals file: {signals_file.absolute()}")
        print(f"Price cache dir: {PRICE_CACHE_DIR.absolute()}")
        all_valid = valid_closed + valid_open
        print(f"\nTotal unique tickers with valid trades: {len(set(v['ticker'] for v in all_valid))}")


def main():
    signals_file = Path("data/signals_history_1b_2023.json")

    analyzer = DetailedDropAnalyzer()
    analyzer.analyze(signals_file)


if __name__ == "__main__":
    main()
