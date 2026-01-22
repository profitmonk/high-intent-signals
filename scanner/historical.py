"""
Historical signal detection for backtesting and proper signal generation.

Downloads historical price data and calculates signals day-by-day to identify
when breakouts, volume spikes, and crossovers actually occurred.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from data.fmp_client import FMPClient

logger = logging.getLogger(__name__)


def get_most_recent_sunday(reference_date: Optional[datetime] = None) -> datetime:
    """
    Get the most recent Sunday (or the reference date if it's already Sunday).

    This ensures consistent date convention across all data sources.
    The $1B+ signals database uses Sunday dates.
    """
    if reference_date is None:
        reference_date = datetime.now()

    # weekday(): Monday = 0, Sunday = 6
    days_since_sunday = (reference_date.weekday() + 1) % 7
    return reference_date - timedelta(days=days_since_sunday)


@dataclass
class HistoricalSignal:
    """A signal detected on a specific date."""

    date: str
    ticker: str
    signal_type: str
    strength: str
    description: str
    price: float
    volume: int

    # Context for the signal
    change_pct: float = 0.0
    volume_vs_avg: float = 0.0
    distance_to_high_pct: float = 0.0

    # Composite score (calculated based on signal quality)
    score: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScoredStockWeek:
    """
    Aggregated signals for a stock in a single week with composite scoring.

    Scoring system:
    - New ATH (actual breakout, not "approaching"): 3 points
    - Volume >= 3x: 2 points
    - Volume 2-3x: 1 point
    - Momentum >= 15%: 2 points
    - Momentum 10-15%: 1 point
    - SMA50 crossover: 1 point
    - SMA200 crossover: 2 points
    - Confluence bonus (2+ signal types): +1 point
    """

    date: str
    ticker: str
    total_score: int
    signals: List[HistoricalSignal]
    signal_types: List[str]
    price: float
    change_pct: float = 0.0

    @property
    def has_confluence(self) -> bool:
        return len(set(self.signal_types)) >= 2

    @property
    def signal_summary(self) -> str:
        return " + ".join(sorted(set(self.signal_types)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "ticker": self.ticker,
            "total_score": self.total_score,
            "signal_types": self.signal_types,
            "signal_summary": self.signal_summary,
            "has_confluence": self.has_confluence,
            "price": self.price,
            "change_pct": self.change_pct,
            "signals": [s.to_dict() for s in self.signals],
        }


@dataclass
class HistoricalConfig:
    """Configuration for historical signal detection."""

    # Data parameters
    years_of_data: int = 3
    resample_to_weekly: bool = True

    # Universe filter
    min_market_cap: int = 5_000_000_000  # $5B
    us_only: bool = True
    exclude_etfs: bool = True

    # Signal thresholds
    ath_threshold_pct: float = 0.98  # Within 2% of 52-week high
    volume_spike_multiplier: float = 2.0  # 2x 20-period average
    sma_cross_periods: List[int] = field(default_factory=lambda: [50, 200])
    min_gain_pct: float = 0.05  # 5% weekly gain for momentum

    # Cache settings
    cache_dir: Path = field(default_factory=lambda: Path("data/cache/historical"))


class HistoricalDataManager:
    """Manages downloading and caching of historical price data."""

    def __init__(self, config: Optional[HistoricalConfig] = None):
        self.config = config or HistoricalConfig()
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fmp = FMPClient()

    async def get_universe(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get the stock universe (US stocks > $5B market cap).

        Returns list of stock info dicts with symbol, name, sector, marketCap.
        """
        cache_file = self.config.cache_dir / "universe.json"

        # Check cache (refresh daily)
        if not force_refresh and cache_file.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if cache_age < timedelta(days=1):
                with open(cache_file) as f:
                    return json.load(f)

        logger.info(f"Fetching stock universe (>${self.config.min_market_cap/1e9:.0f}B market cap)...")

        # FMP screener returns max 1000 per call, may need pagination
        all_stocks = []

        stocks = await self.fmp.get_stock_screener(
            market_cap_min=self.config.min_market_cap,
            is_etf=False,
            is_actively_trading=True,
            limit=10000,  # Get as many as possible
        )

        if stocks:
            # Filter for US exchanges
            us_exchanges = {"NYSE", "NASDAQ", "AMEX"}
            if self.config.us_only:
                stocks = [s for s in stocks if s.get("exchangeShortName") in us_exchanges]

            # Exclude ETFs and mutual funds
            if self.config.exclude_etfs:
                stocks = [s for s in stocks if not s.get("isEtf") and not s.get("isFund")]

            all_stocks = stocks

        logger.info(f"Found {len(all_stocks)} stocks in universe")

        # Cache
        with open(cache_file, "w") as f:
            json.dump(all_stocks, f)

        return all_stocks

    async def get_historical_prices(
        self,
        ticker: str,
        years: int = 3,
        force_refresh: bool = False,
    ) -> Optional[pd.DataFrame]:
        """
        Get historical daily prices for a ticker.

        Returns DataFrame with columns: date, open, high, low, close, volume
        """
        cache_file = self.config.cache_dir / f"{ticker}_daily.parquet"

        # Check cache (refresh weekly)
        if not force_refresh and cache_file.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if cache_age < timedelta(days=7):
                try:
                    return pd.read_parquet(cache_file)
                except Exception:
                    pass  # Re-download if cache is corrupted

        # Calculate date range - align to Sunday for consistent week boundaries
        end_dt = get_most_recent_sunday()
        end_date = end_dt.strftime("%Y-%m-%d")
        start_date = (end_dt - timedelta(days=years * 365)).strftime("%Y-%m-%d")

        try:
            data = await self.fmp.get_historical_prices(ticker, start_date, end_date)

            if not data or "historical" not in data:
                return None

            # Convert to DataFrame
            df = pd.DataFrame(data["historical"])

            if df.empty:
                return None

            # Clean up columns
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            # Keep only needed columns
            columns = ["date", "open", "high", "low", "close", "volume"]
            df = df[[c for c in columns if c in df.columns]]

            # Cache
            df.to_parquet(cache_file, index=False)

            return df

        except Exception as e:
            logger.warning(f"Failed to get historical data for {ticker}: {e}")
            return None

    async def get_weekly_prices(
        self,
        ticker: str,
        years: int = 3,
        force_refresh: bool = False,
    ) -> Optional[pd.DataFrame]:
        """
        Get weekly OHLCV data (resampled from daily).

        Returns DataFrame with weekly bars.
        """
        cache_file = self.config.cache_dir / f"{ticker}_weekly.parquet"

        # Check cache
        if not force_refresh and cache_file.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if cache_age < timedelta(days=7):
                try:
                    return pd.read_parquet(cache_file)
                except Exception:
                    pass

        # Get daily data
        daily = await self.get_historical_prices(ticker, years, force_refresh)

        if daily is None or daily.empty:
            return None

        # Resample to weekly
        daily = daily.set_index("date")

        weekly = daily.resample("W-SUN").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        weekly = weekly.reset_index()

        # Cache
        weekly.to_parquet(cache_file, index=False)

        return weekly

    async def download_universe_data(
        self,
        max_concurrent: int = 10,
        weekly: bool = True,
        custom_tickers: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Download historical data for entire universe.

        Args:
            max_concurrent: Maximum concurrent downloads
            weekly: If True, resample to weekly data
            custom_tickers: Optional list of tickers to download (overrides default universe)

        Returns dict mapping ticker -> DataFrame.
        """
        if custom_tickers:
            tickers = custom_tickers
            logger.info(f"Using custom universe of {len(tickers)} tickers")
        else:
            universe = await self.get_universe()
            tickers = [s["symbol"] for s in universe]

        logger.info(f"Downloading historical data for {len(tickers)} stocks...")

        semaphore = asyncio.Semaphore(max_concurrent)

        async def download_one(ticker: str) -> Tuple[str, Optional[pd.DataFrame]]:
            async with semaphore:
                if weekly:
                    df = await self.get_weekly_prices(ticker, self.config.years_of_data)
                else:
                    df = await self.get_historical_prices(ticker, self.config.years_of_data)
                return ticker, df

        results = await asyncio.gather(
            *[download_one(t) for t in tickers],
            return_exceptions=True,
        )

        data = {}
        success_count = 0
        for result in results:
            if isinstance(result, Exception):
                continue
            ticker, df = result
            if df is not None and not df.empty:
                data[ticker] = df
                success_count += 1

        logger.info(f"Successfully downloaded data for {success_count}/{len(tickers)} stocks")

        return data

    async def close(self):
        await self.fmp.close()


class HistoricalSignalDetector:
    """Detects signals on historical data."""

    def __init__(self, config: Optional[HistoricalConfig] = None):
        self.config = config or HistoricalConfig()

    def calculate_signals(
        self,
        df: pd.DataFrame,
        ticker: str,
    ) -> List[HistoricalSignal]:
        """
        Calculate all signals for a stock's historical data.

        Args:
            df: DataFrame with date, open, high, low, close, volume
            ticker: Stock symbol

        Returns:
            List of signals detected
        """
        # Minimum 20 weeks of data (allow newer stocks)
        if df is None or len(df) < 20:
            return []

        signals = []

        # Add calculated columns
        df = df.copy()
        df = self._add_indicators(df)

        # Start after enough data for lookback (need at least 20 weeks for indicators)
        # For stocks with 52+ weeks, start at 52; for newer stocks, start at 20
        start_idx = 20  # Minimum lookback needed for indicators

        for i in range(start_idx, len(df)):  # Scan from lookback period to end
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            date_str = row["date"].strftime("%Y-%m-%d")

            # Check each signal type
            if signal := self._check_ath_breakout(row, prev_row, ticker, date_str):
                signals.append(signal)

            if signal := self._check_volume_spike(row, ticker, date_str):
                signals.append(signal)

            if signal := self._check_sma_crossover(row, prev_row, ticker, date_str, period=50):
                signals.append(signal)

            if signal := self._check_sma_crossover(row, prev_row, ticker, date_str, period=200):
                signals.append(signal)

            if signal := self._check_momentum(row, prev_row, ticker, date_str):
                signals.append(signal)

        return signals

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators to DataFrame."""

        # Rolling high - use 52 weeks if available, but allow min 20 weeks for newer stocks
        # This captures "all-time high" for stocks with less than 52 weeks of history
        df["rolling_52w_high"] = df["high"].rolling(window=52, min_periods=20).max()

        # 20-period average volume (min 10 for newer stocks)
        df["avg_volume_20"] = df["volume"].rolling(window=20, min_periods=10).mean()

        # SMAs - use min_periods to allow newer stocks
        df["sma_50"] = df["close"].rolling(window=50, min_periods=20).mean()
        df["sma_200"] = df["close"].rolling(window=200, min_periods=50).mean()

        # Weekly change
        df["change_pct"] = df["close"].pct_change()

        # Volume ratio
        df["volume_ratio"] = df["volume"] / df["avg_volume_20"]

        return df

    def _check_ath_breakout(
        self,
        row: pd.Series,
        prev_row: pd.Series,
        ticker: str,
        date_str: str,
    ) -> Optional[HistoricalSignal]:
        """
        Check for 52-week high breakout.

        Signal triggers when price breaks to NEW 52-week high.
        Compare current close to PREVIOUS rolling high (not current, which includes this week's high).
        """
        if pd.isna(prev_row.get("rolling_52w_high")):
            return None

        # Use PREVIOUS rolling high as the benchmark (before this week's price action)
        prev_high_52w = prev_row["rolling_52w_high"]

        # Check where we were vs where we are now relative to the previous high
        prev_pct = prev_row["close"] / prev_high_52w if prev_high_52w > 0 else 0
        curr_pct = row["close"] / prev_high_52w if prev_high_52w > 0 else 0

        # Signal: price crossed above the previous 52-week high threshold
        if prev_pct < self.config.ath_threshold_pct and curr_pct >= self.config.ath_threshold_pct:
            # Determine strength - strong if actual NEW high (close > previous high)
            if row["close"] > prev_high_52w:
                strength = "strong"
                desc = f"Breaking to new 52-week high at ${row['close']:.2f} (prev high: ${prev_high_52w:.2f})"
            else:
                strength = "moderate"
                desc = f"Approaching 52-week high ({curr_pct:.1%} of ${prev_high_52w:.2f})"

            return HistoricalSignal(
                date=date_str,
                ticker=ticker,
                signal_type="ATH_BREAKOUT",
                strength=strength,
                description=desc,
                price=row["close"],
                volume=int(row["volume"]),
                change_pct=row.get("change_pct", 0),
                distance_to_high_pct=1 - curr_pct,
            )

        return None

    def _check_volume_spike(
        self,
        row: pd.Series,
        ticker: str,
        date_str: str,
    ) -> Optional[HistoricalSignal]:
        """
        Check for volume spike (volume >> average).
        """
        if pd.isna(row.get("volume_ratio")):
            return None

        ratio = row["volume_ratio"]

        if ratio >= self.config.volume_spike_multiplier:
            if ratio >= 5.0:
                strength = "strong"
                desc = f"Extreme volume spike ({ratio:.1f}x average)"
            elif ratio >= 3.0:
                strength = "moderate"
                desc = f"High volume ({ratio:.1f}x average)"
            else:
                strength = "weak"
                desc = f"Above-average volume ({ratio:.1f}x)"

            return HistoricalSignal(
                date=date_str,
                ticker=ticker,
                signal_type="VOLUME_SPIKE",
                strength=strength,
                description=desc,
                price=row["close"],
                volume=int(row["volume"]),
                change_pct=row.get("change_pct", 0),
                volume_vs_avg=ratio,
            )

        return None

    def _check_sma_crossover(
        self,
        row: pd.Series,
        prev_row: pd.Series,
        ticker: str,
        date_str: str,
        period: int,
    ) -> Optional[HistoricalSignal]:
        """
        Check for SMA crossover (price crossing above SMA).

        Signal triggers when price crosses from below to above.
        """
        sma_col = f"sma_{period}"

        if pd.isna(row.get(sma_col)) or pd.isna(prev_row.get(sma_col)):
            return None

        curr_sma = row[sma_col]
        prev_sma = prev_row[sma_col]

        # Check for crossover: was below, now above
        was_below = prev_row["close"] < prev_sma
        now_above = row["close"] > curr_sma

        if was_below and now_above:
            if period == 200:
                strength = "strong"
                desc = f"Crossing above 200-period SMA (${curr_sma:.2f})"
            else:
                strength = "moderate"
                desc = f"Crossing above {period}-period SMA (${curr_sma:.2f})"

            return HistoricalSignal(
                date=date_str,
                ticker=ticker,
                signal_type=f"SMA{period}_CROSSOVER",
                strength=strength,
                description=desc,
                price=row["close"],
                volume=int(row["volume"]),
                change_pct=row.get("change_pct", 0),
            )

        return None

    def _check_momentum(
        self,
        row: pd.Series,
        prev_row: pd.Series,
        ticker: str,
        date_str: str,
    ) -> Optional[HistoricalSignal]:
        """
        Check for strong momentum (large weekly gain).
        """
        change = row.get("change_pct", 0)

        if pd.isna(change):
            return None

        if change >= self.config.min_gain_pct:
            if change >= 0.15:
                strength = "strong"
                desc = f"Strong momentum (+{change:.1%} this week)"
            elif change >= 0.10:
                strength = "moderate"
                desc = f"Good momentum (+{change:.1%} this week)"
            else:
                strength = "weak"
                desc = f"Positive momentum (+{change:.1%} this week)"

            return HistoricalSignal(
                date=date_str,
                ticker=ticker,
                signal_type="MOMENTUM",
                strength=strength,
                description=desc,
                price=row["close"],
                volume=int(row["volume"]),
                change_pct=change,
            )

        return None

    @staticmethod
    def calculate_signal_score(signal: HistoricalSignal) -> int:
        """
        Calculate composite score for a single signal.

        Scoring:
        - ATH_BREAKOUT (actual new high): 3 points
        - ATH_BREAKOUT (approaching): 0 points (filtered out)
        - VOLUME_SPIKE >= 3x: 2 points
        - VOLUME_SPIKE 2-3x: 1 point
        - MOMENTUM >= 15%: 2 points
        - MOMENTUM 10-15%: 1 point
        - MOMENTUM < 10%: 0 points (filtered out)
        - SMA50_CROSSOVER: 1 point
        - SMA200_CROSSOVER: 2 points
        """
        sig_type = signal.signal_type
        desc = signal.description

        if sig_type == "ATH_BREAKOUT":
            # Only actual new highs count
            if "Breaking to new" in desc:
                return 3
            return 0  # "Approaching" doesn't count

        elif sig_type == "VOLUME_SPIKE":
            vol_ratio = signal.volume_vs_avg
            if vol_ratio >= 5.0:
                return 3
            elif vol_ratio >= 3.0:
                return 2
            else:
                return 1

        elif sig_type == "MOMENTUM":
            change = abs(signal.change_pct) if signal.change_pct else 0
            if change >= 0.15:
                return 2
            elif change >= 0.10:
                return 1
            return 0  # < 10% doesn't count

        elif sig_type == "SMA200_CROSSOVER":
            return 2

        elif sig_type == "SMA50_CROSSOVER":
            return 1

        return 0

    def aggregate_by_stock_week(
        self,
        signals: List[HistoricalSignal],
    ) -> List[ScoredStockWeek]:
        """
        Aggregate signals by stock-week and calculate total scores with confluence bonus.

        Returns list of ScoredStockWeek sorted by score (descending).
        """
        from collections import defaultdict

        # Group signals by (ticker, date)
        grouped: Dict[Tuple[str, str], List[HistoricalSignal]] = defaultdict(list)

        for signal in signals:
            key = (signal.ticker, signal.date)
            # Calculate and set score
            signal.score = self.calculate_signal_score(signal)
            grouped[key].append(signal)

        # Build ScoredStockWeek for each group
        scored_weeks = []

        for (ticker, date), week_signals in grouped.items():
            # Sum individual scores
            base_score = sum(s.score for s in week_signals)

            # Skip if no meaningful signals
            if base_score == 0:
                continue

            # Get unique signal types (only those with score > 0)
            signal_types = [s.signal_type for s in week_signals if s.score > 0]
            unique_types = set(signal_types)

            # Confluence bonus: +1 if 2+ different signal types
            confluence_bonus = 1 if len(unique_types) >= 2 else 0
            total_score = base_score + confluence_bonus

            # Get price and change from first signal
            price = week_signals[0].price
            change_pct = week_signals[0].change_pct

            scored_weeks.append(ScoredStockWeek(
                date=date,
                ticker=ticker,
                total_score=total_score,
                signals=week_signals,
                signal_types=signal_types,
                price=price,
                change_pct=change_pct,
            ))

        # Sort by score descending, then date descending
        scored_weeks.sort(key=lambda x: (x.total_score, x.date), reverse=True)

        return scored_weeks


class HistoricalScanner:
    """
    Main class for historical signal scanning.

    Downloads data, calculates signals, and provides analysis.
    """

    def __init__(self, config: Optional[HistoricalConfig] = None):
        self.config = config or HistoricalConfig()
        self.data_manager = HistoricalDataManager(self.config)
        self.detector = HistoricalSignalDetector(self.config)
        self._signals_cache: Optional[List[HistoricalSignal]] = None
        self._sp500_universe = None  # Lazy-loaded SP500Universe

    async def _get_sp500_universe(self):
        """Lazy-load the S&P 500 universe manager."""
        if self._sp500_universe is None:
            from scanner.universe import SP500Universe
            self._sp500_universe = SP500Universe()
            await self._sp500_universe.load()
        return self._sp500_universe

    async def scan_universe(
        self,
        max_concurrent: int = 10,
        force_refresh: bool = False,
        custom_tickers: Optional[List[str]] = None,
    ) -> List[HistoricalSignal]:
        """
        Scan entire universe for historical signals.

        Downloads data if needed, then calculates signals.

        Args:
            max_concurrent: Maximum concurrent API requests
            force_refresh: Force refresh of cached data
            custom_tickers: Optional list of tickers to scan (instead of default universe)
        """
        logger.info("Starting historical scan...")

        # Determine cache file name based on whether custom tickers are used
        if custom_tickers:
            # Use a different cache file for custom universes
            cache_key = hash(tuple(sorted(custom_tickers))) % 10**8
            signals_cache_file = self.config.cache_dir / f"signals_custom_{cache_key}.json"
        else:
            signals_cache_file = self.config.cache_dir / "all_signals.json"

        if not force_refresh and signals_cache_file.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(signals_cache_file.stat().st_mtime)
            if cache_age < timedelta(days=1):
                logger.info("Loading signals from cache...")
                with open(signals_cache_file) as f:
                    data = json.load(f)
                    self._signals_cache = [HistoricalSignal(**s) for s in data]
                    return self._signals_cache

        # Download data
        data = await self.data_manager.download_universe_data(
            max_concurrent=max_concurrent,
            weekly=self.config.resample_to_weekly,
            custom_tickers=custom_tickers,
        )

        # Calculate signals for each stock
        all_signals = []

        for ticker, df in data.items():
            signals = self.detector.calculate_signals(df, ticker)
            all_signals.extend(signals)

            if signals:
                logger.debug(f"{ticker}: {len(signals)} signals detected")

        # Sort by date (newest first)
        all_signals.sort(key=lambda s: s.date, reverse=True)

        logger.info(f"Total signals detected: {len(all_signals)}")

        # Cache
        with open(signals_cache_file, "w") as f:
            json.dump([s.to_dict() for s in all_signals], f)

        self._signals_cache = all_signals
        return all_signals

    async def get_recent_signals(
        self,
        days: int = 30,
        signal_types: Optional[List[str]] = None,
        min_strength: str = "weak",
    ) -> List[HistoricalSignal]:
        """
        Get signals from the last N days.
        """
        if self._signals_cache is None:
            await self.scan_universe()

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        strength_order = {"weak": 1, "moderate": 2, "strong": 3}
        min_strength_val = strength_order.get(min_strength, 1)

        filtered = []
        for signal in self._signals_cache:
            if signal.date < cutoff:
                continue
            if signal_types and signal.signal_type not in signal_types:
                continue
            if strength_order.get(signal.strength, 0) < min_strength_val:
                continue
            filtered.append(signal)

        return filtered

    async def get_signals_by_ticker(
        self,
        ticker: str,
    ) -> List[HistoricalSignal]:
        """Get all signals for a specific ticker."""
        if self._signals_cache is None:
            await self.scan_universe()

        return [s for s in self._signals_cache if s.ticker == ticker]

    async def get_signal_summary(self) -> Dict[str, Any]:
        """Get summary statistics of signals."""
        if self._signals_cache is None:
            await self.scan_universe()

        signals = self._signals_cache

        # Count by type
        by_type = {}
        for s in signals:
            by_type[s.signal_type] = by_type.get(s.signal_type, 0) + 1

        # Count by strength
        by_strength = {}
        for s in signals:
            by_strength[s.strength] = by_strength.get(s.strength, 0) + 1

        # Recent signals (last 30 days)
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        recent = [s for s in signals if s.date >= cutoff]

        # Top tickers by signal count (last 30 days)
        ticker_counts = {}
        for s in recent:
            ticker_counts[s.ticker] = ticker_counts.get(s.ticker, 0) + 1

        top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:20]

        return {
            "total_signals": len(signals),
            "date_range": {
                "start": min(s.date for s in signals) if signals else None,
                "end": max(s.date for s in signals) if signals else None,
            },
            "by_type": by_type,
            "by_strength": by_strength,
            "last_30_days": {
                "total": len(recent),
                "top_tickers": top_tickers,
            },
        }

    async def get_high_intent_signals(
        self,
        min_score: int = 4,
        days: Optional[int] = None,
        ticker: Optional[str] = None,
        as_of_date: Optional[str] = None,
        use_sp500_pit: bool = False,
        use_marketcap_pit: bool = False,
        marketcap_universe: Optional[Any] = None,
        min_market_cap: Optional[int] = None,
        max_market_cap: Optional[int] = None,
    ) -> List[ScoredStockWeek]:
        """
        Get high-intent signals aggregated by stock-week with composite scoring.

        Args:
            min_score: Minimum composite score to include (default: 4)
            days: Only include signals from last N days (default: all)
            ticker: Filter to specific ticker (default: all)
            as_of_date: Only include signals on or before this date (YYYY-MM-DD)
                       Used for point-in-time backtesting
            use_sp500_pit: If True, filter to only stocks that were in S&P 500
                          at the as_of_date (point-in-time, survivorship-bias-free)
            use_marketcap_pit: If True, filter by point-in-time market cap threshold
            marketcap_universe: HistoricalMarketCapUniverse instance (required if use_marketcap_pit=True)
            min_market_cap: Override minimum market cap filter (uses dynamic threshold if None)
            max_market_cap: Maximum market cap filter (no max if None)

        Returns:
            List of ScoredStockWeek sorted by score descending
        """
        if self._signals_cache is None:
            await self.scan_universe()

        signals = self._signals_cache

        # Filter by as_of_date for point-in-time analysis
        if as_of_date:
            signals = [s for s in signals if s.date <= as_of_date]

        # Filter by date range if specified
        if days:
            reference_date = datetime.strptime(as_of_date, "%Y-%m-%d") if as_of_date else datetime.now()
            cutoff = (reference_date - timedelta(days=days)).strftime("%Y-%m-%d")
            signals = [s for s in signals if s.date >= cutoff]

        # Filter by ticker if specified
        if ticker:
            signals = [s for s in signals if s.ticker == ticker.upper()]

        # Filter to point-in-time S&P 500 members (survivorship-bias-free)
        if use_sp500_pit and as_of_date:
            sp500 = await self._get_sp500_universe()
            pit_members = sp500.get_members_on_date(as_of_date)
            signals = [s for s in signals if s.ticker in pit_members]

        # Filter by point-in-time market cap (survivorship-bias-free)
        if use_marketcap_pit and as_of_date and marketcap_universe:
            pit_members = marketcap_universe.get_members_on_date(
                as_of_date,
                min_cap=min_market_cap,
                max_cap=max_market_cap,
            )
            signals = [s for s in signals if s.ticker in pit_members]

        # Aggregate by stock-week and calculate scores
        scored_weeks = self.detector.aggregate_by_stock_week(signals)

        # Filter by minimum score
        scored_weeks = [sw for sw in scored_weeks if sw.total_score >= min_score]

        return scored_weeks

    async def get_high_intent_summary(
        self,
        min_score: int = 4,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get summary statistics for high-intent signals.
        """
        scored = await self.get_high_intent_signals(min_score=min_score, days=days)

        # Score distribution
        score_dist = {}
        for sw in scored:
            score_dist[sw.total_score] = score_dist.get(sw.total_score, 0) + 1

        # Signals by type
        type_counts = {}
        for sw in scored:
            for sig_type in set(sw.signal_types):
                type_counts[sig_type] = type_counts.get(sig_type, 0) + 1

        # Top tickers
        ticker_scores = {}
        for sw in scored:
            if sw.ticker not in ticker_scores:
                ticker_scores[sw.ticker] = {"count": 0, "max_score": 0}
            ticker_scores[sw.ticker]["count"] += 1
            ticker_scores[sw.ticker]["max_score"] = max(
                ticker_scores[sw.ticker]["max_score"],
                sw.total_score
            )

        top_tickers = sorted(
            ticker_scores.items(),
            key=lambda x: (x[1]["max_score"], x[1]["count"]),
            reverse=True
        )[:20]

        # Confluence stats
        with_confluence = sum(1 for sw in scored if sw.has_confluence)

        return {
            "total_high_intent": len(scored),
            "min_score": min_score,
            "days": days,
            "score_distribution": dict(sorted(score_dist.items(), reverse=True)),
            "by_signal_type": type_counts,
            "with_confluence": with_confluence,
            "without_confluence": len(scored) - with_confluence,
            "top_tickers": top_tickers,
        }

    async def scan_sp500_historical(
        self,
        start_date: str = "2016-01-01",
        end_date: Optional[str] = None,
        max_concurrent: int = 10,
        force_refresh: bool = False,
    ) -> List[HistoricalSignal]:
        """
        Scan all historical S&P 500 members (survivorship-bias-free).

        Downloads data for ALL stocks that were ever in S&P 500 during the period,
        not just current members. This avoids survivorship bias.

        Args:
            start_date: Start of backtest period (YYYY-MM-DD)
            end_date: End of backtest period (default: today)
            max_concurrent: Maximum concurrent API requests
            force_refresh: Force refresh of cached data

        Returns:
            List of all signals for the extended universe
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        # Calculate years of data needed (from start_date to now + 1 year buffer)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        years_needed = (datetime.now() - start_dt).days // 365 + 2  # +2 for buffer

        # Update config to fetch enough historical data
        if years_needed > self.config.years_of_data:
            logger.info(f"Updating years_of_data from {self.config.years_of_data} to {years_needed}")
            self.config.years_of_data = years_needed
            # Also update data manager's config
            self.data_manager.config.years_of_data = years_needed

        logger.info(f"Scanning survivorship-bias-free S&P 500 universe: {start_date} to {end_date}")
        logger.info(f"Using {years_needed} years of historical data")

        # Get all stocks that were ever in S&P 500 during the period
        sp500 = await self._get_sp500_universe()
        all_historical_members = sp500.get_all_historical_members(start_date, end_date)

        logger.info(f"Total unique S&P 500 members in period: {len(all_historical_members)}")

        # Scan this extended universe
        return await self.scan_universe(
            max_concurrent=max_concurrent,
            force_refresh=force_refresh,
            custom_tickers=list(all_historical_members),
        )

    async def scan_marketcap_historical(
        self,
        marketcap_universe,
        start_date: str = "2016-01-01",
        end_date: Optional[str] = None,
        max_concurrent: int = 10,
        force_refresh: bool = False,
    ) -> List[HistoricalSignal]:
        """
        Scan all stocks with historical market cap data (survivorship-bias-free).

        Downloads data for ALL stocks that have market cap history,
        then filters by point-in-time threshold during signal retrieval.

        Args:
            marketcap_universe: HistoricalMarketCapUniverse instance
            start_date: Start of backtest period (YYYY-MM-DD)
            end_date: End of backtest period (default: today)
            max_concurrent: Maximum concurrent API requests
            force_refresh: Force refresh of cached data

        Returns:
            List of all signals for the market cap universe
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        # Calculate years of data needed (from start_date to now + 1 year buffer)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        years_needed = (datetime.now() - start_dt).days // 365 + 2  # +2 for buffer

        # Update config to fetch enough historical data
        if years_needed > self.config.years_of_data:
            logger.info(f"Updating years_of_data from {self.config.years_of_data} to {years_needed}")
            self.config.years_of_data = years_needed
            # Also update data manager's config
            self.data_manager.config.years_of_data = years_needed

        logger.info(f"Scanning market cap universe: {start_date} to {end_date}")
        logger.info(f"Using {years_needed} years of historical data")

        # Get all tickers with market cap history
        all_tickers = list(marketcap_universe._market_cap_history.keys())

        logger.info(f"Total tickers with market cap history: {len(all_tickers)}")

        # Scan this extended universe
        return await self.scan_universe(
            max_concurrent=max_concurrent,
            force_refresh=force_refresh,
            custom_tickers=all_tickers,
        )

    async def close(self):
        await self.data_manager.close()
        if self._sp500_universe:
            await self._sp500_universe.close()
