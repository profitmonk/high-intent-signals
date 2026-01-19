"""
News synthesizer that uses LLM to generate narratives from stock news.

Converts raw news articles into coherent explanations of stock movements.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import get_settings, Settings
from llm.factory import get_llm_provider
from llm.base import LLMError

logger = logging.getLogger(__name__)


class NewsSynthesizer:
    """
    Synthesizes news articles into coherent narratives using LLM.

    Takes stock data, signals, and news articles as input,
    produces a 2-3 paragraph narrative explaining the movement.
    """

    def __init__(self, settings: Optional[Settings] = None):
        """
        Initialize the synthesizer.

        Args:
            settings: Application settings (uses defaults if not provided)
        """
        self.settings = settings or get_settings()
        self._llm = None
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        """Load the system prompt from file."""
        prompt_path = Path(__file__).parent / "prompts" / "news_synthesis.md"

        if prompt_path.exists():
            return prompt_path.read_text()

        # Fallback prompt if file doesn't exist
        return """You are a financial news analyst. Synthesize the provided news articles
        into a clear 2-3 paragraph narrative explaining what's driving the stock's movement.
        Be factual, use specific numbers, and focus on the "why" behind the price action."""

    @property
    def llm(self):
        """Lazy-load the LLM provider."""
        if self._llm is None:
            self._llm = get_llm_provider(self.settings)
        return self._llm

    async def synthesize(
        self,
        ticker: str,
        company_name: str,
        price: float,
        change_pct: float,
        signals: List[str],
        signal_details: List[Dict[str, str]],
        news: List[Dict[str, Any]],
    ) -> str:
        """
        Generate a narrative for a stock based on its signals and news.

        Args:
            ticker: Stock ticker symbol
            company_name: Company name
            price: Current stock price
            change_pct: Price change percentage (as decimal, e.g., 0.05 for 5%)
            signals: List of signal types (e.g., ["ATH_BREAKOUT", "VOLUME_SPIKE"])
            signal_details: List of signal detail dicts with type, strength, description
            news: List of news articles with title, text, publishedDate, etc.

        Returns:
            Synthesized narrative string
        """
        if not news:
            return self._generate_no_news_narrative(ticker, company_name, price, change_pct, signals)

        # Build the user prompt
        user_prompt = self._build_user_prompt(
            ticker, company_name, price, change_pct, signals, signal_details, news
        )

        try:
            # Use fast model for synthesis (doesn't need deep reasoning)
            model = self.settings.get_model("fast")

            response = await self.llm.complete(
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                model=model,
                max_tokens=1024,
                temperature=0.3,  # Slight creativity for natural writing
            )

            logger.debug(
                f"Synthesized narrative for {ticker} using {response.model} "
                f"({response.total_tokens} tokens)"
            )

            return response.content.strip()

        except LLMError as e:
            logger.error(f"LLM error synthesizing {ticker}: {e}")
            return self._generate_fallback_narrative(ticker, company_name, price, change_pct, signals)

        except Exception as e:
            logger.error(f"Unexpected error synthesizing {ticker}: {e}")
            return self._generate_fallback_narrative(ticker, company_name, price, change_pct, signals)

    async def synthesize_batch(
        self,
        stocks: List[Dict[str, Any]],
        max_concurrent: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Synthesize narratives for multiple stocks.

        Args:
            stocks: List of stock dicts with ticker, company, signals, news, etc.
            max_concurrent: Maximum concurrent LLM calls

        Returns:
            Same list with 'narrative' field populated
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_stock(stock: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                narrative = await self.synthesize(
                    ticker=stock.get("ticker", ""),
                    company_name=stock.get("company", ""),
                    price=stock.get("price", 0),
                    change_pct=stock.get("change_pct", 0) / 100,  # Convert from percentage
                    signals=stock.get("signals", []),
                    signal_details=stock.get("signal_details", []),
                    news=stock.get("news", []),
                )
                stock["narrative"] = narrative
                return stock

        results = await asyncio.gather(
            *[process_stock(s) for s in stocks],
            return_exceptions=True,
        )

        # Handle any exceptions
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error processing stock {stocks[i].get('ticker', '?')}: {result}")
                stocks[i]["narrative"] = "Unable to generate narrative."
                processed.append(stocks[i])
            else:
                processed.append(result)

        return processed

    def _build_user_prompt(
        self,
        ticker: str,
        company_name: str,
        price: float,
        change_pct: float,
        signals: List[str],
        signal_details: List[Dict[str, str]],
        news: List[Dict[str, Any]],
    ) -> str:
        """Build the user prompt for the LLM."""
        # Format the change
        change_str = f"+{change_pct * 100:.1f}%" if change_pct >= 0 else f"{change_pct * 100:.1f}%"

        # Format signals
        signals_str = "\n".join(
            f"- {d.get('type', '')}: {d.get('description', '')} (strength: {d.get('strength', '')})"
            for d in signal_details
        )

        # Format news (limit to most recent 8 articles)
        news_items = []
        for article in news[:8]:
            title = article.get("title", "")
            text = article.get("text", "")[:500]  # Truncate long articles
            date = article.get("publishedDate", "")[:10]  # Just the date
            news_items.append(f"**{title}** ({date})\n{text}")

        news_str = "\n\n".join(news_items)

        return f"""## Stock Information

**Ticker:** {ticker}
**Company:** {company_name}
**Current Price:** ${price:.2f}
**Today's Change:** {change_str}

## Detected Signals

{signals_str}

## Recent News (Past 7 Days)

{news_str}

---

Please synthesize this information into a 2-3 paragraph narrative explaining what's driving {ticker}'s movement."""

    def _generate_no_news_narrative(
        self,
        ticker: str,
        company_name: str,
        price: float,
        change_pct: float,
        signals: List[str],
    ) -> str:
        """Generate a narrative when no news is available."""
        change_str = f"+{change_pct * 100:.1f}%" if change_pct >= 0 else f"{change_pct * 100:.1f}%"
        direction = "higher" if change_pct >= 0 else "lower"

        signal_descriptions = []
        if "ATH_BREAKOUT" in signals:
            signal_descriptions.append("trading near 52-week highs")
        if "VOLUME_SPIKE" in signals:
            signal_descriptions.append("with unusual volume")
        if "GAP_UP" in signals:
            signal_descriptions.append("after gapping up on the open")
        if "MOMENTUM" in signals:
            signal_descriptions.append("showing strong momentum")

        signal_text = ", ".join(signal_descriptions) if signal_descriptions else "showing technical strength"

        return (
            f"{company_name} ({ticker}) moved {change_str} {direction} to ${price:.2f}, {signal_text}. "
            f"No significant news catalysts were identified for this move, suggesting the activity may be "
            f"driven by technical factors, sector rotation, or broader market dynamics."
        )

    def _generate_fallback_narrative(
        self,
        ticker: str,
        company_name: str,
        price: float,
        change_pct: float,
        signals: List[str],
    ) -> str:
        """Generate a fallback narrative when LLM fails."""
        change_str = f"+{change_pct * 100:.1f}%" if change_pct >= 0 else f"{change_pct * 100:.1f}%"

        signal_text = ", ".join(s.replace("_", " ").title() for s in signals)

        return (
            f"{company_name} ({ticker}) is showing high-intent signals ({signal_text}) "
            f"with a {change_str} move to ${price:.2f}. See news articles for details."
        )
