"""Shared test fixtures."""

from __future__ import annotations

import pytest

from learning_platform.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Test settings — no real DB or LLM calls."""
    return Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///test.db",
        llm_base_url="http://localhost:11434",
        debug=True,
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="test-jwt-secret",
    )
