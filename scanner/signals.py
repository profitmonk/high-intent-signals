"""
Signal detection logic for high-intent stock identification.

Defines signal types and detection methods based on technical indicators.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SignalType(Enum):
    """Types of high-intent signals we detect."""

    ATH_BREAKOUT = "ATH_BREAKOUT"  # Near or at 52-week high
    VOLUME_SPIKE = "VOLUME_SPIKE"  # Volume significantly above average
    GAP_UP = "GAP_UP"  # Large gap up on open
    MOMENTUM = "MOMENTUM"  # In top gainers
    SMA_CROSSOVER = "SMA_CROSSOVER"  # Price crossing above key SMA
    TREND_REVERSAL = "TREND_REVERSAL"  # Breaking out of downtrend


@dataclass
class Signal:
    """A detected signal for a stock."""

    signal_type: SignalType
    strength: str  # "strong", "moderate", "weak"
    description: str
    value: Optional[float] = None  # The actual value that triggered signal
    threshold: Optional[float] = None  # The threshold used


@dataclass
class SignalConfig:
    """Configuration for signal detection thresholds."""

    # ATH Breakout: price must be within X% of 52-week high
    ath_threshold_pct: float = 0.95  # Default: 95% of 52wk high

    # Volume Spike: current volume must be X times average
    volume_spike_multiplier: float = 2.0  # Default: 2x average volume

    # Gap Up: open must be X% above previous close
    gap_up_threshold_pct: float = 0.05  # Default: 5% gap

    # Daily Gain: minimum % gain to be considered momentum
    daily_gain_threshold_pct: float = 0.03  # Default: 3% daily gain

    # SMA Crossover: price crossing above this SMA
    sma_crossover_period: int = 50  # Default: 50-day SMA


@dataclass
class StockData:
    """Data needed for signal detection on a stock."""

    ticker: str
    price: float
    previous_close: float
    open_price: float
    volume: int
    avg_volume: int
    year_high: float
    year_low: float
    change_pct: float
    company_name: str = ""
    sector: str = ""
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    rsi_14: Optional[float] = None

    @classmethod
    def from_quote(cls, quote: Dict[str, Any], technicals: Optional[Dict[str, Any]] = None) -> "StockData":
        """Create StockData from FMP quote response."""
        technicals = technicals or {}

        return cls(
            ticker=quote.get("symbol", ""),
            price=quote.get("price", 0) or 0,
            previous_close=quote.get("previousClose", 0) or 0,
            open_price=quote.get("open", 0) or 0,
            volume=quote.get("volume", 0) or 0,
            avg_volume=quote.get("avgVolume", 0) or 0,
            year_high=float(quote.get("yearHigh", 0) or 0),
            year_low=float(quote.get("yearLow", 0) or 0),
            change_pct=(quote.get("changesPercentage", 0) or 0) / 100,  # Convert to decimal
            company_name=quote.get("name", ""),
            sma_20=technicals.get("sma_20"),
            sma_50=technicals.get("sma_50"),
            sma_200=technicals.get("sma_200"),
            rsi_14=technicals.get("rsi_14"),
        )

    @classmethod
    def from_gainer(cls, gainer: Dict[str, Any]) -> "StockData":
        """Create StockData from FMP biggest-gainers response."""
        return cls(
            ticker=gainer.get("symbol", ""),
            price=gainer.get("price", 0) or 0,
            previous_close=gainer.get("previousClose", 0) or gainer.get("price", 0) - gainer.get("change", 0),
            open_price=gainer.get("open", 0) or 0,
            volume=gainer.get("volume", 0) or 0,
            avg_volume=gainer.get("avgVolume", 0) or 1,  # Avoid division by zero
            year_high=float(gainer.get("yearHigh", 0) or 0),
            year_low=float(gainer.get("yearLow", 0) or 0),
            change_pct=(gainer.get("changesPercentage", 0) or 0) / 100,
            company_name=gainer.get("name", ""),
        )


class SignalDetector:
    """Detects high-intent signals in stock data."""

    def __init__(self, config: Optional[SignalConfig] = None):
        """Initialize with optional custom configuration."""
        self.config = config or SignalConfig()

    def detect_signals(self, stock: StockData) -> List[Signal]:
        """
        Detect all signals for a stock.

        Args:
            stock: Stock data to analyze

        Returns:
            List of detected signals
        """
        signals = []

        # Check each signal type
        if signal := self._check_ath_breakout(stock):
            signals.append(signal)

        if signal := self._check_volume_spike(stock):
            signals.append(signal)

        if signal := self._check_gap_up(stock):
            signals.append(signal)

        if signal := self._check_momentum(stock):
            signals.append(signal)

        if signal := self._check_sma_crossover(stock):
            signals.append(signal)

        return signals

    def _check_ath_breakout(self, stock: StockData) -> Optional[Signal]:
        """Check if stock is near 52-week high (All-Time High proxy)."""
        if stock.year_high <= 0:
            return None

        pct_of_high = stock.price / stock.year_high

        if pct_of_high >= self.config.ath_threshold_pct:
            # Determine strength
            if pct_of_high >= 0.99:
                strength = "strong"
                desc = f"At 52-week high (${stock.price:.2f} = {pct_of_high:.1%} of ${stock.year_high:.2f})"
            elif pct_of_high >= 0.97:
                strength = "moderate"
                desc = f"Near 52-week high ({pct_of_high:.1%} of ${stock.year_high:.2f})"
            else:
                strength = "weak"
                desc = f"Approaching 52-week high ({pct_of_high:.1%})"

            return Signal(
                signal_type=SignalType.ATH_BREAKOUT,
                strength=strength,
                description=desc,
                value=pct_of_high,
                threshold=self.config.ath_threshold_pct,
            )

        return None

    def _check_volume_spike(self, stock: StockData) -> Optional[Signal]:
        """Check for unusual volume activity."""
        if stock.avg_volume <= 0:
            return None

        volume_ratio = stock.volume / stock.avg_volume

        if volume_ratio >= self.config.volume_spike_multiplier:
            # Determine strength
            if volume_ratio >= 5.0:
                strength = "strong"
                desc = f"Extreme volume ({volume_ratio:.1f}x average)"
            elif volume_ratio >= 3.0:
                strength = "moderate"
                desc = f"High volume ({volume_ratio:.1f}x average)"
            else:
                strength = "weak"
                desc = f"Above-average volume ({volume_ratio:.1f}x)"

            return Signal(
                signal_type=SignalType.VOLUME_SPIKE,
                strength=strength,
                description=desc,
                value=volume_ratio,
                threshold=self.config.volume_spike_multiplier,
            )

        return None

    def _check_gap_up(self, stock: StockData) -> Optional[Signal]:
        """Check for gap up on open."""
        if stock.previous_close <= 0 or stock.open_price <= 0:
            return None

        gap_pct = (stock.open_price - stock.previous_close) / stock.previous_close

        if gap_pct >= self.config.gap_up_threshold_pct:
            # Determine strength
            if gap_pct >= 0.10:
                strength = "strong"
                desc = f"Large gap up ({gap_pct:.1%} above previous close)"
            elif gap_pct >= 0.07:
                strength = "moderate"
                desc = f"Gap up ({gap_pct:.1%})"
            else:
                strength = "weak"
                desc = f"Small gap up ({gap_pct:.1%})"

            return Signal(
                signal_type=SignalType.GAP_UP,
                strength=strength,
                description=desc,
                value=gap_pct,
                threshold=self.config.gap_up_threshold_pct,
            )

        return None

    def _check_momentum(self, stock: StockData) -> Optional[Signal]:
        """Check for momentum (significant daily gain)."""
        if stock.change_pct >= self.config.daily_gain_threshold_pct:
            # Determine strength
            if stock.change_pct >= 0.10:
                strength = "strong"
                desc = f"Strong momentum (+{stock.change_pct:.1%} today)"
            elif stock.change_pct >= 0.05:
                strength = "moderate"
                desc = f"Good momentum (+{stock.change_pct:.1%} today)"
            else:
                strength = "weak"
                desc = f"Positive momentum (+{stock.change_pct:.1%} today)"

            return Signal(
                signal_type=SignalType.MOMENTUM,
                strength=strength,
                description=desc,
                value=stock.change_pct,
                threshold=self.config.daily_gain_threshold_pct,
            )

        return None

    def _check_sma_crossover(self, stock: StockData) -> Optional[Signal]:
        """Check for price crossing above key moving averages."""
        signals_found = []

        # Check SMA 50 crossover (most important)
        if stock.sma_50 and stock.price > stock.sma_50:
            # Check if we're close to the SMA (recent crossover)
            pct_above = (stock.price - stock.sma_50) / stock.sma_50
            if pct_above <= 0.05:  # Within 5% above SMA = recent crossover
                signals_found.append(("50-day", stock.sma_50, pct_above))

        # Check SMA 200 crossover (golden cross territory)
        if stock.sma_200 and stock.price > stock.sma_200:
            pct_above = (stock.price - stock.sma_200) / stock.sma_200
            if pct_above <= 0.05:
                signals_found.append(("200-day", stock.sma_200, pct_above))

        if not signals_found:
            return None

        # Return the most significant crossover
        if len(signals_found) >= 2:
            strength = "strong"
            desc = f"Price above both 50-day and 200-day SMA"
        elif "200-day" in signals_found[0][0]:
            strength = "moderate"
            desc = f"Price crossing above 200-day SMA (${signals_found[0][1]:.2f})"
        else:
            strength = "weak"
            desc = f"Price crossing above 50-day SMA (${signals_found[0][1]:.2f})"

        return Signal(
            signal_type=SignalType.SMA_CROSSOVER,
            strength=strength,
            description=desc,
            value=stock.price,
            threshold=signals_found[0][1],
        )


def filter_by_signal_strength(
    stocks_with_signals: List[tuple],
    min_strength: str = "weak",
    min_signals: int = 1,
) -> List[tuple]:
    """
    Filter stocks by signal strength and count.

    Args:
        stocks_with_signals: List of (StockData, List[Signal]) tuples
        min_strength: Minimum signal strength ("weak", "moderate", "strong")
        min_signals: Minimum number of signals required

    Returns:
        Filtered list of stocks
    """
    strength_order = {"weak": 1, "moderate": 2, "strong": 3}
    min_strength_val = strength_order.get(min_strength, 1)

    filtered = []
    for stock, signals in stocks_with_signals:
        # Filter signals by strength
        qualifying_signals = [
            s for s in signals if strength_order.get(s.strength, 0) >= min_strength_val
        ]

        if len(qualifying_signals) >= min_signals:
            filtered.append((stock, qualifying_signals))

    return filtered


def rank_by_signal_strength(stocks_with_signals: List[tuple]) -> List[tuple]:
    """
    Rank stocks by combined signal strength.

    Scoring:
    - strong signal = 3 points
    - moderate signal = 2 points
    - weak signal = 1 point

    Returns stocks sorted by total score (highest first).
    """
    strength_scores = {"weak": 1, "moderate": 2, "strong": 3}

    def score_stock(item):
        _, signals = item
        return sum(strength_scores.get(s.strength, 0) for s in signals)

    return sorted(stocks_with_signals, key=score_stock, reverse=True)
