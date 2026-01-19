"""
Main scanner class that orchestrates high-intent signal detection.

Coordinates FMP API calls, signal detection, and news aggregation.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from data.fmp_client import FMPClient
from scanner.signals import (
    Signal,
    SignalConfig,
    SignalDetector,
    SignalType,
    StockData,
    filter_by_signal_strength,
    rank_by_signal_strength,
)

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result for a single stock from the scanner."""

    ticker: str
    company_name: str
    sector: str
    price: float
    change_pct: float
    volume: int
    volume_vs_avg: float
    distance_to_52wk_high_pct: float
    signals: List[Signal]
    news: List[Dict[str, Any]] = field(default_factory=list)
    narrative: str = ""  # Filled by synthesis step
    score: int = 0  # Combined signal strength score

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "ticker": self.ticker,
            "company": self.company_name,
            "sector": self.sector,
            "price": self.price,
            "change_pct": round(self.change_pct * 100, 2),
            "volume": self.volume,
            "volume_vs_avg": round(self.volume_vs_avg, 2),
            "distance_to_52wk_high_pct": round(self.distance_to_52wk_high_pct * 100, 2),
            "signals": [s.signal_type.value for s in self.signals],
            "signal_details": [
                {
                    "type": s.signal_type.value,
                    "strength": s.strength,
                    "description": s.description,
                }
                for s in self.signals
            ],
            "score": self.score,
            "news_count": len(self.news),
            "narrative": self.narrative,
        }


@dataclass
class ScanReport:
    """Complete scan report."""

    scan_date: str
    scan_time: str
    total_stocks_scanned: int
    signals_detected: int
    stocks: List[ScanResult]
    execution_time_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "scan_date": self.scan_date,
            "scan_time": self.scan_time,
            "total_stocks_scanned": self.total_stocks_scanned,
            "signals_detected": self.signals_detected,
            "stocks_with_signals": len(self.stocks),
            "execution_time_seconds": round(self.execution_time_seconds, 2),
            "stocks": [s.to_dict() for s in self.stocks],
        }


class StockScanner:
    """
    High-intent stock signal scanner.

    Scans for technical signals indicating potential stock movements.
    """

    def __init__(
        self,
        fmp_client: Optional[FMPClient] = None,
        signal_config: Optional[SignalConfig] = None,
    ):
        """
        Initialize the scanner.

        Args:
            fmp_client: FMP API client (creates new one if not provided)
            signal_config: Signal detection configuration
        """
        self.fmp = fmp_client or FMPClient()
        self.detector = SignalDetector(signal_config)
        self.config = signal_config or SignalConfig()

    async def scan_market_movers(self) -> List[ScanResult]:
        """
        Scan today's biggest gainers and most active stocks.

        This is the primary scan method - uses FMP's pre-filtered lists.
        """
        logger.info("Fetching market movers (gainers + most active)...")

        # Fetch gainers and most active in parallel
        gainers, most_active = await asyncio.gather(
            self.fmp.get_biggest_gainers(),
            self.fmp.get_most_active(),
            return_exceptions=True,
        )

        # Handle errors
        gainers = gainers if not isinstance(gainers, Exception) else []
        most_active = most_active if not isinstance(most_active, Exception) else []

        logger.info(f"Found {len(gainers)} gainers, {len(most_active)} most active")

        # Combine and deduplicate
        seen_tickers: Set[str] = set()
        candidates = []

        for stock in gainers + most_active:
            ticker = stock.get("symbol", "")
            if ticker and ticker not in seen_tickers:
                seen_tickers.add(ticker)
                candidates.append(stock)

        logger.info(f"Total unique candidates: {len(candidates)}")

        # Detect signals for each candidate
        results = []
        for stock_data in candidates:
            stock = StockData.from_gainer(stock_data)
            signals = self.detector.detect_signals(stock)

            if signals:  # Only include stocks with at least one signal
                result = self._create_result(stock, signals)
                results.append(result)

        # Rank by signal strength
        results = sorted(results, key=lambda r: r.score, reverse=True)

        logger.info(f"Detected signals in {len(results)} stocks")
        return results

    async def scan_tickers(self, tickers: List[str]) -> List[ScanResult]:
        """
        Scan specific tickers for signals.

        Args:
            tickers: List of ticker symbols to scan

        Returns:
            List of stocks with detected signals
        """
        logger.info(f"Scanning {len(tickers)} specific tickers...")

        # Fetch quotes in batches
        all_quotes = []
        for i in range(0, len(tickers), 50):
            batch = tickers[i : i + 50]
            quotes = await self.fmp.get_batch_quotes(batch)
            if quotes:
                all_quotes.extend(quotes)

        logger.info(f"Fetched quotes for {len(all_quotes)} tickers")

        # Detect signals for each stock
        results = []
        for quote in all_quotes:
            stock = StockData.from_quote(quote)
            signals = self.detector.detect_signals(stock)

            if signals:
                result = self._create_result(stock, signals)
                results.append(result)

        # Rank by signal strength
        results = sorted(results, key=lambda r: r.score, reverse=True)

        logger.info(f"Detected signals in {len(results)} stocks")
        return results

    async def scan_sp500(self) -> List[ScanResult]:
        """
        Scan all S&P 500 stocks for signals.

        More comprehensive but slower than scan_market_movers().
        """
        logger.info("Fetching S&P 500 constituents...")

        constituents = await self.fmp.get_sp500_constituents()
        tickers = [c.get("symbol") for c in constituents if c.get("symbol")]

        logger.info(f"Found {len(tickers)} S&P 500 stocks")

        return await self.scan_tickers(tickers)

    async def enrich_with_technicals(self, results: List[ScanResult]) -> List[ScanResult]:
        """
        Enrich results with additional technical indicators.

        Adds SMA crossover detection for stocks that don't have it yet.
        """
        logger.info(f"Enriching {len(results)} stocks with technicals...")

        async def fetch_technicals(result: ScanResult) -> ScanResult:
            try:
                scanner_data = await self.fmp.get_scanner_data(result.ticker)

                # Update stock data with technicals
                stock = StockData(
                    ticker=result.ticker,
                    price=result.price,
                    previous_close=result.price / (1 + result.change_pct) if result.change_pct != -1 else result.price,
                    open_price=result.price,  # Approximation
                    volume=result.volume,
                    avg_volume=int(result.volume / result.volume_vs_avg) if result.volume_vs_avg > 0 else result.volume,
                    year_high=result.price / (1 - result.distance_to_52wk_high_pct) if result.distance_to_52wk_high_pct < 1 else result.price,
                    year_low=0,  # Not needed for SMA check
                    change_pct=result.change_pct,
                    company_name=result.company_name,
                    sma_20=scanner_data.get("sma_20"),
                    sma_50=scanner_data.get("sma_50"),
                    sma_200=scanner_data.get("sma_200"),
                    rsi_14=scanner_data.get("rsi_14"),
                )

                # Check for SMA crossover
                if sma_signal := self.detector._check_sma_crossover(stock):
                    # Check if we already have this signal type
                    existing_types = {s.signal_type for s in result.signals}
                    if SignalType.SMA_CROSSOVER not in existing_types:
                        result.signals.append(sma_signal)
                        result.score += {"weak": 1, "moderate": 2, "strong": 3}.get(sma_signal.strength, 0)

            except Exception as e:
                logger.warning(f"Failed to fetch technicals for {result.ticker}: {e}")

            return result

        # Fetch technicals in parallel (limit concurrency)
        enriched = await asyncio.gather(
            *[fetch_technicals(r) for r in results[:30]],  # Limit to top 30 to avoid rate limits
            return_exceptions=True,
        )

        # Filter out exceptions and re-sort
        valid_results = [r for r in enriched if isinstance(r, ScanResult)]
        return sorted(valid_results, key=lambda r: r.score, reverse=True)

    async def fetch_news_for_results(
        self,
        results: List[ScanResult],
        limit_per_stock: int = 10,
    ) -> List[ScanResult]:
        """
        Fetch news for stocks with signals.

        Args:
            results: Scan results to enrich with news
            limit_per_stock: Max news articles per stock

        Returns:
            Results with news populated
        """
        if not results:
            return results

        logger.info(f"Fetching news for {len(results)} stocks...")

        # Fetch news in batches of 10 tickers
        ticker_batches = [
            [r.ticker for r in results[i : i + 10]] for i in range(0, len(results), 10)
        ]

        all_news = []
        for batch in ticker_batches:
            news = await self.fmp.get_stock_news_stable(batch, limit=limit_per_stock * len(batch))
            if news:
                all_news.extend(news)

        # Group news by ticker
        news_by_ticker: Dict[str, List[Dict]] = {}
        for article in all_news:
            ticker = article.get("symbol", "")
            if ticker:
                if ticker not in news_by_ticker:
                    news_by_ticker[ticker] = []
                if len(news_by_ticker[ticker]) < limit_per_stock:
                    news_by_ticker[ticker].append(article)

        # Attach news to results
        for result in results:
            result.news = news_by_ticker.get(result.ticker, [])

        logger.info(f"Attached news to {sum(1 for r in results if r.news)} stocks")
        return results

    async def run_full_scan(
        self,
        tickers: Optional[List[str]] = None,
        include_technicals: bool = True,
        include_news: bool = True,
    ) -> ScanReport:
        """
        Run a complete scan with all enrichments.

        Args:
            tickers: Specific tickers to scan (None = market movers)
            include_technicals: Whether to fetch additional technicals
            include_news: Whether to fetch news

        Returns:
            Complete scan report
        """
        start_time = datetime.now()

        # Run the scan
        if tickers:
            results = await self.scan_tickers(tickers)
            total_scanned = len(tickers)
        else:
            results = await self.scan_market_movers()
            total_scanned = len(results) + 50  # Approximate (some may have no signals)

        # Enrich with technicals
        if include_technicals and results:
            results = await self.enrich_with_technicals(results)

        # Fetch news
        if include_news and results:
            results = await self.fetch_news_for_results(results)

        execution_time = (datetime.now() - start_time).total_seconds()

        # Build report
        report = ScanReport(
            scan_date=start_time.strftime("%Y-%m-%d"),
            scan_time=start_time.strftime("%H:%M:%S"),
            total_stocks_scanned=total_scanned,
            signals_detected=sum(len(r.signals) for r in results),
            stocks=results,
            execution_time_seconds=execution_time,
        )

        logger.info(
            f"Scan complete: {len(results)} stocks with signals, "
            f"{report.signals_detected} total signals in {execution_time:.1f}s"
        )

        return report

    def _create_result(self, stock: StockData, signals: List[Signal]) -> ScanResult:
        """Create a ScanResult from stock data and signals."""
        # Calculate signal score
        strength_scores = {"weak": 1, "moderate": 2, "strong": 3}
        score = sum(strength_scores.get(s.strength, 0) for s in signals)

        # Calculate distance to 52-week high
        distance_to_high = 0.0
        if stock.year_high > 0:
            distance_to_high = (stock.year_high - stock.price) / stock.year_high

        # Calculate volume vs average
        volume_vs_avg = 0.0
        if stock.avg_volume > 0:
            volume_vs_avg = stock.volume / stock.avg_volume

        return ScanResult(
            ticker=stock.ticker,
            company_name=stock.company_name,
            sector=stock.sector,
            price=stock.price,
            change_pct=stock.change_pct,
            volume=stock.volume,
            volume_vs_avg=volume_vs_avg,
            distance_to_52wk_high_pct=distance_to_high,
            signals=signals,
            score=score,
        )

    async def close(self):
        """Clean up resources."""
        await self.fmp.close()
