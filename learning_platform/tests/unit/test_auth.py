"""Unit tests for JWT auth helpers."""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi import HTTPException

from learning_platform.api.auth import decode_token


def _token(secret: str, payload: dict[str, object]) -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


def test_decode_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    token = _token("test-secret", {"sub": "user-1", "exp": int(time.time()) + 3600})

    decoded = decode_token(token)
    assert decoded["sub"] == "user-1"


def test_decode_token_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "")
    monkeypatch.setenv("ENVIRONMENT", "test")

    with pytest.raises(HTTPException) as exc:
        decode_token("abc")
    assert exc.value.status_code == 500
    assert "JWT_SECRET" in str(exc.value.detail)


def test_decode_token_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    token = _token("test-secret", {"sub": "user-1", "exp": int(time.time()) - 1})

    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401
    assert "expired" in str(exc.value.detail).lower()


def test_decode_token_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "good-secret")
    token = _token("wrong-secret", {"sub": "user-1", "exp": int(time.time()) + 3600})

    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401
    assert "invalid" in str(exc.value.detail).lower()
