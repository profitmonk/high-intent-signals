"""
OpenAI provider implementation.
"""

import asyncio
from typing import Any, Dict, List, Optional

import backoff

from config.settings import Settings, get_settings
from llm.base import LLMProvider, LLMResponse, LLMError, LLMRateLimitError, LLMConnectionError


class OpenAIProvider(LLMProvider):
    """
    OpenAI API provider.

    Supports GPT-4o, GPT-4o-mini, and other OpenAI models.
    """

    provider_name = "openai"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client = None

    def _get_client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.settings.openai_api_key)
            except ImportError:
                raise LLMError("openai package not installed. Run: pip install openai")
        return self._client

    def get_default_model(self) -> str:
        return self.settings.openai_default_model

    def is_available(self) -> bool:
        return bool(self.settings.openai_api_key)

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
        """Generate completion using OpenAI API."""
        client = self._get_client()
        model = model or self.get_default_model()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            )

            content = ""
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content or ""

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                usage={
                    "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "output_tokens": response.usage.completion_tokens if response.usage else 0,
                },
                raw_response=response,
            )

        except Exception as e:
            error_str = str(e).lower()
            if "rate" in error_str or "limit" in error_str:
                raise LLMRateLimitError(f"OpenAI rate limit: {e}")
            elif "connection" in error_str or "timeout" in error_str:
                raise LLMConnectionError(f"OpenAI connection error: {e}")
            else:
                raise LLMError(f"OpenAI API error: {e}")

    async def complete_with_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate completion from message list."""
        client = self._get_client()
        model = model or self.get_default_model()

        # Prepend system message if provided
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=all_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            )

            content = ""
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content or ""

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                usage={
                    "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "output_tokens": response.usage.completion_tokens if response.usage else 0,
                },
                raw_response=response,
            )

        except Exception as e:
            error_str = str(e).lower()
            if "rate" in error_str or "limit" in error_str:
                raise LLMRateLimitError(f"OpenAI rate limit: {e}")
            elif "connection" in error_str or "timeout" in error_str:
                raise LLMConnectionError(f"OpenAI connection error: {e}")
            else:
                raise LLMError(f"OpenAI API error: {e}")
