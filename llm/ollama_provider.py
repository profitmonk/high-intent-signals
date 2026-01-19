"""
Ollama provider implementation for local LLM inference.
"""

import asyncio
from typing import Any, Dict, List, Optional

import httpx
import backoff

from config.settings import Settings, get_settings
from llm.base import LLMProvider, LLMResponse, LLMError, LLMRateLimitError, LLMConnectionError


class OllamaProvider(LLMProvider):
    """
    Ollama local LLM provider.

    Supports running local models like Llama 3.1, Mistral, etc.
    Ollama must be running locally (ollama serve).
    """

    provider_name = "ollama"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.ollama_base_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=300.0,  # Longer timeout for local inference
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def get_default_model(self) -> str:
        return self.settings.ollama_default_model

    def is_available(self) -> bool:
        """Check if Ollama is running by pinging the API."""
        try:
            import httpx
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    @backoff.on_exception(
        backoff.expo,
        (httpx.ConnectError, httpx.TimeoutException),
        max_tries=3,
        max_time=60,
    )
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate completion using Ollama API."""
        client = await self._get_client()
        model = model or self.get_default_model()

        # Ollama uses a chat endpoint similar to OpenAI
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await client.post(
                "/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "")

            # Ollama provides token counts in some responses
            eval_count = data.get("eval_count", 0)
            prompt_eval_count = data.get("prompt_eval_count", 0)

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                usage={
                    "input_tokens": prompt_eval_count,
                    "output_tokens": eval_count,
                },
                raw_response=data,
            )

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Make sure Ollama is running (ollama serve). Error: {e}"
            )
        except httpx.TimeoutException as e:
            raise LLMConnectionError(f"Ollama request timed out: {e}")
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama API error: {e}")
        except Exception as e:
            raise LLMError(f"Ollama error: {e}")

    async def complete_with_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate completion from message list."""
        client = await self._get_client()
        model = model or self.get_default_model()

        # Prepend system message if provided
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        try:
            response = await client.post(
                "/api/chat",
                json={
                    "model": model,
                    "messages": all_messages,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "")
            eval_count = data.get("eval_count", 0)
            prompt_eval_count = data.get("prompt_eval_count", 0)

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                usage={
                    "input_tokens": prompt_eval_count,
                    "output_tokens": eval_count,
                },
                raw_response=data,
            )

        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Make sure Ollama is running (ollama serve). Error: {e}"
            )
        except httpx.TimeoutException as e:
            raise LLMConnectionError(f"Ollama request timed out: {e}")
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama API error: {e}")
        except Exception as e:
            raise LLMError(f"Ollama error: {e}")

    async def list_models(self) -> List[str]:
        """List available models in Ollama."""
        client = await self._get_client()
        try:
            response = await client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except Exception:
            return []

    async def pull_model(self, model: str) -> bool:
        """Pull a model from Ollama registry."""
        client = await self._get_client()
        try:
            response = await client.post(
                "/api/pull",
                json={"name": model},
                timeout=600.0,  # Model downloads can take a while
            )
            return response.status_code == 200
        except Exception:
            return False
