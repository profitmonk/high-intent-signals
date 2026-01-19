"""
Output formatter for scan reports.

Supports JSON, markdown, and console output formats.
"""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from scanner.scanner import ScanReport, ScanResult


class OutputFormat(Enum):
    """Supported output formats."""

    JSON = "json"
    MARKDOWN = "markdown"
    CONSOLE = "console"


class OutputFormatter:
    """Formats scan reports for various output destinations."""

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize the formatter.

        Args:
            output_dir: Directory for output files (default: reports/output)
        """
        self.output_dir = output_dir or Path("reports/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def format(
        self,
        report: ScanReport,
        format_type: OutputFormat = OutputFormat.JSON,
    ) -> str:
        """
        Format a scan report.

        Args:
            report: The scan report to format
            format_type: Output format type

        Returns:
            Formatted string
        """
        if format_type == OutputFormat.JSON:
            return self._format_json(report)
        elif format_type == OutputFormat.MARKDOWN:
            return self._format_markdown(report)
        elif format_type == OutputFormat.CONSOLE:
            return self._format_console(report)
        else:
            raise ValueError(f"Unknown format type: {format_type}")

    def save(
        self,
        report: ScanReport,
        format_type: OutputFormat = OutputFormat.JSON,
        filename: Optional[str] = None,
    ) -> Path:
        """
        Save a scan report to file.

        Args:
            report: The scan report to save
            format_type: Output format type
            filename: Custom filename (auto-generated if not provided)

        Returns:
            Path to the saved file
        """
        if filename is None:
            date_str = report.scan_date.replace("-", "")
            ext = "json" if format_type == OutputFormat.JSON else "md"
            filename = f"scan_{date_str}.{ext}"

        filepath = self.output_dir / filename
        content = self.format(report, format_type)

        with open(filepath, "w") as f:
            f.write(content)

        return filepath

    def _format_json(self, report: ScanReport) -> str:
        """Format as JSON."""
        return json.dumps(report.to_dict(), indent=2)

    def _format_markdown(self, report: ScanReport) -> str:
        """Format as markdown."""
        lines = [
            f"# High Intent Stock Scanner Report",
            f"",
            f"**Date:** {report.scan_date}",
            f"**Time:** {report.scan_time}",
            f"**Stocks Scanned:** {report.total_stocks_scanned}",
            f"**Signals Detected:** {report.signals_detected}",
            f"**Stocks with Signals:** {len(report.stocks)}",
            f"**Execution Time:** {report.execution_time_seconds:.1f}s",
            f"",
            f"---",
            f"",
        ]

        for i, stock in enumerate(report.stocks, 1):
            lines.extend(self._format_stock_markdown(stock, i))
            lines.append("")

        return "\n".join(lines)

    def _format_stock_markdown(self, stock: ScanResult, rank: int) -> List[str]:
        """Format a single stock as markdown."""
        change_str = f"+{stock.change_pct * 100:.1f}%" if stock.change_pct >= 0 else f"{stock.change_pct * 100:.1f}%"

        lines = [
            f"## {rank}. {stock.ticker} - {stock.company_name}",
            f"",
            f"**Price:** ${stock.price:.2f} ({change_str})",
            f"**Volume:** {stock.volume:,} ({stock.volume_vs_avg:.1f}x average)",
            f"**Distance to 52wk High:** {stock.distance_to_52wk_high_pct * 100:.1f}%",
            f"**Signal Score:** {stock.score}",
            f"",
            f"### Signals Detected",
            f"",
        ]

        for signal in stock.signals:
            emoji = self._get_signal_emoji(signal.signal_type.value)
            lines.append(f"- {emoji} **{signal.signal_type.value}** ({signal.strength}): {signal.description}")

        lines.append("")

        if stock.narrative:
            lines.extend([
                f"### Narrative",
                f"",
                stock.narrative,
                f"",
            ])

        if stock.news:
            lines.extend([
                f"### Recent News ({len(stock.news)} articles)",
                f"",
            ])
            for article in stock.news[:5]:
                title = article.get("title", "")
                date = article.get("publishedDate", "")[:10]
                lines.append(f"- [{title}] ({date})")
            lines.append("")

        lines.append("---")

        return lines

    def _format_console(self, report: ScanReport) -> str:
        """Format for console output."""
        lines = [
            "",
            "=" * 60,
            "HIGH INTENT STOCK SCANNER REPORT",
            "=" * 60,
            f"Date: {report.scan_date} {report.scan_time}",
            f"Stocks Scanned: {report.total_stocks_scanned}",
            f"Signals Detected: {report.signals_detected}",
            f"Execution Time: {report.execution_time_seconds:.1f}s",
            "=" * 60,
            "",
        ]

        if not report.stocks:
            lines.append("No stocks with high-intent signals detected.")
            return "\n".join(lines)

        for i, stock in enumerate(report.stocks[:20], 1):  # Limit console output to top 20
            lines.extend(self._format_stock_console(stock, i))
            lines.append("")

        if len(report.stocks) > 20:
            lines.append(f"... and {len(report.stocks) - 20} more stocks")

        return "\n".join(lines)

    def _format_stock_console(self, stock: ScanResult, rank: int) -> List[str]:
        """Format a single stock for console."""
        change_str = f"+{stock.change_pct * 100:.1f}%" if stock.change_pct >= 0 else f"{stock.change_pct * 100:.1f}%"

        # Build signal string
        signal_strs = []
        for signal in stock.signals:
            emoji = self._get_signal_emoji(signal.signal_type.value)
            signal_strs.append(f"{emoji}{signal.signal_type.value}")

        signals = " | ".join(signal_strs)

        lines = [
            f"{rank:2}. {stock.ticker:6} ${stock.price:>8.2f} ({change_str:>7}) Score: {stock.score}",
            f"    {stock.company_name[:40]}",
            f"    Signals: {signals}",
        ]

        if stock.narrative:
            # Truncate narrative for console
            narrative = stock.narrative[:200] + "..." if len(stock.narrative) > 200 else stock.narrative
            lines.append(f"    {narrative}")

        return lines

    def _get_signal_emoji(self, signal_type: str) -> str:
        """Get emoji for signal type."""
        emojis = {
            "ATH_BREAKOUT": "🚀",
            "VOLUME_SPIKE": "📊",
            "GAP_UP": "⬆️",
            "MOMENTUM": "💪",
            "SMA_CROSSOVER": "📈",
            "TREND_REVERSAL": "🔄",
        }
        return emojis.get(signal_type, "•")


def print_report(report: ScanReport) -> None:
    """Convenience function to print report to console."""
    formatter = OutputFormatter()
    print(formatter.format(report, OutputFormat.CONSOLE))


def save_report(
    report: ScanReport,
    output_dir: Optional[Path] = None,
    formats: List[OutputFormat] = None,
) -> List[Path]:
    """
    Convenience function to save report in multiple formats.

    Args:
        report: The scan report
        output_dir: Output directory
        formats: List of formats to save (default: JSON and Markdown)

    Returns:
        List of saved file paths
    """
    formats = formats or [OutputFormat.JSON, OutputFormat.MARKDOWN]
    formatter = OutputFormatter(output_dir)

    paths = []
    for fmt in formats:
        path = formatter.save(report, fmt)
        paths.append(path)

    return paths
