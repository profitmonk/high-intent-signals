"""
Logging configuration for the SP500 Research Agent.
Uses loguru for structured, colored logging with optional file output.
"""

import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from loguru import logger

from config.settings import get_settings


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    rotation: str = "10 MB",
    retention: str = "7 days",
) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to settings value.
        log_file: Path to log file. Defaults to settings value.
        rotation: When to rotate log files. Default "10 MB".
        retention: How long to keep log files. Default "7 days".
    """
    settings = get_settings()
    level = level or settings.log_level
    log_file = log_file or settings.log_file

    # Remove default handler
    logger.remove()

    # Console handler with colors
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stderr,
        format=console_format,
        level=level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # File handler if configured
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        )

        logger.add(
            log_path,
            format=file_format,
            level=level,
            rotation=rotation,
            retention=retention,
            compression="gz",
            enqueue=True,  # Thread-safe
        )

    logger.info(f"Logging configured: level={level}, file={log_file}")


def get_logger(name: str):
    """
    Get a logger instance bound to a specific name/context.

    Args:
        name: Logger name (typically module or class name)

    Returns:
        Bound logger instance
    """
    return logger.bind(name=name)


class AgentLogger:
    """
    Context manager for logging agent execution with timing.

    Usage:
        with AgentLogger("CompanyProfiler", ticker="AAPL") as log:
            # Do work
            log.info("Processing...")
    """

    def __init__(self, agent_name: str, **context):
        """
        Initialize agent logger.

        Args:
            agent_name: Name of the agent
            **context: Additional context (ticker, etc.)
        """
        self.agent_name = agent_name
        self.context = context
        self.logger = logger.bind(agent=agent_name, **context)
        self.start_time: Optional[datetime] = None

    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.info(f"Starting {self.agent_name}")
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds()

        if exc_type is not None:
            self.logger.error(
                f"{self.agent_name} failed after {duration:.2f}s: {exc_val}"
            )
        else:
            self.logger.info(
                f"{self.agent_name} completed in {duration:.2f}s"
            )

        return False  # Don't suppress exceptions


def log_api_call(
    service: str,
    endpoint: str,
    ticker: str,
    success: bool,
    duration_ms: float,
    error: Optional[str] = None,
) -> None:
    """
    Log an API call with structured data.

    Args:
        service: API service name (e.g., "FMP", "SEC")
        endpoint: API endpoint called
        ticker: Stock ticker
        success: Whether call succeeded
        duration_ms: Call duration in milliseconds
        error: Error message if failed
    """
    log_data = {
        "service": service,
        "endpoint": endpoint,
        "ticker": ticker,
        "success": success,
        "duration_ms": round(duration_ms, 2),
    }

    if error:
        log_data["error"] = error
        logger.warning(f"API call failed: {log_data}")
    else:
        logger.debug(f"API call: {log_data}")


def log_agent_output(
    agent_name: str,
    ticker: str,
    output_keys: list[str],
    has_errors: bool = False,
) -> None:
    """
    Log agent output summary.

    Args:
        agent_name: Name of the agent
        ticker: Stock ticker
        output_keys: Keys in the output dictionary
        has_errors: Whether output contains validation errors
    """
    log_data = {
        "agent": agent_name,
        "ticker": ticker,
        "output_keys": output_keys,
        "has_errors": has_errors,
    }

    if has_errors:
        logger.warning(f"Agent output with errors: {log_data}")
    else:
        logger.info(f"Agent output: {log_data}")
