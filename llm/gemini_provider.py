"""
Google Gemini provider implementation.
"""

import asyncio
from typing import Any, Dict, List, Optional

import backoff

from config.settings import Settings, get_settings
from llm.base import LLMProvider, LLMResponse, LLMError, LLMRateLimitError, LLMConnectionError


class GeminiProvider(LLMProvider):
    """
    Google Gemini API provider.

    Supports Gemini 1.5 Pro, Gemini 1.5 Flash, and other Gemini models.
    """

    provider_name = "gemini"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client = None

    def _get_client(self):
        """Lazy initialization of Gemini client."""
        if self._client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.settings.gemini_api_key)
                self._client = genai
            except ImportError:
                raise LLMError(
                    "google-generativeai package not installed. "
                    "Run: pip install google-generativeai"
                )
        return self._client

    def get_default_model(self) -> str:
        return self.settings.gemini_default_model

    def is_available(self) -> bool:
        return bool(self.settings.gemini_api_key)

    @backoff.on_exception(
        backoff.expo,
        (Exception,),
        max_tries=5,
        max_time=120,
        giveup=lambda e: "quota" not in str(e).lower() and "rate" not in str(e).lower(),
    )
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate completion using Gemini API."""
        genai = self._get_client()
        model_name = model or self.get_default_model()

        try:
            # Create model with system instruction
            generation_config = {
                "max_output_tokens": max_tokens,
                "temperature": temperature,
            }

            model_instance = genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config,
                system_instruction=system_prompt,
            )

            # Run in executor since genai is synchronous
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: model_instance.generate_content(user_prompt)
            )

            content = ""
            if response.text:
                content = response.text

            # Extract usage metadata if available
            usage = {"input_tokens": 0, "output_tokens": 0}
            if hasattr(response, "usage_metadata"):
                usage["input_tokens"] = getattr(response.usage_metadata, "prompt_token_count", 0)
                usage["output_tokens"] = getattr(response.usage_metadata, "candidates_token_count", 0)

            return LLMResponse(
                content=content,
                model=model_name,
                provider=self.provider_name,
                usage=usage,
                raw_response=response,
            )

        except Exception as e:
            error_str = str(e).lower()
            if "quota" in error_str or "rate" in error_str or "limit" in error_str:
                raise LLMRateLimitError(f"Gemini rate limit: {e}")
            elif "connection" in error_str or "timeout" in error_str:
                raise LLMConnectionError(f"Gemini connection error: {e}")
            else:
                raise LLMError(f"Gemini API error: {e}")

    async def complete_with_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate completion from message list."""
        genai = self._get_client()
        model_name = model or self.get_default_model()

        try:
            generation_config = {
                "max_output_tokens": max_tokens,
                "temperature": temperature,
            }

            model_kwargs = {
                "model_name": model_name,
                "generation_config": generation_config,
            }
            if system_prompt:
                model_kwargs["system_instruction"] = system_prompt

            model_instance = genai.GenerativeModel(**model_kwargs)

            # Convert messages to Gemini format
            # Gemini uses "user" and "model" roles
            gemini_history = []
            for msg in messages[:-1]:  # All but last message go to history
                role = "model" if msg["role"] == "assistant" else "user"
                gemini_history.append({
                    "role": role,
                    "parts": [msg["content"]],
                })

            # Start chat with history
            chat = model_instance.start_chat(history=gemini_history)

            # Send the last message
            last_message = messages[-1]["content"] if messages else ""

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: chat.send_message(last_message)
            )

            content = ""
            if response.text:
                content = response.text

            usage = {"input_tokens": 0, "output_tokens": 0}
            if hasattr(response, "usage_metadata"):
                usage["input_tokens"] = getattr(response.usage_metadata, "prompt_token_count", 0)
                usage["output_tokens"] = getattr(response.usage_metadata, "candidates_token_count", 0)

            return LLMResponse(
                content=content,
                model=model_name,
                provider=self.provider_name,
                usage=usage,
                raw_response=response,
            )

        except Exception as e:
            error_str = str(e).lower()
            if "quota" in error_str or "rate" in error_str or "limit" in error_str:
                raise LLMRateLimitError(f"Gemini rate limit: {e}")
            elif "connection" in error_str or "timeout" in error_str:
                raise LLMConnectionError(f"Gemini connection error: {e}")
            else:
                raise LLMError(f"Gemini API error: {e}")
