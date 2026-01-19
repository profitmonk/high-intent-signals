"""
LLM Provider Factory.
Creates the appropriate provider based on configuration.
"""

from typing import Optional

from config.settings import Settings, get_settings, LLMProvider as LLMProviderType
from llm.base import LLMProvider, LLMError


def create_provider(
    provider_name: Optional[LLMProviderType] = None,
    settings: Optional[Settings] = None,
) -> LLMProvider:
    """
    Create an LLM provider instance.

    Args:
        provider_name: Provider to create. If None, uses settings.llm_provider
        settings: Application settings

    Returns:
        LLMProvider instance

    Raises:
        LLMError: If provider is unknown or not properly configured
    """
    settings = settings or get_settings()
    provider_name = provider_name or settings.llm_provider

    if provider_name == "anthropic":
        from llm.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(settings)
        if not provider.is_available():
            raise LLMError(
                "Anthropic provider selected but ANTHROPIC_API_KEY not set. "
                "Set the key in .env or choose a different provider."
            )
        return provider

    elif provider_name == "openai":
        from llm.openai_provider import OpenAIProvider
        provider = OpenAIProvider(settings)
        if not provider.is_available():
            raise LLMError(
                "OpenAI provider selected but OPENAI_API_KEY not set. "
                "Set the key in .env or choose a different provider."
            )
        return provider

    elif provider_name == "ollama":
        from llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(settings)
        # Note: Ollama availability check is optional since it's local
        return provider

    elif provider_name == "gemini":
        from llm.gemini_provider import GeminiProvider
        provider = GeminiProvider(settings)
        if not provider.is_available():
            raise LLMError(
                "Gemini provider selected but GEMINI_API_KEY not set. "
                "Set the key in .env or choose a different provider."
            )
        return provider

    else:
        raise LLMError(
            f"Unknown LLM provider: {provider_name}. "
            f"Available: anthropic, openai, ollama, gemini"
        )


# Cached provider instance
_provider_instance: Optional[LLMProvider] = None


def get_llm_provider(settings: Optional[Settings] = None) -> LLMProvider:
    """
    Get the configured LLM provider (cached singleton).

    Uses the provider specified in LLM_PROVIDER environment variable.

    Returns:
        Configured LLMProvider instance
    """
    global _provider_instance

    settings = settings or get_settings()

    # Check if we need to create a new instance
    if _provider_instance is None or _provider_instance.provider_name != settings.llm_provider:
        _provider_instance = create_provider(settings=settings)

    return _provider_instance


def reset_provider():
    """Reset the cached provider instance (useful for testing)."""
    global _provider_instance
    _provider_instance = None
