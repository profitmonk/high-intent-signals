#!/usr/bin/env python3
"""
Strict Portfolio Analyzer

Performs portfolio simulation with STRICT date validation:
- Only uses signals where entry price data exists on exact date
- Only calculates returns where exit price data exists on exact date
- Drops any signal/trade where required data is missing
- Reports how many signals were dropped and why

Usage:
    python strict_portfolio_analyzer.py                    # Run all datasets
    python strict_portfolio_analyzer.py --dataset 1b       # Run $1B+ only
"""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict


PRICE_CACHE_DIR = Path("data/cache")


@dataclass
class StrictTradeResult:
    """Result for a single trade with strict validation."""
    ticker: str
    score: int
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    days_held: int
    return_pct: float
    exit_reason: str  # 'time', 'stop_loss'
    cost_basis: float = 0.0
    shares: int = 0
    pnl: float = 0.0


class StrictPortfolioAnalyzer:
    """Analyzes portfolio with strict date validation."""

    def __init__(self):
        self.price_data: Dict[str, Dict[str, Dict]] = {}  # ticker -> date -> {open, high, low, close}
        self.signals: List[Dict] = []
        self.dropped_signals: List[Dict] = []

    def load_price_cache(self, tickers: Set[str]) -> None:
        """Load price data and index by date for fast exact lookup."""
        loaded = 0

        for ticker in tickers:
            # Find the largest price file for this ticker
            patterns = [
                f"_historical-price-full_{ticker}_*.json",
            ]

            cache_file = None
            for pattern in patterns:
                matches = list(PRICE_CACHE_DIR.glob(pattern))
                if matches:
                    # Sort by file size (descending) to get the file with most data
                    matches.sort(key=lambda x: x.stat().st_size, reverse=True)
                    cache_file = matches[0]
                    break

            if cache_file and cache_file.exists():
                try:
                    with open(cache_file) as f:
                        data = json.load(f)
                        if isinstance(data, dict) and 'historical' in data:
                            # Index by date for O(1) lookup
                            self.price_data[ticker] = {}
                            for day in data['historical']:
                                date = day.get('date', '')
                                if date:
                                    self.price_data[ticker][date] = {
                                        'open': day.get('open'),
                                        'high': day.get('high'),
                                        'low': day.get('low'),
                                        'close': day.get('close'),
                                        'volume': day.get('volume'),
                                    }
                            loaded += 1
                except Exception as e:
                    print(f"  Warning: Failed to load {ticker}: {e}")

        print(f"Loaded price data for {loaded}/{len(tickers)} tickers")

    def get_close_on_exact_date(self, ticker: str, date: str) -> Optional[float]:
        """Get closing price only if we have data for that EXACT date."""
        if ticker not in self.price_data:
            return None
        if date not in self.price_data[ticker]:
            return None
        return self.price_data[ticker][date].get('close')

    def get_close_within_days(self, ticker: str, target_date: str, max_days: int = 5) -> Tuple[Optional[float], Optional[str]]:
        """Get closing price within max_days of target date. Returns (price, actual_date)."""
        if ticker not in self.price_data:
            return None, None

        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        # Try exact date first
        if target_date in self.price_data[ticker]:
            return self.price_data[ticker][target_date].get('close'), target_date

        # Try nearby dates (prefer later dates for entry, earlier for exit)
        for offset in range(1, max_days + 1):
            # Try date + offset (for entry: next trading day)
            later_date = (target_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            if later_date in self.price_data[ticker]:
                return self.price_data[ticker][later_date].get('close'), later_date

            # Try date - offset (for exit: previous trading day)
            earlier_date = (target_dt - timedelta(days=offset)).strftime("%Y-%m-%d")
            if earlier_date in self.price_data[ticker]:
                return self.price_data[ticker][earlier_date].get('close'), earlier_date

        return None, None

    def get_latest_price(self, ticker: str) -> Tuple[Optional[float], Optional[str]]:
        """Get the most recent price for a ticker. Returns (price, date)."""
        if ticker not in self.price_data:
            return None, None

        dates = sorted(self.price_data[ticker].keys(), reverse=True)
        for date in dates:
            close = self.price_data[ticker][date].get('close')
            if close:
                return close, date
        return None, None

    def check_stop_loss_triggered(
        self, ticker: str, entry_date: str, entry_price: float, exit_date: str, stop_loss_pct: float
    ) -> Tuple[bool, Optional[str], Optional[float]]:
        """
        Check if stop loss was triggered between entry and exit dates.
        Returns: (triggered, stop_date, stop_price)
        """
        if ticker not in self.price_data:
            return False, None, None

        stop_price = entry_price * (1 - stop_loss_pct)
        entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
        exit_dt = datetime.strptime(exit_date, "%Y-%m-%d")

        # Check each day's low
        current_dt = entry_dt
        while current_dt <= exit_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            if date_str in self.price_data[ticker]:
                day_low = self.price_data[ticker][date_str].get('low')
                if day_low and day_low <= stop_price:
                    return True, date_str, stop_price
            current_dt += timedelta(days=1)

        return False, None, None

    def has_sufficient_price_data(self, ticker: str, start_date: str, end_date: str, min_coverage: float = 0.5) -> bool:
        """Check if we have sufficient price data coverage for a period."""
        if ticker not in self.price_data:
            return False

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        total_days = (end_dt - start_dt).days

        # If start == end (brand new signal), it's valid - just 0 days held so far
        if total_days <= 0:
            return True

        # Count trading days with data (approximate: exclude weekends)
        expected_trading_days = total_days * 5 / 7
        actual_days = 0

        current_dt = start_dt
        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            if date_str in self.price_data[ticker]:
                actual_days += 1
            current_dt += timedelta(days=1)

        coverage = actual_days / max(expected_trading_days, 1)
        return coverage >= min_coverage

    def analyze_signals_strict(
        self,
        signals_file: Path,
        holding_days: int = 365,
        stop_loss_pct: float = 0.25,
        min_score: int = 5,
        max_score: int = 7,
    ) -> Dict:
        """
        Analyze signals with STRICT date validation.
        - Drops signals where entry price is missing
        - Drops signals where coverage is insufficient in the MIDDLE of holding period
        - For signals where exit date is in future, uses latest available price (marked as 'open')
        """
        # Load signals
        with open(signals_file) as f:
            all_signals = json.load(f)

        print(f"\nAnalyzing {signals_file.name}")
        print(f"Total signals in file: {len(all_signals)}")
        print(f"Score filter: {min_score}-{max_score}")
        print(f"Holding period: {holding_days} days")
        print(f"Stop loss: -{stop_loss_pct:.0%}")

        # Filter by score
        signals = [s for s in all_signals if min_score <= s.get('score', 0) <= max_score]
        print(f"Signals after score filter: {len(signals)}")

        # Load price data
        tickers = set(s.get('ticker', '') for s in signals if s.get('ticker'))
        self.load_price_cache(tickers)

        # Track dropped signals
        dropped_no_entry_price = []
        dropped_no_price_coverage = []  # Real data gaps in middle of holding period

        # Analyze each signal
        valid_trades: List[StrictTradeResult] = []

        for signal in signals:
            ticker = signal.get('ticker', '')
            entry_date = signal.get('entry_date', signal.get('signal_date', ''))
            score = signal.get('score', 0)

            if not ticker or not entry_date:
                continue

            # Calculate expected exit date
            entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
            exit_dt = entry_dt + timedelta(days=holding_days)
            exit_date = exit_dt.strftime("%Y-%m-%d")

            # STRICT CHECK 1: Entry price must exist within 5 trading days
            entry_price, actual_entry_date = self.get_close_within_days(ticker, entry_date, max_days=5)
            if entry_price is None:
                dropped_no_entry_price.append({
                    'ticker': ticker,
                    'date': entry_date,
                    'reason': 'no_entry_price'
                })
                continue

            # Update entry date if we used a nearby date
            if actual_entry_date != entry_date:
                entry_date = actual_entry_date
                entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
                exit_dt = entry_dt + timedelta(days=holding_days)
                exit_date = exit_dt.strftime("%Y-%m-%d")

            # Get latest available price date for this ticker
            _, latest_date = self.get_latest_price(ticker)
            if not latest_date:
                dropped_no_entry_price.append({
                    'ticker': ticker,
                    'date': entry_date,
                    'reason': 'no_price_data'
                })
                continue

            latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")

            # Determine the effective end date for coverage check
            # (either exit date or latest available date, whichever is earlier)
            effective_end_date = min(exit_date, latest_date)

            # STRICT CHECK 2: Must have sufficient price data coverage from entry to effective end
            # This catches REAL data gaps (delisted stocks, missing data in middle)
            if not self.has_sufficient_price_data(ticker, entry_date, effective_end_date, min_coverage=0.3):
                dropped_no_price_coverage.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'exit_date': exit_date,
                    'effective_end': effective_end_date,
                    'reason': 'insufficient_coverage_in_period'
                })
                continue

            # Check if stop loss triggered (up to effective end date)
            stop_triggered, stop_date, stop_price = self.check_stop_loss_triggered(
                ticker, entry_date, entry_price, effective_end_date, stop_loss_pct
            )

            if stop_triggered:
                # Exit at stop loss
                actual_exit_date = stop_date
                actual_exit_price = stop_price
                exit_reason = 'stop_loss'
            else:
                # Check if this is a completed trade or still open
                exit_price, actual_exit_date = self.get_close_within_days(ticker, exit_date, max_days=5)

                if exit_price is not None:
                    # Trade completed - exited at 12M mark
                    actual_exit_price = exit_price
                    exit_reason = 'time'
                else:
                    # Exit date is in the future - use latest available price
                    actual_exit_price, actual_exit_date = self.get_latest_price(ticker)
                    exit_reason = 'open'  # Still holding

            # Calculate return
            days_held = (datetime.strptime(actual_exit_date, "%Y-%m-%d") - entry_dt).days
            return_pct = (actual_exit_price - entry_price) / entry_price

            valid_trades.append(StrictTradeResult(
                ticker=ticker,
                score=score,
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=actual_exit_date,
                exit_price=actual_exit_price,
                days_held=days_held,
                return_pct=return_pct,
                exit_reason=exit_reason,
            ))

        # Calculate statistics
        print(f"\n--- STRICT VALIDATION RESULTS ---")
        print(f"Valid trades: {len(valid_trades)}")
        print(f"Dropped - no entry price: {len(dropped_no_entry_price)}")
        print(f"Dropped - insufficient coverage (data gaps): {len(dropped_no_price_coverage)}")
        total_dropped = len(dropped_no_entry_price) + len(dropped_no_price_coverage)
        print(f"Total dropped: {total_dropped} ({total_dropped/(len(signals))*100:.1f}% of filtered signals)")

        if not valid_trades:
            return {'error': 'No valid trades'}

        # Separate closed vs open trades
        closed_trades = [t for t in valid_trades if t.exit_reason in ('stop_loss', 'time')]
        open_trades = [t for t in valid_trades if t.exit_reason == 'open']

        # Calculate returns for closed trades only (completed)
        closed_returns = [t.return_pct for t in closed_trades]
        closed_winners = [t for t in closed_trades if t.return_pct > 0]
        closed_losers = [t for t in closed_trades if t.return_pct <= 0]

        stop_loss_trades = [t for t in valid_trades if t.exit_reason == 'stop_loss']
        time_exit_trades = [t for t in valid_trades if t.exit_reason == 'time']

        # Stats for all trades (including open with current value)
        all_returns = [t.return_pct for t in valid_trades]
        all_winners = [t for t in valid_trades if t.return_pct > 0]
        all_losers = [t for t in valid_trades if t.return_pct <= 0]

        avg_return_closed = sum(closed_returns) / len(closed_returns) if closed_returns else 0
        avg_return_all = sum(all_returns) / len(all_returns)
        win_rate_closed = len(closed_winners) / len(closed_trades) if closed_trades else 0
        win_rate_all = len(all_winners) / len(valid_trades)
        avg_win = sum(t.return_pct for t in all_winners) / len(all_winners) if all_winners else 0
        avg_loss = sum(t.return_pct for t in all_losers) / len(all_losers) if all_losers else 0

        stats = {
            'file': signals_file.name,
            'total_signals': len(all_signals),
            'filtered_signals': len(signals),
            'valid_trades': len(valid_trades),
            'closed_trades': len(closed_trades),
            'open_trades': len(open_trades),
            'dropped_total': total_dropped,
            'dropped_no_entry': len(dropped_no_entry_price),
            'dropped_no_coverage': len(dropped_no_price_coverage),

            'avg_return_closed': avg_return_closed,
            'avg_return_all': avg_return_all,
            'win_rate_closed': win_rate_closed,
            'win_rate_all': win_rate_all,
            'winners': len(all_winners),
            'losers': len(all_losers),
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'best_return': max(all_returns),
            'worst_return': min(all_returns),

            'stop_loss_count': len(stop_loss_trades),
            'stop_loss_pct': len(stop_loss_trades) / len(closed_trades) if closed_trades else 0,
            'time_exit_count': len(time_exit_trades),

            'trades': valid_trades,
        }

        return stats

    def print_stats(self, stats: Dict) -> None:
        """Print analysis statistics."""
        if 'error' in stats:
            print(f"Error: {stats['error']}")
            return

        print(f"\n{'='*80}")
        print(f"STRICT ANALYSIS: {stats['file']}")
        print(f"{'='*80}")

        print(f"\nData Quality:")
        print(f"  Total signals:     {stats['total_signals']}")
        print(f"  After score filter: {stats['filtered_signals']}")
        print(f"  Valid trades:      {stats['valid_trades']} ({stats['valid_trades']/stats['filtered_signals']*100:.1f}%)")
        print(f"    - Closed:        {stats['closed_trades']} (stop_loss or 12M exit)")
        print(f"    - Open:          {stats['open_trades']} (still holding, using latest price)")
        print(f"  Dropped (total):   {stats['dropped_total']} ({stats['dropped_total']/stats['filtered_signals']*100:.1f}%)")
        print(f"    - No entry price:  {stats['dropped_no_entry']}")
        print(f"    - Data gaps:       {stats['dropped_no_coverage']} (insufficient coverage in holding period)")

        print(f"\nPerformance - CLOSED trades only ({stats['closed_trades']} trades):")
        print(f"  Avg Return:    {stats['avg_return_closed']:+.1%}")
        print(f"  Win Rate:      {stats['win_rate_closed']:.1%}")

        print(f"\nPerformance - ALL trades including OPEN ({stats['valid_trades']} trades):")
        print(f"  Avg Return:    {stats['avg_return_all']:+.1%}")
        print(f"  Win Rate:      {stats['win_rate_all']:.1%} ({stats['winners']}W / {stats['losers']}L)")
        print(f"  Avg Win:       {stats['avg_win']:+.1%}")
        print(f"  Avg Loss:      {stats['avg_loss']:+.1%}")
        print(f"  Best:          {stats['best_return']:+.1%}")
        print(f"  Worst:         {stats['worst_return']:+.1%}")

        print(f"\nExit Reasons (closed trades):")
        print(f"  Stop Loss (-25%): {stats['stop_loss_count']} ({stats['stop_loss_pct']:.1%} of closed)")
        print(f"  Time (12M):       {stats['time_exit_count']} ({stats['time_exit_count']/stats['closed_trades']*100:.1f}% of closed)" if stats['closed_trades'] else "  Time (12M):       0")

    def print_trades(self, stats: Dict) -> None:
        """Print all trades as a table."""
        if 'error' in stats or 'trades' not in stats:
            return

        trades = sorted(stats['trades'], key=lambda x: x.entry_date)

        print(f"\nAll Trades ({len(trades)}):")
        print(f"{'Entry':<12} {'Exit':<12} {'Ticker':<8} {'Score':>5} {'Entry$':>10} {'Exit$':>10} {'Return':>10} {'Days':>6} {'Reason':<10}")
        print("-" * 95)

        for t in trades:
            print(f"{t.entry_date:<12} {t.exit_date:<12} {t.ticker:<8} {t.score:>5} {t.entry_price:>10.2f} {t.exit_price:>10.2f} {t.return_pct:>+9.1%} {t.days_held:>6} {t.exit_reason:<10}")

        # Top 10 winners
        top_winners = sorted([t for t in trades if t.return_pct > 0], key=lambda x: -x.return_pct)[:10]
        print(f"\nTop 10 Winners:")
        for t in top_winners:
            print(f"  {t.ticker}: {t.return_pct:+.1%} | {t.entry_date} -> {t.exit_date}")


def main():
    parser = argparse.ArgumentParser(description="Strict portfolio analysis with date validation")
    parser.add_argument("--dataset", type=str, choices=['1b', 'micro-small', 'small-cap', 'all'],
                        default='all', help="Which dataset to analyze")
    parser.add_argument("--print-trades", action="store_true", help="Print all trades")
    parser.add_argument("--stop-loss", type=float, default=0.25, help="Stop loss percentage (default: 0.25 for -25%%)")
    args = parser.parse_args()

    datasets = {
        '1b': ("$1B+ Market Cap", Path("data/signals_history_1b_2023.json")),
        'micro-small': ("Micro-Small ($500M-$2B)", Path("data/signals_history_micro_small.json")),
        'small-cap': ("Small-Cap ($1B-$5B)", Path("data/signals_history_small_cap.json")),
    }

    if args.dataset == 'all':
        selected = list(datasets.keys())
    else:
        selected = [args.dataset]

    analyzer = StrictPortfolioAnalyzer()
    all_stats = []

    for key in selected:
        name, path = datasets[key]
        if not path.exists():
            print(f"Skipping {name} - file not found: {path}")
            continue

        stats = analyzer.analyze_signals_strict(path, stop_loss_pct=args.stop_loss)
        stats['dataset_name'] = name
        all_stats.append(stats)

        analyzer.print_stats(stats)
        if args.print_trades:
            analyzer.print_trades(stats)

    # Summary comparison
    if len(all_stats) > 1:
        print(f"\n{'='*120}")
        print("SUMMARY COMPARISON (Strict Validation)")
        print(f"{'='*120}")
        print(f"{'Dataset':<30} {'Total':>7} {'Closed':>7} {'Open':>6} {'Drop':>6} {'AvgRet(Closed)':>14} {'AvgRet(All)':>12} {'Win%':>7} {'StopLoss%':>10}")
        print("-" * 120)
        for s in all_stats:
            if 'error' not in s:
                print(f"{s['dataset_name']:<30} {s['valid_trades']:>7} {s['closed_trades']:>7} {s['open_trades']:>6} {s['dropped_total']:>6} {s['avg_return_closed']:>+13.1%} {s['avg_return_all']:>+11.1%} {s['win_rate_all']:>6.1%} {s['stop_loss_pct']:>9.1%}")


if __name__ == "__main__":
    main()
