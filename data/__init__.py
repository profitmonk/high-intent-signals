"""
Data clients for the High Intent Signal Scanner.

Primary data source: Financial Modeling Prep (FMP) API
"""

from data.fmp_client import FMPClient, FMPError, FMPRateLimitError

__all__ = [
    "FMPClient",
    "FMPError",
    "FMPRateLimitError",
]
