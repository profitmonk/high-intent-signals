#!/usr/bin/env python3
"""
High Intent Stock Signal Scanner - Main Entry Point

Identifies stocks showing high-intent trading signals and synthesizes news narratives.

Usage:
    # Run daily scan (market movers)
    python main.py

    # Scan specific tickers
    python main.py --tickers AAPL,MSFT,GOOGL

    # Scan full S&P 500
    python main.py --sp500

    # Custom thresholds
    python main.py --volume-threshold 3.0 --ath-threshold 0.98

    # Skip news synthesis (faster)
    python main.py --no-synthesis
"""

import argparse
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import get_settings
from scanner.scanner import StockScanner, ScanReport
from scanner.signals import SignalConfig
from synthesis.news_synthesizer import NewsSynthesizer
from output.formatter import OutputFormatter, OutputFormat, print_report, save_report
from utils.logging import setup_logging, get_logger


console = Console()
logger = get_logger("main")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Scan for high-intent stock signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py                           # Scan market movers
    python main.py --tickers AAPL,MSFT       # Scan specific stocks
    python main.py --sp500                   # Scan all S&P 500
    python main.py --volume-threshold 3.0    # Custom volume threshold
    python main.py --no-synthesis            # Skip LLM narrative generation
        """,
    )

    # Scan target
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--tickers", "-t",
        type=str,
        help="Comma-separated list of tickers to scan (e.g., AAPL,MSFT,GOOGL)",
    )
    target_group.add_argument(
        "--sp500",
        action="store_true",
        help="Scan all S&P 500 stocks (slower, more comprehensive)",
    )

    # Signal thresholds
    parser.add_argument(
        "--ath-threshold",
        type=float,
        default=0.95,
        help="ATH threshold (0-1, default: 0.95 = within 5%% of 52wk high)",
    )
    parser.add_argument(
        "--volume-threshold",
        type=float,
        default=2.0,
        help="Volume spike threshold (multiplier, default: 2.0 = 2x average)",
    )
    parser.add_argument(
        "--gap-threshold",
        type=float,
        default=0.05,
        help="Gap up threshold (0-1, default: 0.05 = 5%% gap)",
    )
    parser.add_argument(
        "--gain-threshold",
        type=float,
        default=0.03,
        help="Daily gain threshold (0-1, default: 0.03 = 3%% gain)",
    )

    # Processing options
    parser.add_argument(
        "--no-synthesis",
        action="store_true",
        help="Skip LLM narrative synthesis (faster, just signals + news)",
    )
    parser.add_argument(
        "--no-technicals",
        action="store_true",
        help="Skip fetching additional technical indicators",
    )
    parser.add_argument(
        "--no-news",
        action="store_true",
        help="Skip fetching news articles",
    )

    # Output options
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output file path (auto-generated if not specified)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "markdown", "console"],
        default="console",
        help="Output format (default: console)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save report to file (JSON and Markdown)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/output"),
        help="Output directory for saved reports",
    )

    # Logging
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress non-essential output",
    )

    return parser.parse_args()


def get_tickers_from_args(args: argparse.Namespace) -> Optional[List[str]]:
    """Get list of tickers from arguments."""
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",")]
    return None  # None means use market movers


async def run_scan(args: argparse.Namespace) -> ScanReport:
    """Run the scan with given arguments."""
    settings = get_settings()

    # Build signal config from args
    signal_config = SignalConfig(
        ath_threshold_pct=args.ath_threshold,
        volume_spike_multiplier=args.volume_threshold,
        gap_up_threshold_pct=args.gap_threshold,
        daily_gain_threshold_pct=args.gain_threshold,
    )

    # Initialize scanner
    scanner = StockScanner(signal_config=signal_config)

    try:
        # Determine scan target
        tickers = get_tickers_from_args(args)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            # Run scan
            if args.sp500:
                progress.add_task("[cyan]Scanning S&P 500 stocks...", total=None)
                report = await scanner.run_full_scan(
                    tickers=None,  # Will fetch S&P 500 list
                    include_technicals=not args.no_technicals,
                    include_news=not args.no_news,
                )
                # Actually need to use scan_sp500
                results = await scanner.scan_sp500()
            elif tickers:
                progress.add_task(f"[cyan]Scanning {len(tickers)} tickers...", total=None)
                report = await scanner.run_full_scan(
                    tickers=tickers,
                    include_technicals=not args.no_technicals,
                    include_news=not args.no_news,
                )
            else:
                progress.add_task("[cyan]Scanning market movers...", total=None)
                report = await scanner.run_full_scan(
                    tickers=None,
                    include_technicals=not args.no_technicals,
                    include_news=not args.no_news,
                )

        # Run synthesis if requested
        if not args.no_synthesis and report.stocks:
            console.print("[cyan]Synthesizing narratives...[/cyan]")
            synthesizer = NewsSynthesizer(settings)

            # Convert ScanResults to dicts for synthesizer
            stocks_data = []
            for stock in report.stocks:
                stocks_data.append({
                    "ticker": stock.ticker,
                    "company": stock.company_name,
                    "price": stock.price,
                    "change_pct": stock.change_pct * 100,  # Convert to percentage
                    "signals": [s.signal_type.value for s in stock.signals],
                    "signal_details": [
                        {"type": s.signal_type.value, "strength": s.strength, "description": s.description}
                        for s in stock.signals
                    ],
                    "news": stock.news,
                })

            # Synthesize
            enriched = await synthesizer.synthesize_batch(stocks_data, max_concurrent=5)

            # Update report with narratives
            for i, stock in enumerate(report.stocks):
                if i < len(enriched):
                    stock.narrative = enriched[i].get("narrative", "")

        return report

    finally:
        await scanner.close()


def display_results(report: ScanReport, args: argparse.Namespace) -> None:
    """Display results based on format."""
    format_map = {
        "json": OutputFormat.JSON,
        "markdown": OutputFormat.MARKDOWN,
        "console": OutputFormat.CONSOLE,
    }

    output_format = format_map.get(args.format, OutputFormat.CONSOLE)
    formatter = OutputFormatter(args.output_dir)

    if args.format == "console":
        print_report(report)
    else:
        output = formatter.format(report, output_format)
        console.print(output)

    # Save if requested
    if args.save:
        paths = save_report(report, args.output_dir)
        console.print(f"\n[green]Saved reports:[/green]")
        for path in paths:
            console.print(f"  - {path}")


def display_summary_table(report: ScanReport) -> None:
    """Display a summary table of detected signals."""
    if not report.stocks:
        console.print("[yellow]No high-intent signals detected.[/yellow]")
        return

    table = Table(title="High Intent Signals Detected")
    table.add_column("Rank", style="dim", width=4)
    table.add_column("Ticker", style="cyan", width=6)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Change", justify="right", width=8)
    table.add_column("Volume", justify="right", width=8)
    table.add_column("Signals", width=30)
    table.add_column("Score", justify="right", width=5)

    for i, stock in enumerate(report.stocks[:20], 1):
        change_str = f"+{stock.change_pct * 100:.1f}%" if stock.change_pct >= 0 else f"{stock.change_pct * 100:.1f}%"
        change_style = "green" if stock.change_pct >= 0 else "red"

        signals = ", ".join(s.signal_type.value for s in stock.signals[:3])
        if len(stock.signals) > 3:
            signals += f" +{len(stock.signals) - 3}"

        table.add_row(
            str(i),
            stock.ticker,
            f"${stock.price:.2f}",
            f"[{change_style}]{change_str}[/{change_style}]",
            f"{stock.volume_vs_avg:.1f}x",
            signals,
            str(stock.score),
        )

    console.print(table)

    if len(report.stocks) > 20:
        console.print(f"\n[dim]... and {len(report.stocks) - 20} more stocks with signals[/dim]")


async def main_async(args: argparse.Namespace) -> int:
    """Async main function."""
    console.print(Panel(
        "[bold blue]High Intent Stock Signal Scanner[/bold blue]\n\n"
        f"Mode: {'S&P 500' if args.sp500 else 'Specific tickers' if args.tickers else 'Market Movers'}\n"
        f"Synthesis: {'Disabled' if args.no_synthesis else 'Enabled'}\n"
        f"Thresholds: ATH={args.ath_threshold}, Vol={args.volume_threshold}x",
        expand=False,
    ))

    start_time = datetime.now()

    try:
        # Run scan
        report = await run_scan(args)

        # Display results
        duration = (datetime.now() - start_time).total_seconds()

        console.print()
        console.print(f"[bold]Scan Complete[/bold]")
        console.print(f"Stocks scanned: {report.total_stocks_scanned}")
        console.print(f"Signals detected: {report.signals_detected}")
        console.print(f"Stocks with signals: {len(report.stocks)}")
        console.print(f"Execution time: {duration:.1f}s")
        console.print()

        # Show summary table
        display_summary_table(report)

        # Full output if requested
        if args.format != "console" or args.save:
            console.print()
            display_results(report, args)

        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Scan interrupted by user[/yellow]")
        return 130

    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        logger.exception("Scan failed")
        return 1


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    log_level = "DEBUG" if args.verbose else ("WARNING" if args.quiet else "INFO")
    setup_logging(level=log_level)

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
