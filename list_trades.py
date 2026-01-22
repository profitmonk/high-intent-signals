#!/usr/bin/env python3
"""
List all trades from portfolio simulation.

Usage:
    python list_trades.py                           # Run all datasets
    python list_trades.py --dataset 1b              # Run $1B+ only
    python list_trades.py --dataset micro-small     # Run micro-small only
    python list_trades.py --dataset small-cap       # Run small-cap only
"""

import argparse
import sys
from pathlib import Path
from portfolio_simulator import PortfolioSimulator, StrategyConfig, SIGNALS_DB_PATH
import shutil


def run_for_dataset(dataset_name: str, dataset_path: Path, stop_loss: float = 0.25, holding_days: int = 365) -> dict:
    """Run simulation for a dataset and return results."""
    # Copy dataset to signals_history.json
    shutil.copy(dataset_path, SIGNALS_DB_PATH)

    sim = PortfolioSimulator()
    sim.load_signals()

    # Run strategy with moderate scores
    hold_label = f"{holding_days//30}M" if holding_days >= 30 else f"{holding_days}D"
    config = StrategyConfig(
        name=f"Moderate (5-7) {hold_label} - {dataset_name}",
        holding_period_days=holding_days,
        stop_loss_pct=stop_loss,
        max_position_pct=0.04,
        max_positions=40,
        min_score=5,
        max_score=7,
        initial_capital=100000,
    )

    result = sim.run_simulation(config)
    trades = sorted(result.closed_positions, key=lambda x: x.entry_date)

    # Print summary
    hold_label = f"{holding_days//30}M" if holding_days >= 30 else f"{holding_days}D"
    print(f"\n{'='*100}")
    print(f"TRADE LIST: {dataset_name} | {hold_label} Hold | Stop Loss: -{stop_loss:.0%}")
    print(f"{'='*100}")
    print(f"Total trades: {len(trades)}")
    print(f"Winners: {result.winning_trades} | Losers: {result.losing_trades} | Win Rate: {result.win_rate:.1%}")
    print(f"Final Value: ${result.final_value:,.0f} | Total Return: {result.total_return:+.1%} | CAGR: {result.cagr:+.1%}")
    print(f"Max Drawdown: {result.max_drawdown:.1%}")

    # Exit breakdown
    from collections import Counter
    exits = Counter(t.exit_reason for t in trades)
    print(f"\nExit Breakdown:")
    for reason, count in exits.most_common():
        print(f"  {reason}: {count} ({count/len(trades)*100:.1f}%)")

    # Top 10 winners
    top_winners = sorted([t for t in trades if t.pnl > 0], key=lambda x: -x.pnl)[:10]
    print(f"\nTop 10 Winners:")
    for t in top_winners:
        print(f"  {t.ticker}: +${t.pnl:,.0f} ({t.pnl_pct:+.1%}) | {t.entry_date} -> {t.exit_date}")

    # Print all trades as CSV
    print(f"\nAll Trades (CSV):")
    print("Entry Date,Exit Date,Ticker,Score,Entry Price,Exit Price,Shares,Cost,Proceeds,P&L,P&L %,Days Held,Exit Reason")
    for t in trades:
        print(f"{t.entry_date},{t.exit_date},{t.ticker},{t.score},{t.entry_price:.2f},{t.exit_price:.2f},{t.shares},{t.cost_basis:.0f},{t.proceeds:.0f},{t.pnl:.0f},{t.pnl_pct:+.1%},{t.holding_days},{t.exit_reason}")

    return {
        'name': dataset_name,
        'result': result,
        'trades': trades,
    }


def main():
    parser = argparse.ArgumentParser(description="List trades from portfolio simulation")
    parser.add_argument("--dataset", type=str, choices=['1b', 'micro-small', 'small-cap', 'all'],
                        default='all', help="Which dataset to run")
    parser.add_argument("--stop-loss", type=float, default=0.25,
                        help="Stop loss percentage (default: 0.25 for -25%%)")
    parser.add_argument("--holding-period", type=int, default=365,
                        help="Holding period in days (default: 365 for 12M)")
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

    results = []
    for key in selected:
        name, path = datasets[key]
        if path.exists():
            result = run_for_dataset(name, path, args.stop_loss, args.holding_period)
            results.append(result)
        else:
            print(f"Skipping {name} - file not found: {path}")

    # Summary comparison
    if len(results) > 1:
        print(f"\n{'='*100}")
        print("SUMMARY COMPARISON")
        print(f"{'='*100}")
        print(f"{'Dataset':<30} {'Trades':>8} {'Win%':>8} {'Return':>12} {'CAGR':>10} {'MaxDD':>8}")
        print("-" * 80)
        for r in results:
            res = r['result']
            print(f"{r['name']:<30} {res.total_trades:>8} {res.win_rate:>7.1%} {res.total_return:>+11.1%} {res.cagr:>+9.1%} {res.max_drawdown:>7.1%}")


if __name__ == "__main__":
    main()
