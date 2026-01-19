#!/usr/bin/env python3
"""
Historical Signal Scanner - Scan for signals in historical data.

Downloads 3 years of weekly data for all US stocks > $5B market cap
and identifies when high-intent signals occurred.

Usage:
    # High-intent signals (score >= 4) from last 30 days (RECOMMENDED)
    python scan_historical.py --high-intent --recent 30

    # Adjust minimum score threshold
    python scan_historical.py --high-intent --min-score 5 --recent 30

    # Full universe scan (downloads data, calculates signals)
    python scan_historical.py

    # Show signals for specific ticker
    python scan_historical.py --ticker AAPL

    # Force refresh (re-download all data)
    python scan_historical.py --refresh

    # Show summary statistics
    python scan_historical.py --summary

Scoring System:
    - New ATH (actual breakout): 3 points
    - Volume >= 5x average: 3 points
    - Volume >= 3x average: 2 points
    - Momentum >= 15% weekly: 2 points
    - Momentum 10-15% weekly: 1 point
    - SMA200 crossover: 2 points
    - SMA50 crossover: 1 point
    - Confluence bonus (2+ signal types): +1 point
"""

import argparse
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, BarColumn

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from scanner.historical import HistoricalScanner, HistoricalConfig, HistoricalSignal, ScoredStockWeek
from utils.logging import setup_logging, get_logger

console = Console()
logger = get_logger("historical")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan historical data for high-intent signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mode
    parser.add_argument(
        "--high-intent", "-H",
        action="store_true",
        help="Show high-intent signals with composite scoring (recommended)",
    )
    parser.add_argument(
        "--ticker", "-t",
        type=str,
        help="Show signals for specific ticker",
    )
    parser.add_argument(
        "--recent", "-r",
        type=int,
        default=0,
        help="Show signals from last N days (default: all)",
    )
    parser.add_argument(
        "--summary", "-s",
        action="store_true",
        help="Show summary statistics only",
    )

    # Data options
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force refresh (re-download all data)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=3,
        help="Years of historical data (default: 3)",
    )
    parser.add_argument(
        "--min-market-cap",
        type=float,
        default=5.0,
        help="Minimum market cap in billions (default: 5.0)",
    )

    # Signal filters
    parser.add_argument(
        "--min-score",
        type=int,
        default=4,
        help="Minimum composite score for high-intent mode (default: 4)",
    )
    parser.add_argument(
        "--signal-type",
        type=str,
        help="Filter by signal type (e.g., ATH_BREAKOUT, VOLUME_SPIKE, SMA50_CROSSOVER)",
    )
    parser.add_argument(
        "--min-strength",
        choices=["weak", "moderate", "strong"],
        default="weak",
        help="Minimum signal strength for raw mode (default: weak)",
    )

    # Output
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max signals to display (default: 50)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )

    return parser.parse_args()


def display_high_intent_table(scored_weeks: list, title: str = "High Intent Signals"):
    """Display scored stock-weeks in a table."""
    if not scored_weeks:
        console.print("[yellow]No high-intent signals found matching criteria.[/yellow]")
        return

    table = Table(title=title)
    table.add_column("Date", style="dim", width=12)
    table.add_column("Ticker", style="cyan bold", width=8)
    table.add_column("Score", justify="center", width=7)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Change", justify="right", width=8)
    table.add_column("Signals", width=45)

    for sw in scored_weeks:
        change_str = f"{sw.change_pct * 100:+.1f}%" if sw.change_pct else ""
        change_style = "green" if sw.change_pct and sw.change_pct > 0 else "red"

        # Color score based on value
        if sw.total_score >= 6:
            score_style = "bold green"
        elif sw.total_score >= 5:
            score_style = "green"
        elif sw.total_score >= 4:
            score_style = "yellow"
        else:
            score_style = "dim"

        # Format signal summary
        signal_summary = sw.signal_summary
        if sw.has_confluence:
            signal_summary += " [dim](+confluence)[/dim]"

        table.add_row(
            sw.date,
            sw.ticker,
            f"[{score_style}]{sw.total_score}[/{score_style}]",
            f"${sw.price:.2f}",
            f"[{change_style}]{change_str}[/{change_style}]",
            signal_summary,
        )

    console.print(table)


def display_high_intent_summary(summary: dict):
    """Display high-intent summary statistics."""
    console.print(Panel(
        f"[bold]High Intent Signal Summary[/bold]\n\n"
        f"Total High Intent Signals: {summary['total_high_intent']:,}\n"
        f"Minimum Score: {summary['min_score']}\n"
        f"Time Period: Last {summary['days']} days\n"
        f"With Confluence: {summary['with_confluence']:,}\n"
        f"Without Confluence: {summary['without_confluence']:,}",
        expand=False,
    ))

    # Score distribution
    console.print("\n[bold]Score Distribution:[/bold]")
    score_table = Table(show_header=False)
    score_table.add_column("Score", width=10)
    score_table.add_column("Count", justify="right", width=10)
    for score, count in summary["score_distribution"].items():
        score_table.add_row(f"Score {score}", f"{count:,}")
    console.print(score_table)

    # By signal type
    console.print("\n[bold]By Signal Type:[/bold]")
    for sig_type, count in sorted(summary["by_signal_type"].items(), key=lambda x: x[1], reverse=True):
        console.print(f"  {sig_type}: {count:,}")

    # Top tickers
    console.print("\n[bold]Top Tickers by Score:[/bold]")
    for ticker, info in summary["top_tickers"][:15]:
        console.print(f"  {ticker}: max score {info['max_score']}, {info['count']} instance(s)")


def display_signals_table(signals: list, title: str = "Historical Signals"):
    """Display raw signals in a table."""
    if not signals:
        console.print("[yellow]No signals found matching criteria.[/yellow]")
        return

    table = Table(title=title)
    table.add_column("Date", style="dim", width=12)
    table.add_column("Ticker", style="cyan", width=8)
    table.add_column("Signal", width=18)
    table.add_column("Strength", width=10)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Change", justify="right", width=8)
    table.add_column("Description", width=40)

    for signal in signals:
        change_str = f"{signal.change_pct * 100:+.1f}%" if signal.change_pct else ""
        change_style = "green" if signal.change_pct and signal.change_pct > 0 else "red"

        strength_style = {
            "strong": "bold green",
            "moderate": "yellow",
            "weak": "dim",
        }.get(signal.strength, "")

        table.add_row(
            signal.date,
            signal.ticker,
            signal.signal_type,
            f"[{strength_style}]{signal.strength}[/{strength_style}]",
            f"${signal.price:.2f}",
            f"[{change_style}]{change_str}[/{change_style}]",
            signal.description[:40] + "..." if len(signal.description) > 40 else signal.description,
        )

    console.print(table)


def display_summary(summary: dict):
    """Display summary statistics."""
    console.print(Panel(
        f"[bold]Historical Signal Summary[/bold]\n\n"
        f"Total Signals: {summary['total_signals']:,}\n"
        f"Date Range: {summary['date_range']['start']} to {summary['date_range']['end']}\n"
        f"Last 30 Days: {summary['last_30_days']['total']:,} signals",
        expand=False,
    ))

    # By type
    console.print("\n[bold]Signals by Type:[/bold]")
    type_table = Table(show_header=False)
    type_table.add_column("Type", width=20)
    type_table.add_column("Count", justify="right", width=10)
    for sig_type, count in sorted(summary["by_type"].items(), key=lambda x: x[1], reverse=True):
        type_table.add_row(sig_type, f"{count:,}")
    console.print(type_table)

    # By strength
    console.print("\n[bold]Signals by Strength:[/bold]")
    for strength, count in summary["by_strength"].items():
        console.print(f"  {strength}: {count:,}")

    # Top tickers
    console.print("\n[bold]Top Tickers (Last 30 Days):[/bold]")
    for ticker, count in summary["last_30_days"]["top_tickers"][:10]:
        console.print(f"  {ticker}: {count} signals")


async def run_historical_scan(args: argparse.Namespace):
    """Run the historical scan."""

    config = HistoricalConfig(
        years_of_data=args.years,
        min_market_cap=int(args.min_market_cap * 1_000_000_000),
        resample_to_weekly=True,
    )

    scanner = HistoricalScanner(config)

    try:
        # Check if we need to run full scan
        if args.refresh or not (config.cache_dir / "all_signals.json").exists():
            console.print(Panel(
                f"[bold blue]Historical Signal Scanner[/bold blue]\n\n"
                f"Years of data: {args.years}\n"
                f"Min market cap: ${args.min_market_cap}B\n"
                f"Timeframe: Weekly",
                expand=False,
            ))

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("[cyan]Downloading and analyzing...", total=None)

                signals = await scanner.scan_universe(
                    max_concurrent=10,
                    force_refresh=args.refresh,
                )

                progress.update(task, completed=100, total=100)

            console.print(f"\n[green]Scan complete. {len(signals):,} signals detected.[/green]")
        else:
            # Load from cache
            console.print("[dim]Loading signals from cache...[/dim]")
            signals = await scanner.scan_universe(force_refresh=False)

        # HIGH INTENT MODE
        if args.high_intent:
            days = args.recent if args.recent > 0 else 30  # Default to 30 days for high intent

            if args.summary:
                summary = await scanner.get_high_intent_summary(
                    min_score=args.min_score,
                    days=days,
                )
                display_high_intent_summary(summary)
                return

            scored_weeks = await scanner.get_high_intent_signals(
                min_score=args.min_score,
                days=days,
                ticker=args.ticker,
            )

            title = f"High Intent Signals (Score >= {args.min_score}, Last {days} Days)"
            if args.ticker:
                title = f"High Intent: {args.ticker.upper()} (Score >= {args.min_score})"

            # Limit output
            total = len(scored_weeks)
            scored_weeks = scored_weeks[:args.limit]

            console.print()
            display_high_intent_table(scored_weeks, title)

            if len(scored_weeks) == args.limit and total > args.limit:
                console.print(f"\n[dim](Showing {args.limit} of {total} signals. Use --limit to see more.)[/dim]")

            return

        # RAW SIGNALS MODE (legacy)
        if args.summary:
            summary = await scanner.get_signal_summary()
            display_summary(summary)
            return

        # Filter signals
        if args.ticker:
            signals = [s for s in signals if s.ticker == args.ticker.upper()]
            title = f"Signals for {args.ticker.upper()}"
        elif args.recent > 0:
            cutoff = (datetime.now() - timedelta(days=args.recent)).strftime("%Y-%m-%d")
            signals = [s for s in signals if s.date >= cutoff]
            title = f"Signals (Last {args.recent} Days)"
        else:
            title = "All Historical Signals"

        # Filter by type
        if args.signal_type:
            signals = [s for s in signals if args.signal_type.upper() in s.signal_type]
            title += f" [{args.signal_type}]"

        # Filter by strength
        strength_order = {"weak": 1, "moderate": 2, "strong": 3}
        min_strength = strength_order.get(args.min_strength, 1)
        signals = [s for s in signals if strength_order.get(s.strength, 0) >= min_strength]

        # Limit output
        signals = signals[:args.limit]

        console.print()
        display_signals_table(signals, title)

        if len(signals) == args.limit:
            console.print(f"\n[dim](Showing first {args.limit} signals. Use --limit to see more.)[/dim]")

    finally:
        await scanner.close()


def main():
    args = parse_args()

    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)

    try:
        asyncio.run(run_historical_scan(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
