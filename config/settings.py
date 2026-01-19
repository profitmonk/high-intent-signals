"""
Configuration settings for the SP500 Research Agent.
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import Optional, Literal
from pydantic import Field
from pydantic_settings import BaseSettings


LLMProvider = Literal["anthropic", "openai", "ollama", "gemini"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    fmp_api_key: str = Field(..., env="FMP_API_KEY")
    anthropic_api_key: Optional[str] = Field(None, env="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(None, env="GEMINI_API_KEY")
    news_api_key: Optional[str] = Field(None, env="NEWS_API_KEY")
    reddit_client_id: Optional[str] = Field(None, env="REDDIT_CLIENT_ID")
    reddit_client_secret: Optional[str] = Field(None, env="REDDIT_CLIENT_SECRET")
    reddit_user_agent: str = Field("SP500ResearchAgent/1.0", env="REDDIT_USER_AGENT")
    x_bearer_token: Optional[str] = Field(None, env="X_BEARER_TOKEN")

    # LLM Provider Selection
    llm_provider: LLMProvider = Field("anthropic", env="LLM_PROVIDER")

    # Ollama Configuration
    ollama_base_url: str = Field("http://localhost:11434", env="OLLAMA_BASE_URL")

    # Model Configuration - Anthropic
    anthropic_default_model: str = Field("claude-sonnet-4-20250514", env="ANTHROPIC_DEFAULT_MODEL")
    anthropic_fast_model: str = Field("claude-3-haiku-20240307", env="ANTHROPIC_FAST_MODEL")
    anthropic_advanced_model: str = Field("claude-opus-4-20250514", env="ANTHROPIC_ADVANCED_MODEL")

    # Model Configuration - OpenAI
    openai_default_model: str = Field("gpt-4o", env="OPENAI_DEFAULT_MODEL")
    openai_fast_model: str = Field("gpt-4o-mini", env="OPENAI_FAST_MODEL")
    openai_advanced_model: str = Field("gpt-4o", env="OPENAI_ADVANCED_MODEL")

    # Model Configuration - Ollama (local)
    ollama_default_model: str = Field("llama3.1:8b", env="OLLAMA_DEFAULT_MODEL")
    ollama_fast_model: str = Field("llama3.1:8b", env="OLLAMA_FAST_MODEL")
    ollama_advanced_model: str = Field("llama3.1:70b", env="OLLAMA_ADVANCED_MODEL")

    # Model Configuration - Gemini
    gemini_default_model: str = Field("gemini-1.5-pro", env="GEMINI_DEFAULT_MODEL")
    gemini_fast_model: str = Field("gemini-1.5-flash", env="GEMINI_FAST_MODEL")
    gemini_advanced_model: str = Field("gemini-1.5-pro", env="GEMINI_ADVANCED_MODEL")

    # Legacy model fields (for backwards compatibility)
    default_model: str = Field("claude-sonnet-4-20250514", env="DEFAULT_MODEL")
    fast_model: str = Field("claude-3-haiku-20240307", env="FAST_MODEL")
    advanced_model: str = Field("claude-opus-4-20250514", env="ADVANCED_MODEL")

    # Rate Limiting
    fmp_requests_per_minute: int = Field(300, env="FMP_REQUESTS_PER_MINUTE")
    anthropic_requests_per_minute: int = Field(50, env="ANTHROPIC_REQUESTS_PER_MINUTE")

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    reports_output_dir: Optional[Path] = Field(default=None, env="REPORTS_OUTPUT_DIR")
    cache_dir: Optional[Path] = Field(default=None, env="CACHE_DIR")
    prompts_dir: Optional[Path] = Field(default=None)

    # Cache Settings
    cache_expiry_hours: int = Field(24, env="CACHE_EXPIRY_HOURS")

    # Logging
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_file: Optional[str] = Field(None, env="LOG_FILE")

    # FMP API Base URL
    fmp_base_url: str = "https://financialmodelingprep.com/api/v3"
    fmp_base_url_v4: str = "https://financialmodelingprep.com/api/v4"
    fmp_base_url_stable: str = "https://financialmodelingprep.com/stable"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Set default paths relative to base_dir
        if self.reports_output_dir is None:
            self.reports_output_dir = self.base_dir / "reports" / "output"
        if self.cache_dir is None:
            self.cache_dir = self.base_dir / "data" / "cache"
        if self.prompts_dir is None:
            self.prompts_dir = self.base_dir / "agents" / "prompts"

        # Ensure directories exist
        self.reports_output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_model_for_agent(self, agent_type: str) -> str:
        """Return the appropriate model for each agent type based on current provider."""
        fast_agents = [
            "company_profiler",
            "financial_metrics",
            "news_events",
            "social_sentiment",
            "technical_analysis",
            "etf_exposure",  # Data extraction focused
        ]
        advanced_agents = [
            "financial_forensics",
            "valuation",
            "synthesis",
        ]
        # Default tier (sonnet): sec_filings, industry_sector, moat_analyzer,
        # risk_assessment, transcript_analysis (needs nuanced language analysis)

        # Determine tier
        if agent_type in fast_agents:
            tier = "fast"
        elif agent_type in advanced_agents:
            tier = "advanced"
        else:
            tier = "default"

        # Get model for current provider and tier
        return self.get_model(tier)

    def get_model(self, tier: str = "default") -> str:
        """Get the model name for the current provider and tier."""
        provider = self.llm_provider

        model_map = {
            "anthropic": {
                "fast": self.anthropic_fast_model,
                "default": self.anthropic_default_model,
                "advanced": self.anthropic_advanced_model,
            },
            "openai": {
                "fast": self.openai_fast_model,
                "default": self.openai_default_model,
                "advanced": self.openai_advanced_model,
            },
            "ollama": {
                "fast": self.ollama_fast_model,
                "default": self.ollama_default_model,
                "advanced": self.ollama_advanced_model,
            },
            "gemini": {
                "fast": self.gemini_fast_model,
                "default": self.gemini_default_model,
                "advanced": self.gemini_advanced_model,
            },
        }

        return model_map.get(provider, model_map["anthropic"]).get(tier, model_map[provider]["default"])

    def validate_provider_config(self) -> bool:
        """Validate that the selected provider has required configuration."""
        provider = self.llm_provider

        if provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY required when using Anthropic provider")
        elif provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY required when using OpenAI provider")
        elif provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY required when using Gemini provider")
        # Ollama doesn't require an API key (runs locally)

        return True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
