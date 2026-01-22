#!/usr/bin/env python3
"""
Stop Loss Analyzer

Analyzes the impact of stop loss on signal returns using actual price data.
Compares returns with and without stop loss applied.

Usage:
    python stop_loss_analyzer.py data/signals_history_micro_small.json --stop-loss 0.25
    python stop_loss_analyzer.py --all --stop-loss 0.25  # Run on all 3 datasets
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from data.fmp_client import FMPClient

PRICE_CACHE_DIR = Path("data/cache")


@dataclass
class StopLossResult:
    """Result for a single signal with stop loss analysis."""
    ticker: str
    entry_date: str
    entry_price: float
    score: int

    # Without stop loss (original 12M return)
    return_12m_original: Optional[float]

    # With stop loss
    stop_triggered: bool
    stop_date: Optional[str]
    exit_price: float
    return_with_stop: float
    days_held: int


class StopLossAnalyzer:
    """Analyzes impact of stop loss on returns."""

    def __init__(self):
        self.price_data: Dict[str, List[Dict]] = {}
        self.fmp = FMPClient()

    def _load_price_cache(self, tickers: set) -> None:
        """Load cached historical price data for tickers."""
        loaded = 0

        for ticker in tickers:
            # Look for various cache file patterns
            patterns = [
                f"_historical-price-full_{ticker}_*.json",
                f"historical_{ticker}_*.json",
            ]

            cache_file = None
            for pattern in patterns:
                matches = list(PRICE_CACHE_DIR.glob(pattern))
                if matches:
                    cache_file = matches[0]
                    break

            if cache_file and cache_file.exists():
                try:
                    with open(cache_file) as f:
                        data = json.load(f)
                        if isinstance(data, dict) and 'historical' in data:
                            self.price_data[ticker] = data['historical']
                            loaded += 1
                        elif isinstance(data, list):
                            self.price_data[ticker] = data
                            loaded += 1
                except Exception:
                    pass

        print(f"Loaded price data for {loaded}/{len(tickers)} tickers from cache")

    async def _fetch_price_data(self, ticker: str, start_date: str, end_date: str) -> List[Dict]:
        """Fetch price data from API if not cached."""
        try:
            data = await self.fmp.get_historical_prices(
                ticker,
                from_date=start_date,
                to_date=end_date
            )
            if isinstance(data, dict) and 'historical' in data:
                return data['historical']
            elif isinstance(data, list):
                return data
        except Exception as e:
            pass
        return []

    def _get_price_data_for_period(
        self, ticker: str, start_date: str, end_date: str
    ) -> List[Dict]:
        """Get daily OHLC data for a ticker between dates."""
        if ticker not in self.price_data:
            return []

        data = self.price_data[ticker]
        filtered = [
            d for d in data
            if start_date <= d.get('date', '') <= end_date
        ]
        return sorted(filtered, key=lambda x: x.get('date', ''))

    def _get_close_on_date(self, ticker: str, target_date: str) -> Optional[float]:
        """Get closing price on a specific date (or nearest prior date)."""
        if ticker not in self.price_data:
            return None

        data = self.price_data[ticker]
        best_date = None
        best_price = None

        for d in data:
            date = d.get('date', '')
            if date <= target_date:
                if best_date is None or date > best_date:
                    best_date = date
                    best_price = d.get('close')

        return best_price

    def analyze_signal(
        self,
        signal: Dict,
        stop_loss_pct: float = 0.25,
        holding_days: int = 365
    ) -> Optional[StopLossResult]:
        """Analyze a single signal with stop loss."""

        ticker = signal.get('ticker', '')
        entry_date = signal.get('entry_date', signal.get('signal_date', ''))
        entry_price = signal.get('entry_price', signal.get('signal_price', 0))
        score = signal.get('score', 0)
        return_12m = signal.get('return_12m')

        if not ticker or not entry_date or not entry_price or entry_price <= 0:
            return None

        # Calculate exit date (12M from entry)
        entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
        exit_dt = entry_dt + timedelta(days=holding_days)
        exit_date_str = exit_dt.strftime("%Y-%m-%d")

        # Get price data for holding period
        price_data = self._get_price_data_for_period(ticker, entry_date, exit_date_str)

        if not price_data:
            # No price data - can't analyze
            return None

        # Check if stop loss triggered
        stop_price = entry_price * (1 - stop_loss_pct)
        stop_triggered = False
        stop_date = None
        exit_price = entry_price
        days_held = holding_days

        for day in price_data:
            low = day.get('low', 0)
            if low and low > 0 and low <= stop_price:
                # Stop triggered
                stop_triggered = True
                stop_date = day.get('date')
                exit_price = stop_price  # Exit at stop price
                stop_dt = datetime.strptime(stop_date, "%Y-%m-%d")
                days_held = (stop_dt - entry_dt).days
                break

        # If no stop triggered, get 12M exit price
        if not stop_triggered:
            close_12m = self._get_close_on_date(ticker, exit_date_str)
            if close_12m:
                exit_price = close_12m
            elif return_12m is not None:
                exit_price = entry_price * (1 + return_12m)
            else:
                # Use last available price
                if price_data:
                    exit_price = price_data[-1].get('close', entry_price)

        return_with_stop = (exit_price - entry_price) / entry_price

        return StopLossResult(
            ticker=ticker,
            entry_date=entry_date,
            entry_price=entry_price,
            score=score,
            return_12m_original=return_12m,
            stop_triggered=stop_triggered,
            stop_date=stop_date,
            exit_price=exit_price,
            return_with_stop=return_with_stop,
            days_held=days_held,
        )

    async def analyze_dataset(
        self,
        signals_file: Path,
        stop_loss_pct: float = 0.25,
        fetch_missing: bool = False
    ) -> Dict:
        """Analyze a signals dataset with stop loss.

        Uses a fair methodology:
        - Baseline: ALL signals with return_12m (from file)
        - With stop: For signals with price data, check if stop triggered
        - If stop triggered, replace return with -stop_loss_pct
        - If no price data, assume no stop (use original return)
        """

        # Load signals
        with open(signals_file) as f:
            signals = json.load(f)

        # Filter to signals with 12M returns (fair baseline)
        signals_with_12m = [s for s in signals if s.get('return_12m') is not None]

        print(f"\nAnalyzing {len(signals_with_12m)} signals with 12M returns from {signals_file.name}")
        print(f"Stop loss: -{stop_loss_pct:.0%}")

        # Load cached price data
        tickers = set(s.get('ticker', '') for s in signals_with_12m if s.get('ticker'))
        self._load_price_cache(tickers)

        # Fetch missing price data if requested
        if fetch_missing:
            missing = tickers - set(self.price_data.keys())
            if missing:
                print(f"Fetching price data for {len(missing)} missing tickers...")
                for i, ticker in enumerate(missing):
                    if (i + 1) % 50 == 0:
                        print(f"  Fetched {i + 1}/{len(missing)}...")

                    # Fetch 3 years of data
                    end = datetime.now()
                    start = end - timedelta(days=365 * 3)
                    data = await self._fetch_price_data(
                        ticker,
                        start.strftime("%Y-%m-%d"),
                        end.strftime("%Y-%m-%d")
                    )
                    if data:
                        self.price_data[ticker] = data
                    await asyncio.sleep(0.2)  # Rate limit

        # Analyze each signal - using fair methodology
        original_returns = []
        adjusted_returns = []
        stopped_signals = []
        analyzed_with_price = 0

        for signal in signals_with_12m:
            ticker = signal.get('ticker', '')
            entry_date = signal.get('entry_date', signal.get('signal_date', ''))
            entry_price = signal.get('entry_price', signal.get('signal_price', 0))
            return_12m = signal.get('return_12m')

            original_returns.append(return_12m)

            # Try to check stop loss with actual price data
            result = self.analyze_signal(signal, stop_loss_pct)

            if result and result.stop_triggered:
                # Stop was triggered - use stop loss return
                adjusted_returns.append(-stop_loss_pct)
                stopped_signals.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'stop_date': result.stop_date,
                    'days_held': result.days_held,
                    'would_have_been': return_12m,
                })
                analyzed_with_price += 1
            elif result:
                # Had price data, no stop triggered - use original return
                adjusted_returns.append(return_12m)
                analyzed_with_price += 1
            else:
                # No price data - assume no stop (conservative)
                adjusted_returns.append(return_12m)

        # Calculate statistics
        avg_original = sum(original_returns) / len(original_returns) if original_returns else 0
        avg_adjusted = sum(adjusted_returns) / len(adjusted_returns) if adjusted_returns else 0

        winners_original = len([r for r in original_returns if r > 0])
        winners_adjusted = len([r for r in adjusted_returns if r > 0])

        # Stopped trades analysis
        stopped_would_have = [s['would_have_been'] for s in stopped_signals]
        avg_stopped_would_have = sum(stopped_would_have) / len(stopped_would_have) if stopped_would_have else 0
        avg_days_stopped = sum(s['days_held'] for s in stopped_signals) / len(stopped_signals) if stopped_signals else 0

        stats = {
            'file': signals_file.name,
            'stop_loss_pct': stop_loss_pct,
            'total_signals': len(signals),
            'signals_with_12m': len(signals_with_12m),
            'analyzed_with_price_data': analyzed_with_price,

            'original': {
                'avg_return': avg_original,
                'win_rate': winners_original / len(original_returns) if original_returns else 0,
                'best': max(original_returns) if original_returns else 0,
                'worst': min(original_returns) if original_returns else 0,
            },

            'with_stop_loss': {
                'avg_return': avg_adjusted,
                'win_rate': winners_adjusted / len(adjusted_returns) if adjusted_returns else 0,
                'best': max(adjusted_returns) if adjusted_returns else 0,
                'worst': min(adjusted_returns) if adjusted_returns else 0,
            },

            'stop_triggered': {
                'count': len(stopped_signals),
                'pct_of_total': len(stopped_signals) / len(signals_with_12m) if signals_with_12m else 0,
                'avg_days_held': avg_days_stopped,
                'avg_return': -stop_loss_pct,
                'would_have_avg': avg_stopped_would_have,
            },

            'improvement': avg_adjusted - avg_original,
        }

        return stats, stopped_signals

    def print_stats(self, stats: Dict) -> None:
        """Print analysis statistics."""

        print("\n" + "=" * 60)
        print(f"STOP LOSS ANALYSIS: {stats['file']}")
        print("=" * 60)

        print(f"\nDataset: {stats['signals_with_12m']} signals with 12M returns")
        print(f"Price data available for: {stats['analyzed_with_price_data']} signals")
        print(f"Stop Loss: -{stats['stop_loss_pct']:.0%}")

        orig = stats['original']
        stop = stats['with_stop_loss']
        triggered = stats['stop_triggered']

        print(f"\n{'Metric':<25} {'Without Stop':<15} {'With Stop':<15} {'Diff':<10}")
        print("-" * 65)
        print(f"{'Avg 12M Return':<25} {orig['avg_return']:>+13.1%} {stop['avg_return']:>+13.1%} {stats['improvement']:>+8.1%}")
        print(f"{'Win Rate':<25} {orig['win_rate']:>13.1%} {stop['win_rate']:>13.1%}")
        print(f"{'Best Return':<25} {orig['best']:>+13.1%} {stop['best']:>+13.1%}")
        print(f"{'Worst Return':<25} {orig['worst']:>+13.1%} {stop['worst']:>+13.1%}")

        print(f"\nStop Loss Triggered:")
        print(f"  Count: {triggered['count']} ({triggered['pct_of_total']:.1%} of signals)")
        print(f"  Avg days held: {triggered['avg_days_held']:.0f}")
        print(f"  Return at stop: {triggered['avg_return']:+.1%}")
        print(f"  Would have been: {triggered['would_have_avg']:+.1%}")

        # Was the stop helpful?
        if triggered['would_have_avg'] < triggered['avg_return']:
            saved = triggered['avg_return'] - triggered['would_have_avg']
            print(f"  Stop HELPED: saved {saved:+.1%} per stopped trade")
        else:
            cost = triggered['would_have_avg'] - triggered['avg_return']
            print(f"  Stop HURT: cost {cost:+.1%} per stopped trade")

    async def close(self):
        """Cleanup."""
        await self.fmp.close()


async def main():
    parser = argparse.ArgumentParser(description="Analyze stop loss impact on signal returns")
    parser.add_argument("signals_file", nargs="?", type=str, help="Path to signals JSON file")
    parser.add_argument("--all", action="store_true", help="Run on all 3 datasets")
    parser.add_argument("--stop-loss", type=float, default=0.25, help="Stop loss percentage (default: 0.25)")
    parser.add_argument("--fetch", action="store_true", help="Fetch missing price data from API")

    args = parser.parse_args()

    analyzer = StopLossAnalyzer()

    try:
        if args.all:
            # Run on all 3 datasets
            datasets = [
                Path("data/signals_history_1b_2023.json"),  # $1B+ (if exists)
                Path("data/signals_history_micro_small.json"),  # $500M-$2B
                Path("data/signals_history_small_cap.json"),  # $1B-$5B
            ]

            all_stats = []
            for ds in datasets:
                if ds.exists():
                    stats, _ = await analyzer.analyze_dataset(ds, args.stop_loss, args.fetch)
                    analyzer.print_stats(stats)
                    all_stats.append(stats)
                else:
                    print(f"\nSkipping {ds.name} (not found)")

            # Summary comparison
            if len(all_stats) > 1:
                print("\n" + "=" * 70)
                print("SUMMARY COMPARISON")
                print("=" * 70)
                print(f"\n{'Dataset':<35} {'Original':<12} {'With Stop':<12} {'Diff':<10}")
                print("-" * 70)
                for s in all_stats:
                    name = s['file'].replace('signals_history_', '').replace('.json', '')
                    print(f"{name:<35} {s['original']['avg_return']:>+10.1%} {s['with_stop_loss']['avg_return']:>+10.1%} {s['improvement']:>+8.1%}")

        elif args.signals_file:
            signals_path = Path(args.signals_file)
            if not signals_path.exists():
                print(f"Error: File not found: {signals_path}")
                return

            stats, results = await analyzer.analyze_dataset(signals_path, args.stop_loss, args.fetch)
            analyzer.print_stats(stats)

        else:
            parser.print_help()

    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
