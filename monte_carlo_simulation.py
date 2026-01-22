#!/usr/bin/env python3
"""
Monte Carlo Portfolio Simulation - Tests strategy robustness across different start dates.

Runs the portfolio simulation from multiple start dates (every 6-8 weeks) to check
if returns are statistically robust or heavily dependent on start timing.

Usage:
    python monte_carlo_simulation.py
    python monte_carlo_simulation.py --dataset 1b --stop-loss 0.60
    python monte_carlo_simulation.py --min-gap 6 --max-gap 8
"""

import argparse
import json
import random
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import math

from portfolio_simulator import PortfolioSimulator, StrategyConfig, SIGNALS_DB_PATH

# Paths
DATA_DIR = Path("data")
RESULTS_DIR = Path("simulation_results")


@dataclass
class SimulationRun:
    """Results from a single simulation run."""
    start_date: str
    end_date: str
    total_return: float
    cagr: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    final_value: float
    stop_loss_count: int
    time_exit_count: int


def generate_start_dates(
    start_year: int = 2023,
    end_year: int = 2025,
    min_gap_weeks: int = 6,
    max_gap_weeks: int = 8,
    seed: int = 42
) -> List[str]:
    """
    Generate start dates every 6-8 weeks from start_year to end_year.

    Args:
        start_year: First year to include
        end_year: Last year to include
        min_gap_weeks: Minimum weeks between start dates
        max_gap_weeks: Maximum weeks between start dates
        seed: Random seed for reproducibility

    Returns:
        List of date strings in YYYY-MM-DD format
    """
    rng = random.Random(seed)

    start_dt = datetime(start_year, 1, 1)
    # End date should allow for at least 12 months of simulation
    end_dt = datetime(end_year, 12, 31)

    dates = []
    current_dt = start_dt

    while current_dt <= end_dt:
        # Use Monday of the week
        days_to_monday = (7 - current_dt.weekday()) % 7
        if days_to_monday == 0 and current_dt.weekday() != 0:
            days_to_monday = 7
        monday_dt = current_dt + timedelta(days=days_to_monday)
        if monday_dt.weekday() != 0:
            monday_dt = current_dt - timedelta(days=current_dt.weekday())

        dates.append(current_dt.strftime("%Y-%m-%d"))

        # Random gap between min and max weeks
        gap_weeks = rng.randint(min_gap_weeks, max_gap_weeks)
        current_dt += timedelta(weeks=gap_weeks)

    return dates


def run_monte_carlo(
    signals_file: Path,
    start_dates: List[str],
    holding_days: int = 365,
    stop_loss: float = 0.60,
    initial_capital: float = 100000,
    min_score: int = 5,
    max_score: int = 7,
    max_positions: int = 40,
    max_position_pct: float = 0.04,
) -> List[SimulationRun]:
    """
    Run portfolio simulation from multiple start dates.

    Args:
        signals_file: Path to signals JSON file
        start_dates: List of start dates to test
        holding_days: Holding period in days
        stop_loss: Stop loss percentage (0.60 = -60%)
        initial_capital: Starting capital
        min_score: Minimum signal score
        max_score: Maximum signal score
        max_positions: Maximum concurrent positions
        max_position_pct: Maximum position size as % of portfolio

    Returns:
        List of SimulationRun results
    """
    # Copy signals file to main location
    shutil.copy(signals_file, SIGNALS_DB_PATH)

    # Load all signals once
    with open(signals_file) as f:
        all_signals = json.load(f)

    results = []

    for i, start_date in enumerate(start_dates):
        print(f"  Running simulation {i+1}/{len(start_dates)}: start={start_date}")

        # Filter signals to only those on or after start_date
        filtered_signals = [
            s for s in all_signals
            if s.get('entry_date', s.get('signal_date', '')) >= start_date
        ]

        if not filtered_signals:
            print(f"    Skipping - no signals after {start_date}")
            continue

        # Write filtered signals temporarily
        with open(SIGNALS_DB_PATH, 'w') as f:
            json.dump(filtered_signals, f)

        # Create simulator and run
        sim = PortfolioSimulator()
        sim.load_signals()

        config = StrategyConfig(
            name=f"MC_{start_date}",
            holding_period_days=holding_days,
            stop_loss_pct=stop_loss,
            max_position_pct=max_position_pct,
            max_positions=max_positions,
            min_score=min_score,
            max_score=max_score,
            initial_capital=initial_capital,
        )

        result = sim.run_simulation(config)

        # Count exit reasons
        stop_loss_count = sum(1 for p in result.closed_positions if p.exit_reason == 'stop_loss')
        time_exit_count = sum(1 for p in result.closed_positions if p.exit_reason == 'time')

        # Determine end date from equity curve
        end_date = result.equity_curve[-1][0] if result.equity_curve else datetime.now().strftime("%Y-%m-%d")

        run = SimulationRun(
            start_date=start_date,
            end_date=end_date,
            total_return=result.total_return,
            cagr=result.cagr,
            max_drawdown=result.max_drawdown,
            total_trades=result.total_trades,
            win_rate=result.win_rate,
            avg_win=result.avg_win,
            avg_loss=result.avg_loss,
            profit_factor=result.profit_factor,
            final_value=result.final_value,
            stop_loss_count=stop_loss_count,
            time_exit_count=time_exit_count,
        )
        results.append(run)

    # Restore original signals file
    shutil.copy(signals_file, SIGNALS_DB_PATH)

    return results


def calculate_statistics(results: List[SimulationRun]) -> Dict:
    """Calculate summary statistics from simulation runs."""

    if not results:
        return {"error": "No results to analyze"}

    def percentile(data: List[float], p: float) -> float:
        sorted_data = sorted(data)
        idx = int(len(sorted_data) * p / 100)
        return sorted_data[min(idx, len(sorted_data) - 1)]

    def mean(data: List[float]) -> float:
        return sum(data) / len(data) if data else 0

    def std(data: List[float]) -> float:
        if len(data) < 2:
            return 0
        m = mean(data)
        variance = sum((x - m) ** 2 for x in data) / (len(data) - 1)
        return math.sqrt(variance)

    returns = [r.total_return for r in results]
    cagrs = [r.cagr for r in results]
    drawdowns = [r.max_drawdown for r in results]
    win_rates = [r.win_rate for r in results]
    trades = [r.total_trades for r in results]
    profit_factors = [r.profit_factor for r in results if r.profit_factor < float('inf')]

    stats = {
        'num_simulations': len(results),
        'date_range': f"{results[0].start_date} to {results[-1].start_date}",

        'total_return': {
            'mean': mean(returns),
            'std': std(returns),
            'median': percentile(returns, 50),
            'min': min(returns),
            'max': max(returns),
            'p10': percentile(returns, 10),
            'p25': percentile(returns, 25),
            'p75': percentile(returns, 75),
            'p90': percentile(returns, 90),
        },

        'cagr': {
            'mean': mean(cagrs),
            'std': std(cagrs),
            'median': percentile(cagrs, 50),
            'min': min(cagrs),
            'max': max(cagrs),
            'p10': percentile(cagrs, 10),
            'p90': percentile(cagrs, 90),
        },

        'max_drawdown': {
            'mean': mean(drawdowns),
            'median': percentile(drawdowns, 50),
            'worst': max(drawdowns),
            'best': min(drawdowns),
        },

        'win_rate': {
            'mean': mean(win_rates),
            'std': std(win_rates),
            'min': min(win_rates),
            'max': max(win_rates),
        },

        'trades': {
            'mean': mean(trades),
            'min': min(trades),
            'max': max(trades),
        },

        'profit_factor': {
            'mean': mean(profit_factors) if profit_factors else 0,
            'median': percentile(profit_factors, 50) if profit_factors else 0,
        },

        'individual_runs': [
            {
                'start_date': r.start_date,
                'total_return': r.total_return,
                'cagr': r.cagr,
                'max_drawdown': r.max_drawdown,
                'trades': r.total_trades,
                'win_rate': r.win_rate,
                'final_value': r.final_value,
            }
            for r in results
        ],
    }

    return stats


def print_results(stats: Dict, results: List[SimulationRun]) -> None:
    """Print Monte Carlo simulation results."""

    print("\n" + "=" * 100)
    print("MONTE CARLO SIMULATION RESULTS")
    print("=" * 100)

    print(f"\nSimulations Run: {stats['num_simulations']}")
    print(f"Start Date Range: {stats['date_range']}")

    # Total Return
    r = stats['total_return']
    print(f"\n{'TOTAL RETURN':=^60}")
    print(f"  Mean:       {r['mean']:>+8.1%}  (std: {r['std']:.1%})")
    print(f"  Median:     {r['median']:>+8.1%}")
    print(f"  Range:      {r['min']:>+8.1%} to {r['max']:>+8.1%}")
    print(f"  10th-90th:  {r['p10']:>+8.1%} to {r['p90']:>+8.1%}")
    print(f"  25th-75th:  {r['p25']:>+8.1%} to {r['p75']:>+8.1%}")

    # CAGR
    c = stats['cagr']
    print(f"\n{'CAGR (Annualized Return)':=^60}")
    print(f"  Mean:       {c['mean']:>+8.1%}  (std: {c['std']:.1%})")
    print(f"  Median:     {c['median']:>+8.1%}")
    print(f"  Range:      {c['min']:>+8.1%} to {c['max']:>+8.1%}")
    print(f"  10th-90th:  {c['p10']:>+8.1%} to {c['p90']:>+8.1%}")

    # Max Drawdown
    d = stats['max_drawdown']
    print(f"\n{'MAX DRAWDOWN':=^60}")
    print(f"  Mean:       {d['mean']:>8.1%}")
    print(f"  Median:     {d['median']:>8.1%}")
    print(f"  Best:       {d['best']:>8.1%}")
    print(f"  Worst:      {d['worst']:>8.1%}")

    # Win Rate
    w = stats['win_rate']
    print(f"\n{'WIN RATE':=^60}")
    print(f"  Mean:       {w['mean']:>8.1%}  (std: {w['std']:.1%})")
    print(f"  Range:      {w['min']:>8.1%} to {w['max']:>8.1%}")

    # Trades
    t = stats['trades']
    print(f"\n{'TRADES':=^60}")
    print(f"  Mean:       {t['mean']:>8.0f}")
    print(f"  Range:      {t['min']:>8.0f} to {t['max']:>8.0f}")

    # Profit Factor
    pf = stats['profit_factor']
    print(f"\n{'PROFIT FACTOR':=^60}")
    print(f"  Mean:       {pf['mean']:>8.2f}")
    print(f"  Median:     {pf['median']:>8.2f}")

    # Individual runs table
    print(f"\n{'INDIVIDUAL SIMULATION RUNS':=^100}")
    print(f"{'Start Date':<12} {'Return':>10} {'CAGR':>8} {'MaxDD':>8} {'Trades':>8} {'Win%':>8} {'Final$':>12}")
    print("-" * 70)

    for run in sorted(results, key=lambda x: x.start_date):
        print(f"{run.start_date:<12} {run.total_return:>+9.1%} {run.cagr:>+7.1%} "
              f"{run.max_drawdown:>7.1%} {run.total_trades:>8} {run.win_rate:>7.1%} "
              f"${run.final_value:>10,.0f}")

    # Robustness assessment
    print(f"\n{'ROBUSTNESS ASSESSMENT':=^100}")

    # Check if all runs are profitable
    profitable_runs = sum(1 for r in results if r.total_return > 0)
    pct_profitable = profitable_runs / len(results)
    print(f"  Profitable simulations: {profitable_runs}/{len(results)} ({pct_profitable:.1%})")

    # Check consistency (low std relative to mean)
    if r['mean'] > 0:
        cv = r['std'] / r['mean']  # Coefficient of variation
        consistency = "HIGH" if cv < 0.5 else "MEDIUM" if cv < 1.0 else "LOW"
        print(f"  Return consistency: {consistency} (CV = {cv:.2f})")

    # Check worst case
    worst_return = r['min']
    if worst_return > 0:
        print(f"  Worst case still profitable: YES ({worst_return:+.1%})")
    else:
        print(f"  Worst case still profitable: NO ({worst_return:+.1%})")

    # Risk-adjusted assessment
    if c['mean'] > 0 and d['mean'] > 0:
        return_to_dd = c['mean'] / d['mean']
        print(f"  Return/Drawdown ratio: {return_to_dd:.2f}")


def save_results(stats: Dict, results: List[SimulationRun], output_file: Path) -> None:
    """Save results to JSON file."""

    output = {
        'generated_at': datetime.now().isoformat(),
        'statistics': {
            k: v for k, v in stats.items() if k != 'individual_runs'
        },
        'individual_runs': [
            {
                'start_date': r.start_date,
                'end_date': r.end_date,
                'total_return': r.total_return,
                'cagr': r.cagr,
                'max_drawdown': r.max_drawdown,
                'total_trades': r.total_trades,
                'win_rate': r.win_rate,
                'avg_win': r.avg_win,
                'avg_loss': r.avg_loss,
                'profit_factor': r.profit_factor,
                'final_value': r.final_value,
                'stop_loss_count': r.stop_loss_count,
                'time_exit_count': r.time_exit_count,
            }
            for r in results
        ],
    }

    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Monte Carlo simulation to test strategy robustness across different start dates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run with defaults (6-8 week gaps, 2023-2025):
    python monte_carlo_simulation.py

  Run with specific dataset and stop loss:
    python monte_carlo_simulation.py --dataset 1b --stop-loss 0.60

  Run with custom gap between start dates:
    python monte_carlo_simulation.py --min-gap 4 --max-gap 6
        """
    )

    parser.add_argument("--dataset", type=str, choices=['1b', 'micro-small', 'small-cap'],
                        default='1b', help="Which dataset to use (default: 1b)")
    parser.add_argument("--stop-loss", type=float, default=0.60,
                        help="Stop loss percentage (default: 0.60 for -60%%)")
    parser.add_argument("--holding-period", type=int, default=365,
                        help="Holding period in days (default: 365 for 12M)")
    parser.add_argument("--min-gap", type=int, default=6,
                        help="Minimum weeks between start dates (default: 6)")
    parser.add_argument("--max-gap", type=int, default=8,
                        help="Maximum weeks between start dates (default: 8)")
    parser.add_argument("--start-year", type=int, default=2023,
                        help="First year for start dates (default: 2023)")
    parser.add_argument("--end-year", type=int, default=2025,
                        help="Last year for start dates (default: 2025)")
    parser.add_argument("--capital", type=float, default=100000,
                        help="Initial capital (default: 100000)")
    parser.add_argument("--min-score", type=int, default=5,
                        help="Minimum signal score (default: 5)")
    parser.add_argument("--max-score", type=int, default=7,
                        help="Maximum signal score (default: 7)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility (default: 42)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path (default: auto-generated)")

    args = parser.parse_args()

    # Dataset paths
    datasets = {
        '1b': DATA_DIR / "signals_history_1b_2023.json",
        'micro-small': DATA_DIR / "signals_history_micro_small.json",
        'small-cap': DATA_DIR / "signals_history_small_cap.json",
    }

    signals_file = datasets[args.dataset]
    if not signals_file.exists():
        print(f"Error: Signals file not found: {signals_file}")
        return

    # Generate start dates
    print("=" * 100)
    print("MONTE CARLO PORTFOLIO SIMULATION")
    print("=" * 100)
    print(f"\nConfiguration:")
    print(f"  Dataset:        {args.dataset}")
    print(f"  Signals file:   {signals_file}")
    print(f"  Holding period: {args.holding_period} days")
    print(f"  Stop loss:      -{args.stop_loss:.0%}")
    print(f"  Score range:    {args.min_score}-{args.max_score}")
    print(f"  Initial capital: ${args.capital:,.0f}")
    print(f"  Start date gap: {args.min_gap}-{args.max_gap} weeks")
    print(f"  Year range:     {args.start_year}-{args.end_year}")

    start_dates = generate_start_dates(
        start_year=args.start_year,
        end_year=args.end_year,
        min_gap_weeks=args.min_gap,
        max_gap_weeks=args.max_gap,
        seed=args.seed,
    )

    print(f"\nGenerated {len(start_dates)} start dates:")
    print(f"  First: {start_dates[0]}")
    print(f"  Last:  {start_dates[-1]}")

    # Run simulations
    print(f"\nRunning {len(start_dates)} simulations...")

    results = run_monte_carlo(
        signals_file=signals_file,
        start_dates=start_dates,
        holding_days=args.holding_period,
        stop_loss=args.stop_loss,
        initial_capital=args.capital,
        min_score=args.min_score,
        max_score=args.max_score,
    )

    if not results:
        print("Error: No simulation results generated")
        return

    # Calculate statistics
    stats = calculate_statistics(results)

    # Print results
    print_results(stats, results)

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    if args.output:
        output_file = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = RESULTS_DIR / f"monte_carlo_{args.dataset}_{timestamp}.json"

    save_results(stats, results, output_file)


if __name__ == "__main__":
    main()
