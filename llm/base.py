"""
Base LLM Provider interface.
All providers implement this abstract class for consistent API.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


class LLMError(Exception):
    """Base exception for LLM provider errors."""
    pass


class LLMRateLimitError(LLMError):
    """Rate limit exceeded."""
    pass


class LLMConnectionError(LLMError):
    """Connection to LLM provider failed."""
    pass


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str
    model: str
    provider: str
    usage: Dict[str, int]  # input_tokens, output_tokens
    raw_response: Optional[Any] = None

    @property
    def total_tokens(self) -> int:
        return self.usage.get("input_tokens", 0) + self.usage.get("output_tokens", 0)


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    All providers (Anthropic, OpenAI, Ollama, Gemini) implement this interface
    to provide a consistent API for the agent system.
    """

    provider_name: str = "base"

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Generate a completion from the LLM.

        Args:
            system_prompt: System-level instructions
            user_prompt: User message/query
            model: Model to use (provider-specific). If None, uses default.
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0.0 = deterministic)

        Returns:
            LLMResponse with content and metadata
        """
        pass

    @abstractmethod
    async def complete_with_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Generate a completion from a list of messages.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system_prompt: Optional system prompt
            model: Model to use
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            LLMResponse with content and metadata
        """
        pass

    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is properly configured and available."""
        pass
