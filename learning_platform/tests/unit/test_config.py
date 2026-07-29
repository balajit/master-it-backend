"""Unit tests for learning_platform configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning_platform.config import Settings


def _valid_non_test_kwargs() -> dict[str, object]:
    return {
        "environment": "production",
        "database_url": "postgresql+asyncpg://lp_user:strongpass@localhost:5433/lp_prod",
        "s3_access_key": "lp-access",
        "s3_secret_key": "lp-secret",
        "jwt_secret": "lp-prod-jwt-secret",
    }


def test_non_test_requires_database_url() -> None:
    kwargs = _valid_non_test_kwargs()
    kwargs["database_url"] = ""

    with pytest.raises(ValidationError, match="DATABASE_URL is required"):
        Settings(**kwargs)


def test_non_test_rejects_placeholder_database_url() -> None:
    kwargs = _valid_non_test_kwargs()
    kwargs["database_url"] = (
        "postgresql+asyncpg://postgres_user:secure_password_here@localhost:5433/learning_platform_testing"
    )

    with pytest.raises(ValidationError, match="DATABASE_URL contains insecure placeholder values"):
        Settings(**kwargs)


def test_non_test_requires_s3_and_jwt_secrets() -> None:
    kwargs = _valid_non_test_kwargs()
    kwargs["s3_access_key"] = ""
    kwargs["s3_secret_key"] = ""
    kwargs["jwt_secret"] = ""

    with pytest.raises(ValidationError, match="S3_ACCESS_KEY"):
        Settings(**kwargs)


def test_non_test_rejects_insecure_jwt_placeholders() -> None:
    kwargs = _valid_non_test_kwargs()
    kwargs["jwt_secret"] = "change_me_to_a_long_random_string"

    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(**kwargs)


def test_non_test_openai_requires_api_key() -> None:
    kwargs = _valid_non_test_kwargs()
    kwargs["llm_provider"] = "openai"
    kwargs["openai_api_key"] = ""

    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(**kwargs)


def test_non_test_anthropic_requires_api_key() -> None:
    kwargs = _valid_non_test_kwargs()
    kwargs["llm_provider"] = "anthropic"
    kwargs["anthropic_api_key"] = ""

    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(**kwargs)


def test_test_environment_allows_insecure_defaults() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://postgres_user:secure_password_here@localhost:5433/learning_platform_testing",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="",
    )

    assert settings.is_test_environment is True
