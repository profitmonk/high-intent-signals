"""
Anthropic Claude provider implementation.
"""

import asyncio
from typing import Any, Dict, List, Optional

import backoff

from config.settings import Settings, get_settings
from llm.base import LLMProvider, LLMResponse, LLMError, LLMRateLimitError, LLMConnectionError


class AnthropicProvider(LLMProvider):
    """
    Anthropic Claude API provider.

    Supports Claude 3.5 Haiku, Sonnet, and Opus models.
    """

    provider_name = "anthropic"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client = None

    def _get_client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=self.settings.anthropic_api_key
                )
            except ImportError:
                raise LLMError("anthropic package not installed. Run: pip install anthropic")
        return self._client

    def get_default_model(self) -> str:
        return self.settings.anthropic_default_model

    def is_available(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    @backoff.on_exception(
        backoff.expo,
        (Exception,),
        max_tries=5,
        max_time=120,
        giveup=lambda e: "rate" not in str(e).lower() and "connection" not in str(e).lower(),
    )
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate completion using Anthropic API."""
        import anthropic

        client = self._get_client()
        model = model or self.get_default_model()

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
            )

            content = ""
            if response.content and len(response.content) > 0:
                content = response.content[0].text

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                raw_response=response,
            )

        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(f"Anthropic rate limit: {e}")
        except anthropic.APIConnectionError as e:
            raise LLMConnectionError(f"Anthropic connection error: {e}")
        except anthropic.APIError as e:
            raise LLMError(f"Anthropic API error: {e}")

    async def complete_with_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate completion from message list."""
        import anthropic

        client = self._get_client()
        model = model or self.get_default_model()

        try:
            loop = asyncio.get_event_loop()

            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            response = await loop.run_in_executor(
                None,
                lambda: client.messages.create(**kwargs)
            )

            content = ""
            if response.content and len(response.content) > 0:
                content = response.content[0].text

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                raw_response=response,
            )

        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(f"Anthropic rate limit: {e}")
        except anthropic.APIConnectionError as e:
            raise LLMConnectionError(f"Anthropic connection error: {e}")
        except anthropic.APIError as e:
            raise LLMError(f"Anthropic API error: {e}")
