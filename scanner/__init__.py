"""
High Intent Stock Signal Scanner.

Identifies stocks showing technical breakouts, unusual volume, and momentum shifts.

Modules:
- signals: Real-time signal detection logic
- scanner: Daily scanner for market movers
- historical: Historical signal detection with backtesting
"""

from scanner.signals import SignalType, Signal, SignalDetector
from scanner.scanner import StockScanner
from scanner.historical import (
    HistoricalScanner,
    HistoricalSignal,
    HistoricalConfig,
    HistoricalDataManager,
    ScoredStockWeek,
)

__all__ = [
    # Real-time
    "SignalType",
    "Signal",
    "SignalDetector",
    "StockScanner",
    # Historical
    "HistoricalScanner",
    "HistoricalSignal",
    "HistoricalConfig",
    "HistoricalDataManager",
    "ScoredStockWeek",
]
