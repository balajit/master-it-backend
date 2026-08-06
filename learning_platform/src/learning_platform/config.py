"""Application configuration — single source of truth for all settings."""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings

_INSECURE_DB_MARKERS: frozenset[str] = frozenset({"secure_password_here"})
_INSECURE_S3_VALUES: frozenset[str] = frozenset({"", "minioadmin"})
_INSECURE_JWT_VALUES: frozenset[str] = frozenset(
    {
        "",
        "change_me_to_a_long_random_string",
        "master-it-dev-secret-key-change-in-prod",
        "test-jwt-secret",
        "jwt-secret",
    }
)


class Settings(BaseSettings):
    """All settings are loaded from environment variables (or .env file)."""

    # --- Application ---
    app_name: str = "learning-platform"
    environment: str = "production"
    debug: bool = False

    # --- Database ---
    database_url: str = ""

    # --- File paths ---
    upload_path: str = "uploads"

    # --- Parser backend ---
    parser_backend: str = "parser2"

    # --- Figure image delivery ---
    figure_image_inline: bool = False
    # When False (default): tree endpoint returns image_url per figure node (lazy fetch).
    # When True: tree endpoint embeds base64 image_data inline.
    # Toggle via env var: FIGURE_IMAGE_INLINE=true

    # --- LLM ---
    llm_provider: str = "ollama"  # ollama | openai | anthropic
    llm_model: str = "llama3.1"
    llm_base_url: str = "http://localhost:11435/v1"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 4096
    openai_api_key: str = "sk-no-password"
    anthropic_api_key: str = ""

    # --- Storage ---
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "learning-platform"

    # --- Auth ---
    jwt_secret: str = ""

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def is_test_environment(self) -> bool:
        """Return ``True`` when running in a test environment."""
        env = self.environment.strip().lower()
        return env in {"test", "testing", "ci"}

    @model_validator(mode="after")
    def _validate_required_secrets(self) -> Settings:
        """Fail fast on missing or insecure secrets for non-test environments."""
        if self.is_test_environment:
            return self

        errors: list[str] = []

        db_url = self.database_url.strip()
        if not db_url:
            errors.append("DATABASE_URL is required")
        elif any(marker in db_url for marker in _INSECURE_DB_MARKERS):
            errors.append("DATABASE_URL contains insecure placeholder values")

        if self.s3_access_key.strip() in _INSECURE_S3_VALUES:
            errors.append("S3_ACCESS_KEY must be provided and cannot use default insecure values")

        if self.s3_secret_key.strip() in _INSECURE_S3_VALUES:
            errors.append("S3_SECRET_KEY must be provided and cannot use default insecure values")

        if self.jwt_secret.strip() in _INSECURE_JWT_VALUES:
            errors.append("JWT_SECRET must be provided and cannot use insecure placeholder values")

        provider = self.llm_provider.strip().lower()
        if provider == "openai" and not self.openai_api_key.strip():
            errors.append("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if provider == "anthropic" and not self.anthropic_api_key.strip():
            errors.append("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")

        if errors:
            joined = "; ".join(errors)
            raise ValueError(f"Invalid non-test configuration: {joined}")

        return self


def get_settings() -> Settings:
    """Factory function for dependency injection."""
    return Settings()
