"""
Helper functions for the SP500 Research Agent.
Common utilities for formatting, calculations, and data manipulation.
"""

import asyncio
import functools
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
from datetime import datetime, timedelta
import math

T = TypeVar("T")


# =============================================================================
# Formatting Functions
# =============================================================================

def format_currency(
    value: Union[int, float, None],
    currency: str = "$",
    decimals: int = 2,
    abbreviate: bool = True,
) -> str:
    """
    Format a number as currency.

    Args:
        value: Number to format
        currency: Currency symbol
        decimals: Decimal places
        abbreviate: Use K/M/B abbreviations for large numbers

    Returns:
        Formatted currency string
    """
    if value is None:
        return "N/A"

    if abbreviate:
        abs_value = abs(value)
        if abs_value >= 1_000_000_000_000:
            formatted = f"{value / 1_000_000_000_000:.{decimals}f}T"
        elif abs_value >= 1_000_000_000:
            formatted = f"{value / 1_000_000_000:.{decimals}f}B"
        elif abs_value >= 1_000_000:
            formatted = f"{value / 1_000_000:.{decimals}f}M"
        elif abs_value >= 1_000:
            formatted = f"{value / 1_000:.{decimals}f}K"
        else:
            formatted = f"{value:.{decimals}f}"
    else:
        formatted = f"{value:,.{decimals}f}"

    return f"{currency}{formatted}"


def format_percentage(
    value: Union[int, float, None],
    decimals: int = 1,
    include_sign: bool = False,
) -> str:
    """
    Format a number as percentage.

    Args:
        value: Number to format (0.15 = 15%)
        decimals: Decimal places
        include_sign: Include + for positive values

    Returns:
        Formatted percentage string
    """
    if value is None:
        return "N/A"

    pct = value * 100
    sign = "+" if include_sign and pct > 0 else ""
    return f"{sign}{pct:.{decimals}f}%"


def format_large_number(
    value: Union[int, float, None],
    decimals: int = 1,
) -> str:
    """
    Format a large number with abbreviations.

    Args:
        value: Number to format
        decimals: Decimal places

    Returns:
        Formatted string (e.g., "1.5B")
    """
    if value is None:
        return "N/A"

    abs_value = abs(value)
    sign = "-" if value < 0 else ""

    if abs_value >= 1_000_000_000_000:
        return f"{sign}{abs_value / 1_000_000_000_000:.{decimals}f}T"
    elif abs_value >= 1_000_000_000:
        return f"{sign}{abs_value / 1_000_000_000:.{decimals}f}B"
    elif abs_value >= 1_000_000:
        return f"{sign}{abs_value / 1_000_000:.{decimals}f}M"
    elif abs_value >= 1_000:
        return f"{sign}{abs_value / 1_000:.{decimals}f}K"
    else:
        return f"{sign}{abs_value:.{decimals}f}"


def format_multiple(
    value: Union[int, float, None],
    decimals: int = 1,
) -> str:
    """
    Format a valuation multiple (e.g., P/E ratio).

    Args:
        value: Multiple value
        decimals: Decimal places

    Returns:
        Formatted string (e.g., "25.3x")
    """
    if value is None:
        return "N/A"

    if math.isinf(value) or math.isnan(value):
        return "N/A"

    return f"{value:.{decimals}f}x"


# =============================================================================
# Calculation Functions
# =============================================================================

def calculate_cagr(
    start_value: float,
    end_value: float,
    years: int,
) -> Optional[float]:
    """
    Calculate Compound Annual Growth Rate.

    Args:
        start_value: Starting value
        end_value: Ending value
        years: Number of years

    Returns:
        CAGR as decimal (0.15 = 15%)
    """
    if start_value <= 0 or end_value <= 0 or years <= 0:
        return None

    try:
        return (end_value / start_value) ** (1 / years) - 1
    except (ValueError, ZeroDivisionError):
        return None


def safe_divide(
    numerator: Union[int, float, None],
    denominator: Union[int, float, None],
    default: Optional[float] = None,
) -> Optional[float]:
    """
    Safely divide two numbers, handling zero and None.

    Args:
        numerator: Dividend
        denominator: Divisor
        default: Value to return if division fails

    Returns:
        Result or default
    """
    if numerator is None or denominator is None:
        return default

    if denominator == 0:
        return default

    try:
        return numerator / denominator
    except (TypeError, ValueError):
        return default


def calculate_growth_rate(
    old_value: Union[int, float, None],
    new_value: Union[int, float, None],
) -> Optional[float]:
    """
    Calculate period-over-period growth rate.

    Args:
        old_value: Previous period value
        new_value: Current period value

    Returns:
        Growth rate as decimal (0.15 = 15%)
    """
    if old_value is None or new_value is None or old_value == 0:
        return None

    return (new_value - old_value) / abs(old_value)


def calculate_margin(
    numerator: Union[int, float, None],
    revenue: Union[int, float, None],
) -> Optional[float]:
    """
    Calculate a margin percentage.

    Args:
        numerator: Numerator (e.g., gross profit)
        revenue: Revenue (denominator)

    Returns:
        Margin as decimal (0.45 = 45%)
    """
    return safe_divide(numerator, revenue)


# =============================================================================
# Data Manipulation Functions
# =============================================================================

def dict_get_nested(
    d: Dict[str, Any],
    path: str,
    default: Any = None,
    separator: str = ".",
) -> Any:
    """
    Get a nested value from a dictionary using dot notation.

    Args:
        d: Dictionary to search
        path: Dot-separated path (e.g., "company.profile.name")
        default: Default value if not found
        separator: Path separator

    Returns:
        Value at path or default
    """
    keys = path.split(separator)
    value = d

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list):
            try:
                index = int(key)
                value = value[index]
            except (ValueError, IndexError):
                return default
        else:
            return default

    return value


def flatten_dict(
    d: Dict[str, Any],
    parent_key: str = "",
    separator: str = "_",
) -> Dict[str, Any]:
    """
    Flatten a nested dictionary.

    Args:
        d: Dictionary to flatten
        parent_key: Prefix for keys
        separator: Separator between levels

    Returns:
        Flattened dictionary
    """
    items = []

    for k, v in d.items():
        new_key = f"{parent_key}{separator}{k}" if parent_key else k

        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, separator).items())
        else:
            items.append((new_key, v))

    return dict(items)


def merge_dicts(
    *dicts: Dict[str, Any],
    deep: bool = True,
) -> Dict[str, Any]:
    """
    Merge multiple dictionaries.

    Args:
        *dicts: Dictionaries to merge
        deep: If True, merge nested dicts recursively

    Returns:
        Merged dictionary
    """
    result = {}

    for d in dicts:
        if d is None:
            continue

        for key, value in d.items():
            if (
                deep
                and key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = merge_dicts(result[key], value, deep=True)
            else:
                result[key] = value

    return result


def filter_none_values(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove None values from a dictionary.

    Args:
        d: Dictionary to filter

    Returns:
        Dictionary without None values
    """
    return {k: v for k, v in d.items() if v is not None}


# =============================================================================
# Async Utilities
# =============================================================================

def async_retry(
    max_attempts: int = 3,
    delay_seconds: float = 1.0,
    exponential_backoff: bool = True,
    exceptions: tuple = (Exception,),
):
    """
    Decorator for retrying async functions.

    Args:
        max_attempts: Maximum retry attempts
        delay_seconds: Initial delay between retries
        exponential_backoff: Use exponential backoff
        exceptions: Tuple of exceptions to catch

    Returns:
        Decorated function
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_attempts - 1:
                        delay = delay_seconds * (2 ** attempt if exponential_backoff else 1)
                        await asyncio.sleep(delay)

            raise last_exception

        return wrapper
    return decorator


async def run_with_timeout(
    coro,
    timeout_seconds: float,
    default: T = None,
) -> T:
    """
    Run a coroutine with a timeout.

    Args:
        coro: Coroutine to run
        timeout_seconds: Timeout in seconds
        default: Value to return on timeout

    Returns:
        Coroutine result or default
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return default


# =============================================================================
# Date/Time Utilities
# =============================================================================

def get_fiscal_year_end(
    month: int = 12,
    reference_date: Optional[datetime] = None,
) -> datetime:
    """
    Get the most recent fiscal year end date.

    Args:
        month: Fiscal year end month (1-12)
        reference_date: Reference date (defaults to today)

    Returns:
        Most recent fiscal year end date
    """
    if reference_date is None:
        reference_date = datetime.now()

    # If we're past the fiscal year end month, use this year
    if reference_date.month > month:
        year = reference_date.year
    else:
        year = reference_date.year - 1

    # Last day of the fiscal year end month
    if month == 12:
        return datetime(year, 12, 31)
    else:
        # First day of next month minus one day
        next_month = datetime(year if month < 12 else year + 1, (month % 12) + 1, 1)
        return next_month - timedelta(days=1)


def quarters_between(
    start_date: datetime,
    end_date: datetime,
) -> int:
    """
    Calculate number of quarters between two dates.

    Args:
        start_date: Start date
        end_date: End date

    Returns:
        Number of quarters
    """
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    return months // 3


def get_ttm_periods(
    reference_date: Optional[datetime] = None,
) -> List[str]:
    """
    Get the four quarters that make up TTM (Trailing Twelve Months).

    Args:
        reference_date: Reference date (defaults to today)

    Returns:
        List of quarter strings (e.g., ["Q1 2024", "Q4 2023", "Q3 2023", "Q2 2023"])
    """
    if reference_date is None:
        reference_date = datetime.now()

    quarters = []
    current_quarter = (reference_date.month - 1) // 3 + 1
    current_year = reference_date.year

    for i in range(4):
        q = current_quarter - i
        y = current_year

        if q <= 0:
            q += 4
            y -= 1

        quarters.append(f"Q{q} {y}")

    return quarters


# =============================================================================
# Validation Utilities
# =============================================================================

def is_valid_ticker(ticker: str) -> bool:
    """
    Validate a stock ticker symbol.

    Args:
        ticker: Ticker symbol to validate

    Returns:
        True if valid
    """
    if not ticker or not isinstance(ticker, str):
        return False

    # Basic validation: 1-5 uppercase letters, optionally with a dot and letter
    ticker = ticker.upper()
    if len(ticker) > 6:
        return False

    # Allow patterns like "BRK.B"
    parts = ticker.split(".")
    if len(parts) > 2:
        return False

    for part in parts:
        if not part.isalpha():
            return False

    return True


def validate_financial_data(data: Dict[str, Any]) -> List[str]:
    """
    Validate financial data for common issues.

    Args:
        data: Financial data dictionary

    Returns:
        List of validation warnings
    """
    warnings = []

    # Check for None values in critical fields
    critical_fields = ["revenue", "netIncome", "totalAssets", "totalLiabilities"]
    for field in critical_fields:
        if dict_get_nested(data, field) is None:
            warnings.append(f"Missing critical field: {field}")

    # Check for negative values where unexpected
    if dict_get_nested(data, "revenue", 0) < 0:
        warnings.append("Negative revenue detected")

    if dict_get_nested(data, "totalAssets", 0) < 0:
        warnings.append("Negative total assets detected")

    # Check for suspiciously round numbers (potential data issues)
    revenue = dict_get_nested(data, "revenue", 0)
    if revenue > 0 and revenue % 1_000_000_000 == 0:
        warnings.append("Revenue is suspiciously round - verify data quality")

    return warnings
