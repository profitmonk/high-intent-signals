#!/usr/bin/env python3
"""
Generate Portfolio Data for Jekyll Visualization

Runs portfolio simulation and exports JSON data for the Jekyll-based
GitHub Pages site. Outputs to docs/_data/portfolio_state.json for
use with Chart.js visualizations.

Usage:
    python generate_portfolio_data.py                    # Uses $1B+ dataset (default)
    python generate_portfolio_data.py --dataset small-cap
    python generate_portfolio_data.py --dataset micro-small
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from portfolio_simulator import (
    PortfolioSimulator,
    StrategyConfig,
    SimulationResult,
    DATASET_OPTIONS,
    DEFAULT_DATASET,
)


def calculate_monthly_returns(equity_curve: list) -> list:
    """Calculate monthly returns from weekly equity curve data."""
    if not equity_curve:
        return []

    # Group by month
    monthly_values = defaultdict(list)
    for date_str, value in equity_curve:
        month_key = date_str[:7]  # YYYY-MM
        monthly_values[month_key].append((date_str, value))

    # Calculate returns for each month
    monthly_returns = []
    sorted_months = sorted(monthly_values.keys())

    for i, month in enumerate(sorted_months):
        month_data = monthly_values[month]
        # Use last value of the month
        end_value = month_data[-1][1]

        if i == 0:
            # First month - use first value as start
            start_value = month_data[0][1]
        else:
            # Use previous month's last value
            prev_month = sorted_months[i - 1]
            start_value = monthly_values[prev_month][-1][1]

        if start_value > 0:
            monthly_return = (end_value - start_value) / start_value
        else:
            monthly_return = 0.0

        monthly_returns.append({
            "month": month,
            "return": round(monthly_return, 4),
        })

    return monthly_returns


def result_to_json(result: SimulationResult, dataset_name: str) -> dict:
    """Convert SimulationResult to JSON-serializable dict."""
    config = result.strategy

    # Build equity curve data
    equity_curve_data = [
        {"date": date, "value": round(value, 2)}
        for date, value in result.equity_curve
    ]

    # Build drawdown series data
    drawdown_data = [
        {"date": date, "drawdown": round(dd, 4)}
        for date, dd in result.drawdown_series
    ]

    # Build current holdings data
    holdings_data = []
    for pos in result.current_holdings:
        pnl_pct = 0.0
        if pos.entry_price > 0:
            pnl_pct = (pos.current_price - pos.entry_price) / pos.entry_price

        holdings_data.append({
            "ticker": pos.ticker,
            "entry_date": pos.entry_date,
            "entry_price": round(pos.entry_price, 2),
            "current_price": round(pos.current_price, 2),
            "shares": pos.shares,
            "cost_basis": round(pos.cost_basis, 2),
            "current_value": round(pos.shares * pos.current_price, 2),
            "pnl_pct": round(pnl_pct * 100, 2),
            "score": pos.score,
        })

    # Sort holdings by current value descending
    holdings_data.sort(key=lambda x: x["current_value"], reverse=True)

    # Build closed positions data (recent trades only, last 20)
    closed_data = []
    for pos in sorted(result.closed_positions, key=lambda x: x.exit_date, reverse=True)[:20]:
        closed_data.append({
            "ticker": pos.ticker,
            "entry_date": pos.entry_date,
            "exit_date": pos.exit_date,
            "entry_price": round(pos.entry_price, 2),
            "exit_price": round(pos.exit_price, 2),
            "pnl_pct": round(pos.pnl_pct * 100, 2),
            "holding_days": pos.holding_days,
            "exit_reason": pos.exit_reason,
            "score": pos.score,
        })

    # Calculate monthly returns
    monthly_returns = calculate_monthly_returns(result.equity_curve)

    return {
        "generated_at": datetime.now().isoformat(),
        "dataset": dataset_name,
        "simulation_config": {
            "initial_capital": config.initial_capital,
            "holding_period_days": config.holding_period_days,
            "stop_loss_pct": config.stop_loss_pct,
            "max_position_pct": config.max_position_pct,
            "max_positions": config.max_positions,
            "min_score": config.min_score,
            "max_score": config.max_score,
            "strategy_name": config.name,
        },
        "summary_metrics": {
            "final_value": round(result.final_value, 2),
            "total_return": round(result.total_return, 4),
            "cagr": round(result.cagr, 4),
            "max_drawdown": round(result.max_drawdown, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 2) if result.sharpe_ratio != float('inf') else 99.99,
            "sortino_ratio": round(result.sortino_ratio, 2) if result.sortino_ratio != float('inf') else 99.99,
            "win_rate": round(result.win_rate, 4),
            "profit_factor": round(result.profit_factor, 2) if result.profit_factor != float('inf') else 99.99,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "long_term_pct": round(result.long_term_pct, 4),
        },
        "equity_curve": equity_curve_data,
        "drawdown_series": drawdown_data,
        "current_holdings": holdings_data,
        "closed_positions": closed_data,
        "monthly_returns": monthly_returns,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate portfolio data for Jekyll visualization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Generate with $1B+ dataset (default, matches research paper):
    python generate_portfolio_data.py

  Generate with different dataset:
    python generate_portfolio_data.py --dataset small-cap
    python generate_portfolio_data.py --dataset micro-small

  Custom strategy parameters:
    python generate_portfolio_data.py --stop-loss 0.50 --min-score 6
        """
    )
    parser.add_argument(
        "--dataset",
        type=str,
        choices=list(DATASET_OPTIONS.keys()),
        default=DEFAULT_DATASET,
        help=f"Dataset to use (default: {DEFAULT_DATASET})"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="Score 5-7, 12M Hold",
        help="Strategy name (default: 'Score 5-7, 12M Hold')"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="docs/_data/portfolio_state.json",
        help="Output path (default: docs/_data/portfolio_state.json)"
    )
    parser.add_argument(
        "--holding-days",
        type=int,
        default=365,
        help="Holding period in days (default: 365)"
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=0.60,
        help="Stop loss percentage (default: 0.60 = 60%%)"
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=5,
        help="Minimum signal score (default: 5)"
    )
    parser.add_argument(
        "--max-score",
        type=int,
        default=7,
        help="Maximum signal score (default: 7)"
    )

    args = parser.parse_args()

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get signals file for selected dataset
    dataset_name, signals_path = DATASET_OPTIONS[args.dataset]
    print(f"\nDataset: {dataset_name}")
    print(f"Signals file: {signals_path}")

    # Create simulator and load data
    sim = PortfolioSimulator()

    if not signals_path.exists():
        raise FileNotFoundError(f"Signals file not found: {signals_path}")

    with open(signals_path) as f:
        sim.signals = json.load(f)
    sim.signals.sort(key=lambda x: x.get('entry_date', x.get('signal_date', '')))
    print(f"Loaded {len(sim.signals)} signals")

    # Load price cache
    sim._load_price_cache()

    # Create strategy configuration
    config = StrategyConfig(
        name=args.strategy,
        initial_capital=100_000,
        holding_period_days=args.holding_days,
        stop_loss_pct=args.stop_loss,
        max_position_pct=0.04,
        max_positions=40,
        min_score=args.min_score,
        max_score=args.max_score,
    )

    # Run simulation
    print(f"Running simulation: {config.name}")
    result = sim.run_simulation(config)

    # Convert to JSON
    print("Converting results to JSON...")
    data = result_to_json(result, dataset_name)

    # Write output
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\nPortfolio data written to: {output_path}")
    print(f"\nSummary ({dataset_name}):")
    print(f"  Final Value:    ${data['summary_metrics']['final_value']:,.0f}")
    print(f"  Total Return:   {data['summary_metrics']['total_return']:.1%}")
    print(f"  CAGR:           {data['summary_metrics']['cagr']:.1%}")
    print(f"  Max Drawdown:   {data['summary_metrics']['max_drawdown']:.1%}")
    print(f"  Sharpe Ratio:   {data['summary_metrics']['sharpe_ratio']:.2f}")
    print(f"  Sortino Ratio:  {data['summary_metrics']['sortino_ratio']:.2f}")
    print(f"  Win Rate:       {data['summary_metrics']['win_rate']:.1%}")
    print(f"  Equity Points:  {len(data['equity_curve'])}")
    print(f"  Holdings:       {len(data['current_holdings'])}")
    print(f"  Monthly Periods:{len(data['monthly_returns'])}")


if __name__ == "__main__":
    main()
