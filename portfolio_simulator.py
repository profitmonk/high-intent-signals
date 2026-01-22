#!/usr/bin/env python3
"""
Portfolio Simulator for High Intent Signals

Tests different allocation strategies against historical signal data.
Simulates realistic portfolio management with position sizing, stop-losses,
and time-based exits.

Usage:
    python portfolio_simulator.py
    python portfolio_simulator.py --capital 100000 --stop-loss 0.25
"""

import argparse
import asyncio
import json
import random
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Try to import plotting libraries
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# Paths
SIGNALS_DB_PATH = Path("data/signals_history.json")
PRICE_CACHE_DIR = Path("data/cache")
RESULTS_DIR = Path("simulation_results")


@dataclass
class Position:
    """Represents an open position."""
    ticker: str
    entry_date: str
    entry_price: float
    shares: int
    cost_basis: float
    score: int
    signal_date: str

    # Tracking
    peak_price: float = 0.0
    current_price: float = 0.0

    def __post_init__(self):
        self.peak_price = self.entry_price
        self.current_price = self.entry_price


@dataclass
class ClosedPosition:
    """Represents a closed position."""
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    cost_basis: float
    proceeds: float
    pnl: float
    pnl_pct: float
    holding_days: int
    exit_reason: str  # 'time', 'stop_loss', 'trailing_stop', 'take_profit'
    score: int

    @property
    def is_long_term(self) -> bool:
        """Returns True if held > 365 days (long-term capital gains)."""
        return self.holding_days > 365


@dataclass
class StrategyConfig:
    """Configuration for a trading strategy."""
    name: str
    initial_capital: float = 100_000

    # Position sizing
    position_size_mode: str = "equal"  # 'equal', 'score_weighted', 'fixed_dollar'
    max_position_pct: float = 0.05  # 5% max per position
    fixed_dollar_amount: float = 2000
    min_score: int = 5  # Minimum score to trade

    # Exit rules
    holding_period_days: int = 90  # 3M=90, 6M=180, 12M=365
    stop_loss_pct: float = 0.25  # -25% stop loss
    trailing_stop_pct: float = 0.0  # 0 = disabled
    take_profit_pct: float = 0.0  # 0 = disabled

    # Portfolio limits
    max_positions: int = 50
    max_score: int = 99  # Maximum score to include (99 = no limit)
    max_sector_pct: float = 0.30  # Max 30% in one sector (not implemented yet)


@dataclass
class SimulationResult:
    """Results from a simulation run."""
    strategy: StrategyConfig

    # Performance
    final_value: float = 0.0
    total_return: float = 0.0
    cagr: float = 0.0

    # Risk metrics
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0

    # Trade stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0

    # Tax efficiency
    long_term_trades: int = 0
    short_term_trades: int = 0
    long_term_pct: float = 0.0

    # Time series
    equity_curve: List[Tuple[str, float]] = field(default_factory=list)

    # Closed positions
    closed_positions: List[ClosedPosition] = field(default_factory=list)


class PortfolioSimulator:
    """Simulates portfolio performance using historical signals."""

    def __init__(self):
        self.signals: List[Dict] = []
        self.price_data: Dict[str, List[Dict]] = {}  # ticker -> list of daily OHLC
        self.fmp = None

    def load_signals(self) -> None:
        """Load signals from database."""
        if not SIGNALS_DB_PATH.exists():
            raise FileNotFoundError(f"Signals database not found: {SIGNALS_DB_PATH}")

        with open(SIGNALS_DB_PATH) as f:
            self.signals = json.load(f)

        # Sort by entry date
        self.signals.sort(key=lambda x: x.get('entry_date', x.get('signal_date', '')))
        print(f"Loaded {len(self.signals)} signals")

        # Load cached price data for all tickers
        self._load_price_cache()

    def _load_price_cache(self) -> None:
        """Load cached historical price data for all signal tickers."""
        tickers = set(s.get('ticker', '') for s in self.signals if s.get('ticker'))
        loaded = 0

        # First try JSON files in main cache dir
        for ticker in tickers:
            patterns = [
                f"_historical-price-full_{ticker}_*.json",
                f"historical_{ticker}_*.json",
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
                            self.price_data[ticker] = data['historical']
                            loaded += 1
                        elif isinstance(data, list):
                            self.price_data[ticker] = data
                            loaded += 1
                except Exception:
                    pass

        # Try parquet files in historical subdirectory
        historical_cache = PRICE_CACHE_DIR / "historical"
        if historical_cache.exists():
            try:
                import pandas as pd
                for ticker in tickers:
                    if ticker in self.price_data:
                        continue

                    # Look for daily parquet file
                    parquet_file = historical_cache / f"{ticker}_daily.parquet"
                    if parquet_file.exists():
                        try:
                            df = pd.read_parquet(parquet_file)
                            # Convert to list of dicts with expected keys
                            records = []
                            for idx, row in df.iterrows():
                                # Handle both index-based and column-based date storage
                                if hasattr(idx, 'strftime'):
                                    date_str = idx.strftime('%Y-%m-%d')
                                elif 'date' in row:
                                    date_val = row['date']
                                    if hasattr(date_val, 'strftime'):
                                        date_str = date_val.strftime('%Y-%m-%d')
                                    else:
                                        date_str = str(date_val)[:10]
                                else:
                                    continue  # Skip if no valid date

                                record = {
                                    'date': date_str,
                                    'open': float(row.get('open', row.get('Open', 0))),
                                    'high': float(row.get('high', row.get('High', 0))),
                                    'low': float(row.get('low', row.get('Low', 0))),
                                    'close': float(row.get('close', row.get('Close', 0))),
                                    'volume': int(row.get('volume', row.get('Volume', 0))),
                                }
                                records.append(record)
                            if records:
                                self.price_data[ticker] = records
                                loaded += 1
                        except Exception:
                            pass
            except ImportError:
                pass  # pandas not available

        print(f"Loaded price data for {loaded}/{len(tickers)} tickers")

    def _get_price_data_for_period(
        self, ticker: str, start_date: str, end_date: str
    ) -> List[Dict]:
        """Get daily OHLC data for a ticker between dates."""
        if ticker not in self.price_data:
            return []

        data = self.price_data[ticker]
        filtered = [
            d for d in data
            if start_date <= d.get('date', '') <= end_date
        ]
        # Sort by date ascending
        return sorted(filtered, key=lambda x: x.get('date', ''))

    def _get_lowest_low(self, ticker: str, start_date: str, end_date: str) -> Optional[float]:
        """Get the lowest low price during a period."""
        data = self._get_price_data_for_period(ticker, start_date, end_date)
        if not data:
            return None
        lows = [d.get('low', float('inf')) for d in data if d.get('low')]
        return min(lows) if lows else None

    def _get_lowest_close(self, ticker: str, start_date: str, end_date: str) -> Optional[float]:
        """Get the lowest close price during a period."""
        data = self._get_price_data_for_period(ticker, start_date, end_date)
        if not data:
            return None
        closes = [d.get('close', float('inf')) for d in data if d.get('close')]
        return min(closes) if closes else None

    def _get_close_on_date(self, ticker: str, target_date: str) -> Optional[float]:
        """Get closing price on a specific date (or nearest prior date)."""
        if ticker not in self.price_data:
            return None

        data = self.price_data[ticker]
        # Find exact or nearest prior date
        best_date = None
        best_price = None

        for d in data:
            date = d.get('date', '')
            if date <= target_date:
                if best_date is None or date > best_date:
                    best_date = date
                    best_price = d.get('close')

        return best_price

    def _get_signals_for_week(self, week_date: str) -> List[Dict]:
        """Get all signals for a specific week.

        Matches signals where entry_date falls within the week ending on week_date (Friday).
        Week is defined as Monday (Friday-4) through Friday.
        """
        week_dt = datetime.strptime(week_date, "%Y-%m-%d")
        week_start = (week_dt - timedelta(days=4)).strftime("%Y-%m-%d")  # Monday
        week_end = week_date  # Friday
        return [s for s in self.signals
                if week_start <= s.get('entry_date', s.get('signal_date', '')) <= week_end]

    def _get_all_weeks(self) -> List[str]:
        """Get all unique signal weeks, sorted."""
        weeks = sorted(set(s.get('signal_date', '') for s in self.signals if s.get('signal_date')))
        return weeks

    def _calculate_position_size(
        self,
        config: StrategyConfig,
        cash: float,
        portfolio_value: float,
        signal: Dict,
        current_positions: int
    ) -> float:
        """Calculate how much to invest in a position."""

        if current_positions >= config.max_positions:
            return 0.0

        if config.position_size_mode == "fixed_dollar":
            size = config.fixed_dollar_amount
        elif config.position_size_mode == "score_weighted":
            # Base + score bonus
            base = portfolio_value * 0.02  # 2% base
            score_bonus = (signal.get('score', 5) - 5) * (portfolio_value * 0.005)  # +0.5% per point above 5
            size = base + max(0, score_bonus)
        else:  # equal
            size = portfolio_value * config.max_position_pct

        # Don't exceed available cash
        size = min(size, cash * 0.95)  # Keep 5% cash buffer

        # Don't exceed max position size
        max_size = portfolio_value * config.max_position_pct
        size = min(size, max_size)

        return size if size >= 100 else 0  # Minimum $100 position

    def _check_exit_conditions_real(
        self,
        position: Position,
        current_date: datetime,
        config: StrategyConfig
    ) -> Tuple[bool, str, float, str]:
        """
        Check if position should be exited using REAL price data.
        Returns: (should_exit, reason, exit_price, exit_date)

        Stop loss: triggered if lowest LOW from entry to now hit -X%
        Time exit: triggered after holding_period_days, exit at close
        """
        entry_date_str = position.entry_date
        current_date_str = current_date.strftime("%Y-%m-%d")
        entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d")
        days_held = (current_date - entry_dt).days

        # Get price data for the holding period
        price_data = self._get_price_data_for_period(
            position.ticker, entry_date_str, current_date_str
        )

        if not price_data:
            # No price data - use fallback
            return False, "", 0.0, ""

        # Check stop loss using lowest LOW during holding period
        if config.stop_loss_pct > 0:
            for day in price_data:
                low = day.get('low', 0)
                if low and low > 0:
                    pnl_from_low = (low - position.entry_price) / position.entry_price
                    if pnl_from_low <= -config.stop_loss_pct:
                        # Stop triggered on this day at the stop price
                        stop_price = position.entry_price * (1 - config.stop_loss_pct)
                        return True, "stop_loss", stop_price, day.get('date', current_date_str)

        # Check trailing stop using peak high and subsequent low
        if config.trailing_stop_pct > 0:
            peak_high = position.entry_price
            for day in price_data:
                high = day.get('high', 0)
                low = day.get('low', 0)
                if high and high > peak_high:
                    peak_high = high
                if low and peak_high > 0:
                    drawdown = (peak_high - low) / peak_high
                    if drawdown >= config.trailing_stop_pct:
                        trail_stop_price = peak_high * (1 - config.trailing_stop_pct)
                        return True, "trailing_stop", trail_stop_price, day.get('date', current_date_str)

        # Check take profit using highest HIGH
        if config.take_profit_pct > 0:
            for day in price_data:
                high = day.get('high', 0)
                if high and high > 0:
                    pnl_from_high = (high - position.entry_price) / position.entry_price
                    if pnl_from_high >= config.take_profit_pct:
                        take_profit_price = position.entry_price * (1 + config.take_profit_pct)
                        return True, "take_profit", take_profit_price, day.get('date', current_date_str)

        # Check holding period - exit at close on the exit day
        if days_held >= config.holding_period_days:
            exit_date = entry_dt + timedelta(days=config.holding_period_days)
            exit_date_str = exit_date.strftime("%Y-%m-%d")
            exit_price = self._get_close_on_date(position.ticker, exit_date_str)
            if exit_price:
                return True, "time", exit_price, exit_date_str
            else:
                # No exact price - use last available price from price_data or current_price
                if price_data:
                    # Find price closest to exit date
                    for day in reversed(price_data):
                        if day.get('close'):
                            return True, "time", day['close'], day.get('date', exit_date_str)
                # Fallback to current price if we have it
                if position.current_price > 0:
                    return True, "time", position.current_price, current_date_str

        # Update current price for portfolio valuation
        current_close = self._get_close_on_date(position.ticker, current_date_str)
        if current_close:
            position.current_price = current_close

        return False, "", 0.0, ""

    def _simulate_price_path(self, signal: Dict, start_date: str, end_date: str) -> Dict[str, float]:
        """
        Get price path for a signal between dates.
        Uses the return data we already have to infer prices.
        """
        prices = {}
        entry_price = signal.get('entry_price', signal.get('signal_price', 0))
        entry_date = signal.get('entry_date', signal.get('signal_date', ''))

        if not entry_price or entry_price <= 0:
            return prices

        # We have returns at specific points, interpolate between them
        prices[entry_date] = entry_price

        # 3M price
        if signal.get('return_3m') is not None:
            date_3m = (datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            prices[date_3m] = entry_price * (1 + signal['return_3m'])

        # 6M price
        if signal.get('return_6m') is not None:
            date_6m = (datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=180)).strftime("%Y-%m-%d")
            prices[date_6m] = entry_price * (1 + signal['return_6m'])

        # 12M price
        if signal.get('return_12m') is not None:
            date_12m = (datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=365)).strftime("%Y-%m-%d")
            prices[date_12m] = entry_price * (1 + signal['return_12m'])

        # Current price
        if signal.get('return_current') is not None:
            today = datetime.now().strftime("%Y-%m-%d")
            prices[today] = entry_price * (1 + signal['return_current'])

        return prices

    def _get_price_at_date(self, signal: Dict, target_date: str, add_volatility: bool = True) -> Optional[float]:
        """
        Get price at a specific date with realistic volatility.

        Uses a Brownian bridge approach: interpolate between known return points,
        but add realistic volatility noise based on typical stock behavior.
        """
        prices = self._simulate_price_path(signal, "", "")

        if not prices:
            return None

        entry_date = signal.get('entry_date', signal.get('signal_date', ''))
        entry_price = signal.get('entry_price', signal.get('signal_price', 0))
        ticker = signal.get('ticker', 'UNK')

        if target_date <= entry_date:
            return entry_price

        # Find closest known prices before and after target
        sorted_dates = sorted(prices.keys())

        before_date = None
        after_date = None

        for d in sorted_dates:
            if d <= target_date:
                before_date = d
            elif after_date is None:
                after_date = d

        if before_date is None:
            return entry_price

        if after_date is None:
            return prices[before_date]

        # Brownian bridge interpolation with volatility
        before_price = prices[before_date]
        after_price = prices[after_date]

        before_dt = datetime.strptime(before_date, "%Y-%m-%d")
        after_dt = datetime.strptime(after_date, "%Y-%m-%d")
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        total_days = (after_dt - before_dt).days
        days_in = (target_dt - before_dt).days

        if total_days == 0:
            return before_price

        ratio = days_in / total_days

        # Base interpolated price (linear)
        base_price = before_price + (after_price - before_price) * ratio

        if not add_volatility:
            return base_price

        # Add conservative volatility estimate for drawdown tracking
        # We use a smaller volatility since this is for portfolio valuation,
        # not for triggering stop losses (those use actual return data)
        annual_vol = 0.20  # Conservative 20% annual vol
        daily_vol = annual_vol / math.sqrt(252)

        # Brownian bridge variance: peaks in middle, zero at endpoints
        bridge_var = (days_in * (total_days - days_in)) / total_days * (daily_vol ** 2) * total_days

        # Use deterministic seed for reproducibility
        seed = hash(f"{ticker}_{target_date}") % (2**31)
        rng = random.Random(seed)

        # Generate noise - smaller magnitude for portfolio valuation
        noise_pct = rng.gauss(0, math.sqrt(bridge_var) * 0.5)  # Reduce by half
        noise_pct = max(-0.15, min(0.15, noise_pct))  # Cap at ±15%

        return base_price * (1 + noise_pct)

    def _get_exit_price(self, signal: Dict, exit_date: str, exit_reason: str) -> float:
        """Get the exit price for a position."""
        entry_price = signal.get('entry_price', signal.get('signal_price', 0))
        entry_date_str = signal.get('entry_date', signal.get('signal_date', ''))

        entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d")
        exit_dt = datetime.strptime(exit_date, "%Y-%m-%d")
        days_held = (exit_dt - entry_dt).days

        # Use the return data we have
        if days_held >= 365 and signal.get('return_12m') is not None:
            return entry_price * (1 + signal['return_12m'])
        elif days_held >= 180 and signal.get('return_6m') is not None:
            return entry_price * (1 + signal['return_6m'])
        elif days_held >= 90 and signal.get('return_3m') is not None:
            return entry_price * (1 + signal['return_3m'])
        elif signal.get('return_current') is not None:
            return entry_price * (1 + signal['return_current'])

        # Interpolate
        return self._get_price_at_date(signal, exit_date) or entry_price

    def run_simulation(self, config: StrategyConfig) -> SimulationResult:
        """Run a full simulation with the given strategy configuration."""

        result = SimulationResult(strategy=config)

        # Portfolio state
        cash = config.initial_capital
        positions: Dict[str, Position] = {}  # ticker -> Position
        signal_map: Dict[str, Dict] = {}  # ticker -> signal data (for price lookup)

        equity_curve = []
        all_weeks = self._get_all_weeks()

        if not all_weeks:
            return result

        start_date = datetime.strptime(all_weeks[0], "%Y-%m-%d")
        end_date = datetime.now()

        # Simulate week by week
        current_date = start_date

        while current_date <= end_date:
            current_date_str = current_date.strftime("%Y-%m-%d")

            # 1. Check exits for existing positions using REAL price data
            positions_to_close = []
            for ticker, position in positions.items():
                should_exit, reason, exit_price, exit_date = self._check_exit_conditions_real(
                    position, current_date, config
                )

                if should_exit:
                    positions_to_close.append((ticker, reason, exit_price, exit_date))

            # Close positions
            for ticker, reason, exit_price, exit_date in positions_to_close:
                position = positions.pop(ticker)
                signal_map.pop(ticker, None)

                proceeds = position.shares * exit_price
                pnl = proceeds - position.cost_basis
                pnl_pct = pnl / position.cost_basis if position.cost_basis > 0 else 0

                entry_dt = datetime.strptime(position.entry_date, "%Y-%m-%d")
                exit_dt = datetime.strptime(exit_date, "%Y-%m-%d") if exit_date else current_date
                holding_days = (exit_dt - entry_dt).days

                closed = ClosedPosition(
                    ticker=ticker,
                    entry_date=position.entry_date,
                    exit_date=exit_date or current_date_str,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    shares=position.shares,
                    cost_basis=position.cost_basis,
                    proceeds=proceeds,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    holding_days=holding_days,
                    exit_reason=reason,
                    score=position.score
                )
                result.closed_positions.append(closed)
                cash += proceeds

            # 2. Check for new signals this week (on Fridays)
            if current_date.weekday() == 4:  # Friday
                week_signals = self._get_signals_for_week(current_date_str)

                for signal in week_signals:
                    ticker = signal.get('ticker', '')
                    score = signal.get('score', 0)
                    entry_price = signal.get('entry_price', signal.get('signal_price', 0))
                    entry_date = signal.get('entry_date', '')

                    # Skip if we already have this position
                    if ticker in positions:
                        continue

                    # Skip if below minimum score
                    if score < config.min_score:
                        continue

                    # Skip if above maximum score
                    if score > config.max_score:
                        continue

                    # Skip if no valid entry price
                    if not entry_price or entry_price <= 0:
                        continue

                    # Calculate position size
                    portfolio_value = cash + sum(
                        p.shares * p.current_price for p in positions.values()
                    )

                    position_size = self._calculate_position_size(
                        config, cash, portfolio_value, signal, len(positions)
                    )

                    if position_size <= 0:
                        continue

                    # Buy on Monday (entry_date)
                    shares = int(position_size / entry_price)
                    if shares <= 0:
                        continue

                    cost = shares * entry_price
                    if cost > cash:
                        continue

                    cash -= cost

                    position = Position(
                        ticker=ticker,
                        entry_date=entry_date,
                        entry_price=entry_price,
                        shares=shares,
                        cost_basis=cost,
                        score=score,
                        signal_date=current_date_str
                    )
                    positions[ticker] = position
                    signal_map[ticker] = signal

            # 3. Calculate portfolio value using REAL closing prices
            portfolio_value = cash
            for ticker, position in positions.items():
                # Get actual closing price from cached data
                current_price = self._get_close_on_date(ticker, current_date_str)
                if current_price:
                    position.current_price = current_price
                    portfolio_value += position.shares * current_price
                else:
                    # Fallback to cost basis if no price data
                    portfolio_value += position.cost_basis

            # Record equity curve (weekly)
            if current_date.weekday() == 4:  # Fridays only
                equity_curve.append((current_date_str, portfolio_value))

            current_date += timedelta(days=1)

        # Close any remaining positions at current prices
        for ticker, position in positions.items():
            signal = signal_map.get(ticker)
            if not signal:
                continue

            exit_price = position.current_price
            proceeds = position.shares * exit_price
            pnl = proceeds - position.cost_basis
            pnl_pct = pnl / position.cost_basis if position.cost_basis > 0 else 0

            entry_dt = datetime.strptime(position.entry_date, "%Y-%m-%d")
            holding_days = (end_date - entry_dt).days

            closed = ClosedPosition(
                ticker=ticker,
                entry_date=position.entry_date,
                exit_date=end_date.strftime("%Y-%m-%d"),
                entry_price=position.entry_price,
                exit_price=exit_price,
                shares=position.shares,
                cost_basis=position.cost_basis,
                proceeds=proceeds,
                pnl=pnl,
                pnl_pct=pnl_pct,
                holding_days=holding_days,
                exit_reason="end_of_sim",
                score=position.score
            )
            result.closed_positions.append(closed)
            cash += proceeds

        # Calculate final metrics
        result.equity_curve = equity_curve
        result.final_value = cash
        result.total_return = (cash - config.initial_capital) / config.initial_capital

        # CAGR
        if equity_curve:
            start_dt = datetime.strptime(equity_curve[0][0], "%Y-%m-%d")
            end_dt = datetime.strptime(equity_curve[-1][0], "%Y-%m-%d")
            years = (end_dt - start_dt).days / 365.25
            if years > 0:
                result.cagr = (cash / config.initial_capital) ** (1 / years) - 1

        # Max drawdown
        peak = config.initial_capital
        max_dd = 0
        for date, value in equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        result.max_drawdown = max_dd

        # Trade statistics
        result.total_trades = len(result.closed_positions)
        winners = [p for p in result.closed_positions if p.pnl > 0]
        losers = [p for p in result.closed_positions if p.pnl <= 0]

        result.winning_trades = len(winners)
        result.losing_trades = len(losers)
        result.win_rate = len(winners) / len(result.closed_positions) if result.closed_positions else 0

        if winners:
            result.avg_win = sum(p.pnl_pct for p in winners) / len(winners)
        if losers:
            result.avg_loss = sum(p.pnl_pct for p in losers) / len(losers)

        total_wins = sum(p.pnl for p in winners) if winners else 0
        total_losses = abs(sum(p.pnl for p in losers)) if losers else 1
        result.profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

        # Tax efficiency
        long_term = [p for p in result.closed_positions if p.is_long_term]
        result.long_term_trades = len(long_term)
        result.short_term_trades = len(result.closed_positions) - len(long_term)
        result.long_term_pct = len(long_term) / len(result.closed_positions) if result.closed_positions else 0

        return result

    def print_results(self, result: SimulationResult) -> None:
        """Print simulation results."""
        config = result.strategy

        print("\n" + "=" * 70)
        print(f"STRATEGY: {config.name}")
        print("=" * 70)

        print(f"\nConfiguration:")
        print(f"  Initial Capital:    ${config.initial_capital:,.0f}")
        print(f"  Position Size:      {config.position_size_mode} (max {config.max_position_pct:.0%})")
        print(f"  Holding Period:     {config.holding_period_days} days")
        print(f"  Stop Loss:          {config.stop_loss_pct:.0%}")
        print(f"  Min Score:          {config.min_score}")
        print(f"  Max Positions:      {config.max_positions}")

        print(f"\nPerformance:")
        print(f"  Final Value:        ${result.final_value:,.0f}")
        print(f"  Total Return:       {result.total_return:+.1%}")
        print(f"  CAGR:               {result.cagr:+.1%}")
        print(f"  Max Drawdown:       {result.max_drawdown:.1%}")
        print(f"  Profit Factor:      {result.profit_factor:.2f}")

        print(f"\nTrade Statistics:")
        print(f"  Total Trades:       {result.total_trades}")
        print(f"  Win Rate:           {result.win_rate:.1%}")
        print(f"  Avg Win:            {result.avg_win:+.1%}")
        print(f"  Avg Loss:           {result.avg_loss:+.1%}")

        print(f"\nTax Efficiency:")
        print(f"  Long-Term (>1yr):   {result.long_term_trades} ({result.long_term_pct:.1%})")
        print(f"  Short-Term:         {result.short_term_trades}")

        # Exit reason breakdown
        exit_reasons = defaultdict(int)
        for p in result.closed_positions:
            exit_reasons[p.exit_reason] += 1

        print(f"\nExit Reasons:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            pct = count / result.total_trades if result.total_trades > 0 else 0
            print(f"  {reason:15} {count:4} ({pct:.1%})")

    def plot_equity_curves(self, results: List[SimulationResult], save_path: str = None) -> None:
        """Plot equity curves for multiple strategies."""
        if not HAS_MATPLOTLIB:
            print("matplotlib not installed - skipping plots")
            return

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

        colors = ['#2ecc71', '#3498db', '#e74c3c', '#9b59b6', '#f39c12']

        # Equity curves
        for i, result in enumerate(results):
            if not result.equity_curve:
                continue

            dates = [datetime.strptime(d, "%Y-%m-%d") for d, v in result.equity_curve]
            values = [v for d, v in result.equity_curve]

            color = colors[i % len(colors)]
            ax1.plot(dates, values, label=result.strategy.name, color=color, linewidth=2)

        ax1.axhline(y=100000, color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
        ax1.set_title('Portfolio Value Over Time', fontsize=14, fontweight='bold')
        ax1.set_ylabel('Portfolio Value ($)')
        ax1.legend(loc='upper left')
        ax1.grid(True, alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

        # Returns comparison bar chart
        names = [r.strategy.name for r in results]
        returns = [r.total_return * 100 for r in results]
        cagrs = [r.cagr * 100 for r in results]

        x = range(len(names))
        width = 0.35

        bars1 = ax2.bar([i - width/2 for i in x], returns, width, label='Total Return %', color='#2ecc71')
        bars2 = ax2.bar([i + width/2 for i in x], cagrs, width, label='CAGR %', color='#3498db')

        ax2.set_ylabel('Return (%)')
        ax2.set_title('Strategy Comparison', fontsize=14, fontweight='bold')
        ax2.set_xticks(x)
        ax2.set_xticklabels(names, rotation=45, ha='right')
        ax2.legend()
        ax2.grid(True, alpha=0.3, axis='y')

        # Add value labels on bars
        for bar in bars1:
            height = bar.get_height()
            ax2.annotate(f'{height:.1f}%',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)

        for bar in bars2:
            height = bar.get_height()
            ax2.annotate(f'{height:.1f}%',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"\nChart saved to: {save_path}")

        plt.show()

    def run_rolling_analysis(
        self,
        config: StrategyConfig,
        min_gap_weeks: int = 4,
        max_gap_weeks: int = 6,
        min_holding_periods: float = 1.5
    ) -> Dict:
        """
        Run simulation from multiple start dates to remove start-date bias.

        Args:
            config: Strategy configuration
            min_gap_weeks: Minimum weeks between start dates
            max_gap_weeks: Maximum weeks between start dates
            min_holding_periods: Minimum simulation length in holding periods
                                 (e.g., 1.5 means 1.5x the holding period)

        Returns:
            Dict with mean, std, percentiles, and individual run results
        """
        all_weeks = self._get_all_weeks()
        if not all_weeks:
            return {"error": "No signals found"}

        # Calculate minimum simulation length
        min_days = int(config.holding_period_days * min_holding_periods)

        # Find valid start weeks (must have enough future data)
        last_valid_start = datetime.now() - timedelta(days=min_days)
        valid_weeks = [w for w in all_weeks
                       if datetime.strptime(w, "%Y-%m-%d") <= last_valid_start]

        if not valid_weeks:
            return {"error": "Not enough historical data for rolling analysis"}

        # Select start dates with random 4-6 week gaps
        rng = random.Random(42)  # Fixed seed for reproducibility
        start_weeks = []
        idx = 0

        while idx < len(valid_weeks):
            start_weeks.append(valid_weeks[idx])
            gap = rng.randint(min_gap_weeks, max_gap_weeks)
            idx += gap

        print(f"\nRolling Analysis: {len(start_weeks)} simulations")
        print(f"  Start dates from {start_weeks[0]} to {start_weeks[-1]}")
        print(f"  Gap between starts: {min_gap_weeks}-{max_gap_weeks} weeks (random)")

        # Run simulation from each start date
        results = []
        for i, start_week in enumerate(start_weeks):
            # Filter signals to only those on or after start_week
            original_signals = self.signals
            self.signals = [s for s in original_signals
                           if s.get('signal_date', '') >= start_week]

            if not self.signals:
                self.signals = original_signals
                continue

            result = self.run_simulation(config)
            results.append({
                'start_week': start_week,
                'total_return': result.total_return,
                'cagr': result.cagr,
                'max_drawdown': result.max_drawdown,
                'win_rate': result.win_rate,
                'total_trades': result.total_trades,
                'final_value': result.final_value,
            })

            # Restore original signals
            self.signals = original_signals

            # Progress indicator
            if (i + 1) % 5 == 0:
                print(f"  Completed {i + 1}/{len(start_weeks)} simulations...")

        if not results:
            return {"error": "No valid simulations completed"}

        # Calculate statistics
        returns = [r['total_return'] for r in results]
        cagrs = [r['cagr'] for r in results]
        drawdowns = [r['max_drawdown'] for r in results]
        win_rates = [r['win_rate'] for r in results]

        def percentile(data, p):
            sorted_data = sorted(data)
            idx = int(len(sorted_data) * p / 100)
            return sorted_data[min(idx, len(sorted_data) - 1)]

        def mean(data):
            return sum(data) / len(data) if data else 0

        def std(data):
            if len(data) < 2:
                return 0
            m = mean(data)
            variance = sum((x - m) ** 2 for x in data) / (len(data) - 1)
            return math.sqrt(variance)

        analysis = {
            'strategy': config.name,
            'num_simulations': len(results),
            'start_range': f"{start_weeks[0]} to {start_weeks[-1]}",

            'return': {
                'mean': mean(returns),
                'std': std(returns),
                'median': percentile(returns, 50),
                'p10': percentile(returns, 10),
                'p25': percentile(returns, 25),
                'p75': percentile(returns, 75),
                'p90': percentile(returns, 90),
                'min': min(returns),
                'max': max(returns),
            },

            'cagr': {
                'mean': mean(cagrs),
                'std': std(cagrs),
                'median': percentile(cagrs, 50),
                'min': min(cagrs),
                'max': max(cagrs),
            },

            'max_drawdown': {
                'mean': mean(drawdowns),
                'median': percentile(drawdowns, 50),
                'worst': max(drawdowns),
            },

            'win_rate': {
                'mean': mean(win_rates),
                'min': min(win_rates),
                'max': max(win_rates),
            },

            'individual_runs': results,
        }

        return analysis

    def print_rolling_analysis(self, analysis: Dict) -> None:
        """Print rolling analysis results."""
        if 'error' in analysis:
            print(f"Error: {analysis['error']}")
            return

        print("\n" + "=" * 70)
        print(f"ROLLING ANALYSIS: {analysis['strategy']}")
        print("=" * 70)
        print(f"\nSimulations: {analysis['num_simulations']}")
        print(f"Start Range: {analysis['start_range']}")

        r = analysis['return']
        print(f"\nTotal Return:")
        print(f"  Mean:   {r['mean']:+.1%}  (std: {r['std']:.1%})")
        print(f"  Median: {r['median']:+.1%}")
        print(f"  Range:  {r['min']:+.1%} to {r['max']:+.1%}")
        print(f"  10th-90th percentile: {r['p10']:+.1%} to {r['p90']:+.1%}")

        c = analysis['cagr']
        print(f"\nCAGR:")
        print(f"  Mean:   {c['mean']:+.1%}  (std: {c['std']:.1%})")
        print(f"  Median: {c['median']:+.1%}")
        print(f"  Range:  {c['min']:+.1%} to {c['max']:+.1%}")

        d = analysis['max_drawdown']
        print(f"\nMax Drawdown:")
        print(f"  Mean:   {d['mean']:.1%}")
        print(f"  Median: {d['median']:.1%}")
        print(f"  Worst:  {d['worst']:.1%}")

        w = analysis['win_rate']
        print(f"\nWin Rate:")
        print(f"  Mean:   {w['mean']:.1%}")
        print(f"  Range:  {w['min']:.1%} to {w['max']:.1%}")

    def generate_report(self, results: List[SimulationResult]) -> str:
        """Generate a markdown report comparing strategies."""

        lines = [
            "# Portfolio Simulation Results",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Strategy Comparison",
            "",
            "| Strategy | Final Value | Total Return | CAGR | Max DD | Win Rate | Profit Factor | LT % |",
            "|----------|-------------|--------------|------|--------|----------|---------------|------|",
        ]

        for r in results:
            lines.append(
                f"| {r.strategy.name} | ${r.final_value:,.0f} | {r.total_return:+.1%} | "
                f"{r.cagr:+.1%} | {r.max_drawdown:.1%} | {r.win_rate:.1%} | "
                f"{r.profit_factor:.2f} | {r.long_term_pct:.0%} |"
            )

        lines.extend([
            "",
            "## Strategy Details",
            "",
        ])

        for r in results:
            c = r.strategy
            lines.extend([
                f"### {c.name}",
                "",
                f"- **Position Sizing:** {c.position_size_mode} (max {c.max_position_pct:.0%})",
                f"- **Holding Period:** {c.holding_period_days} days",
                f"- **Stop Loss:** {c.stop_loss_pct:.0%}",
                f"- **Min Score:** {c.min_score}",
                f"- **Max Positions:** {c.max_positions}",
                "",
                f"**Results:**",
                f"- Trades: {r.total_trades} ({r.winning_trades}W / {r.losing_trades}L)",
                f"- Avg Win: {r.avg_win:+.1%} | Avg Loss: {r.avg_loss:+.1%}",
                f"- Long-term trades: {r.long_term_trades} ({r.long_term_pct:.0%})",
                "",
            ])

        # Tax analysis
        lines.extend([
            "## Tax Analysis",
            "",
            "Long-term capital gains (>1 year holding) are taxed at lower rates (0-20%) vs short-term (ordinary income rates up to 37%).",
            "",
            "| Strategy | LT Trades | ST Trades | LT % | Est. Tax Savings* |",
            "|----------|-----------|-----------|------|-------------------|",
        ])

        for r in results:
            # Rough tax savings estimate: assume 15% LT vs 35% ST rate
            lt_gains = sum(p.pnl for p in r.closed_positions if p.is_long_term and p.pnl > 0)
            st_gains = sum(p.pnl for p in r.closed_positions if not p.is_long_term and p.pnl > 0)
            tax_savings = lt_gains * 0.20  # 20% rate difference

            lines.append(
                f"| {r.strategy.name} | {r.long_term_trades} | {r.short_term_trades} | "
                f"{r.long_term_pct:.0%} | ${tax_savings:,.0f} |"
            )

        lines.extend([
            "",
            "*Estimated based on 20% rate differential between LT and ST capital gains",
            "",
        ])

        return "\n".join(lines)


def create_test_strategies() -> List[StrategyConfig]:
    """Create a set of strategies to test."""

    strategies = [
        # Strategy 1: Conservative 3M
        StrategyConfig(
            name="3M Hold (-25% Stop)",
            holding_period_days=90,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=5,
        ),

        # Strategy 2: Balanced 6M
        StrategyConfig(
            name="6M Hold (-25% Stop)",
            holding_period_days=180,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=5,
        ),

        # Strategy 3: Long-term 12M (tax efficient)
        StrategyConfig(
            name="12M Hold (-25% Stop)",
            holding_period_days=365,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=5,
        ),

        # Strategy 4: 13M for tax efficiency
        StrategyConfig(
            name="13M Hold (Tax Optimal)",
            holding_period_days=395,  # 13 months for safety
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=5,
        ),

        # Strategy 5: High conviction only (8+)
        StrategyConfig(
            name="High Score (8+) 12M",
            holding_period_days=365,
            stop_loss_pct=0.25,
            max_position_pct=0.06,
            max_positions=25,
            min_score=8,
        ),

        # Strategy 6: Moderate scores only (5-7) - excluding high scores
        StrategyConfig(
            name="Moderate (5-7) 12M",
            holding_period_days=365,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=5,
            max_score=7,
        ),

        # Strategy 7: Moderate scores with 13M hold (tax optimal)
        StrategyConfig(
            name="Moderate (5-7) 13M Tax",
            holding_period_days=395,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=5,
            max_score=7,
        ),

        # Strategy 8: Extended moderate (4-7)
        StrategyConfig(
            name="Score 4-7 12M",
            holding_period_days=365,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=4,
            max_score=7,
        ),

        # Strategy 9: Low scores only (1-4)
        StrategyConfig(
            name="Low Score (1-4) 12M",
            holding_period_days=365,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=1,
            max_score=4,
        ),

        # Strategy 10: Score 6-7 only (sweet spot?)
        StrategyConfig(
            name="Score 6-7 12M",
            holding_period_days=365,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=6,
            max_score=7,
        ),

        # Strategy 11: Score 5-6 only
        StrategyConfig(
            name="Score 5-6 12M",
            holding_period_days=365,
            stop_loss_pct=0.25,
            max_position_pct=0.04,
            max_positions=40,
            min_score=5,
            max_score=6,
        ),
    ]

    return strategies


async def main():
    parser = argparse.ArgumentParser(
        description="Portfolio simulator for high intent signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run default comparison:
    python portfolio_simulator.py

  Run rolling analysis (removes start-date bias):
    python portfolio_simulator.py --rolling

  Custom settings:
    python portfolio_simulator.py --capital 50000 --stop-loss 0.20
        """
    )
    parser.add_argument("--capital", type=float, default=100000,
                        help="Initial capital (default: 100000)")
    parser.add_argument("--stop-loss", type=float, default=0.25,
                        help="Stop loss percentage (default: 0.25 = 25%%)")
    parser.add_argument("--no-plot", action="store_true",
                        help="Skip plotting charts")
    parser.add_argument("--save-report", type=str,
                        help="Save markdown report to file")
    parser.add_argument("--rolling", action="store_true",
                        help="Run rolling start analysis to remove start-date bias")
    parser.add_argument("--min-gap", type=int, default=4,
                        help="Minimum weeks between rolling start dates (default: 4)")
    parser.add_argument("--max-gap", type=int, default=6,
                        help="Maximum weeks between rolling start dates (default: 6)")

    args = parser.parse_args()

    # Create simulator
    sim = PortfolioSimulator()
    sim.load_signals()

    # Rolling analysis mode
    if args.rolling:
        print("\n" + "=" * 70)
        print("ROLLING START ANALYSIS")
        print("=" * 70)
        print("This removes start-date bias by running from multiple start points")

        # Test key strategies with rolling analysis
        rolling_strategies = [
            StrategyConfig(
                name="Score 5-7, 12M Hold",
                holding_period_days=365,
                stop_loss_pct=args.stop_loss,
                max_position_pct=0.04,
                max_positions=40,
                min_score=5,
                max_score=7,
                initial_capital=args.capital,
            ),
            StrategyConfig(
                name="Score 5-7, 13M Tax",
                holding_period_days=395,
                stop_loss_pct=args.stop_loss,
                max_position_pct=0.04,
                max_positions=40,
                min_score=5,
                max_score=7,
                initial_capital=args.capital,
            ),
            StrategyConfig(
                name="All Scores (5+), 12M",
                holding_period_days=365,
                stop_loss_pct=args.stop_loss,
                max_position_pct=0.04,
                max_positions=40,
                min_score=5,
                initial_capital=args.capital,
            ),
        ]

        all_analyses = []
        for strategy in rolling_strategies:
            analysis = sim.run_rolling_analysis(
                strategy,
                min_gap_weeks=args.min_gap,
                max_gap_weeks=args.max_gap
            )
            sim.print_rolling_analysis(analysis)
            all_analyses.append(analysis)

        # Summary table
        print("\n" + "=" * 70)
        print("ROLLING ANALYSIS SUMMARY")
        print("=" * 70)
        print(f"\n{'Strategy':<22} {'Mean Ret':>10} {'Std':>8} {'Median':>9} {'10th':>8} {'90th':>8}")
        print("-" * 70)
        for a in all_analyses:
            if 'error' not in a:
                r = a['return']
                print(f"{a['strategy']:<22} {r['mean']:>+9.1%} {r['std']:>7.1%} "
                      f"{r['median']:>+8.1%} {r['p10']:>+7.1%} {r['p90']:>+7.1%}")

        return

    # Create strategies with user settings
    strategies = create_test_strategies()
    for s in strategies:
        s.initial_capital = args.capital
        s.stop_loss_pct = args.stop_loss

    # Run simulations
    print("\nRunning simulations...")
    results = []
    for strategy in strategies:
        print(f"  Simulating: {strategy.name}")
        result = sim.run_simulation(strategy)
        results.append(result)
        sim.print_results(result)

    # Summary comparison
    print("\n" + "=" * 70)
    print("SUMMARY COMPARISON")
    print("=" * 70)
    print(f"\n{'Strategy':<25} {'Return':>10} {'CAGR':>8} {'Max DD':>8} {'Win%':>7} {'LT%':>6}")
    print("-" * 70)
    for r in results:
        print(f"{r.strategy.name:<25} {r.total_return:>+9.1%} {r.cagr:>+7.1%} "
              f"{r.max_drawdown:>7.1%} {r.win_rate:>6.1%} {r.long_term_pct:>5.0%}")

    # Generate report
    report = sim.generate_report(results)

    if args.save_report:
        with open(args.save_report, 'w') as f:
            f.write(report)
        print(f"\nReport saved to: {args.save_report}")
    else:
        # Save to default location
        RESULTS_DIR.mkdir(exist_ok=True)
        report_path = RESULTS_DIR / f"simulation_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        with open(report_path, 'w') as f:
            f.write(report)
        print(f"\nReport saved to: {report_path}")

    # Plot
    if not args.no_plot and HAS_MATPLOTLIB:
        chart_path = RESULTS_DIR / f"equity_curves_{datetime.now().strftime('%Y%m%d_%H%M')}.png"
        sim.plot_equity_curves(results, save_path=str(chart_path))


if __name__ == "__main__":
    asyncio.run(main())
