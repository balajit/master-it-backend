"""Application configuration — single source of truth for all settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings are loaded from environment variables (or .env file)."""

    # --- Application ---
    app_name: str = "learning-platform"
    debug: bool = False

    # --- Database ---
    database_url: str = "postgresql+asyncpg://postgres_user:secure_password_here@localhost:5433/learning_platform_testing"

    # --- LLM ---
    llm_provider: str = "ollama"  # ollama | openai | anthropic
    llm_model: str = "llama3.1"
    llm_base_url: str = "http://localhost:11434"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 4096
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # --- Storage ---
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "learning-platform"

    # --- Auth ---
    jwt_secret: str = ""

    model_config = {"env_prefix": "", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Factory function for dependency injection."""
    return Settings()
