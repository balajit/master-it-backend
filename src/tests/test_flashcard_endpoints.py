"""Integration tests for Flashcard API endpoints.

Tests:
  POST /api/v1/flashcards
  POST /api/v1/flashcards/generate (with force logic)
  PUT  /api/v1/flashcards/{id}
  DELETE /api/v1/flashcards/{id}
  GET  /api/v1/units/{id}/flashcards
  GET  /api/v1/lessons/{id}/flashcards
  GET  /api/v1/courses/{id}/flashcards
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

MOCK_CARD: dict[str, Any] = {
    "id": 1,
    "user_id": 1,
    "created_by": 1,
    "front": "What is SGD?",
    "back": "Stochastic Gradient Descent",
    "course_id": None,
    "unit_id": 10,
    "lesson_id": None,
    "is_generated": False,
    "created_at": NOW,
    "updated_at": None,
}

MOCK_GEN_CARD: dict[str, Any] = {
    **MOCK_CARD,
    "id": 2,
    "is_generated": True,
    "front": "Gradient",
    "back": "Rate of change",
}


@pytest.fixture()
def app():
    from main import app as _app

    return _app


@pytest.fixture()
def mock_user() -> dict[str, Any]:
    return {
        "id": 1,
        "email": "t@t.com",
        "name": "T",
        "picture_url": "",
        "phone": "",
        "auth_provider": "local",
        "roles": ["Student"],
        "permissions": [],
    }


def _override_auth(app, user):
    from auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user


def _run(coro):
    return asyncio.run(coro)


# ── POST /flashcards ─────────────────────────────────────────────────────────


class TestCreateFlashcard:
    def test_user_scoped_card_created(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.flashcards.create_flashcard",
                new=AsyncMock(return_value=MOCK_CARD),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards",
                        json={
                            "front": "What is SGD?",
                            "back": "SGD",
                            "scope": "user",
                            "unit_id": 10,
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 201
        assert resp.json()["front"] == "What is SGD?"
        assert resp.json()["unit_id"] == 10

    def test_course_scoped_card_created(self, app, mock_user):
        _override_auth(app, mock_user)
        course_card = {**MOCK_CARD, "user_id": None, "course_id": 5, "unit_id": None}

        async def go():
            with patch(
                "database.repositories.flashcards.create_flashcard",
                new=AsyncMock(return_value=course_card),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards",
                        json={
                            "front": "Q",
                            "back": "A",
                            "scope": "course",
                            "course_id": 5,
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 201
        assert resp.json()["user_id"] is None
        assert resp.json()["course_id"] == 5

    def test_no_target_returns_422(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/flashcards",
                    json={"front": "Q", "back": "A", "scope": "user"},
                    headers={"Authorization": "Bearer fake"},
                )
            return resp

        resp = _run(go())
        assert resp.status_code == 422

    def test_course_scope_without_course_id_returns_422(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/flashcards",
                    json={"front": "Q", "back": "A", "scope": "course", "unit_id": 1},
                    headers={"Authorization": "Bearer fake"},
                )
            return resp

        resp = _run(go())
        assert resp.status_code == 422


# ── POST /flashcards/generate ─────────────────────────────────────────────────


class TestGenerateFlashcards:
    def test_generate_returns_cards(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "routers.v1.generate_flashcards",
                new=AsyncMock(return_value=[MOCK_GEN_CARD]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={"scope": "unit", "target_id": 10, "card_scope": "user"},
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 201
        assert resp.json()[0]["is_generated"] is True

    def test_generate_409_when_cards_exist_no_force(self, app, mock_user):
        _override_auth(app, mock_user)
        from fastapi import HTTPException

        async def go():
            with patch(
                "routers.v1.generate_flashcards",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=409,
                        detail="Generated flashcards already exist for this target. Pass force=true to replace them.",
                    )
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={"scope": "unit", "target_id": 10, "card_scope": "user"},
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 409
        assert "force=true" in resp.json()["detail"]

    def test_generate_with_force_replaces_cards(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "routers.v1.generate_flashcards",
                new=AsyncMock(return_value=[MOCK_GEN_CARD]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "unit",
                            "target_id": 10,
                            "card_scope": "user",
                            "force": True,
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 201

    def test_generate_empty_when_no_lp_data(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "routers.v1.generate_flashcards",
                new=AsyncMock(return_value=[]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={"scope": "unit", "target_id": 99, "card_scope": "user"},
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 201
        assert resp.json() == []


# ── PUT /flashcards/{id} ──────────────────────────────────────────────────────


class TestUpdateFlashcard:
    def test_update_own_card(self, app, mock_user):
        _override_auth(app, mock_user)
        updated = {**MOCK_CARD, "front": "Updated Q", "updated_at": NOW}

        async def go():
            with patch(
                "database.repositories.flashcards.update_flashcard",
                new=AsyncMock(return_value=updated),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.put(
                        "/api/v1/flashcards/1",
                        json={"front": "Updated Q"},
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert resp.json()["front"] == "Updated Q"

    def test_update_neither_field_returns_422(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    "/api/v1/flashcards/1",
                    json={},
                    headers={"Authorization": "Bearer fake"},
                )
            return resp

        resp = _run(go())
        assert resp.status_code == 422

    def test_update_not_found_returns_404(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.flashcards.update_flashcard",
                new=AsyncMock(return_value=None),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.put(
                        "/api/v1/flashcards/999",
                        json={"front": "X"},
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 404


# ── DELETE /flashcards/{id} ───────────────────────────────────────────────────


class TestDeleteFlashcard:
    def test_delete_own_card(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with (
                patch(
                    "database.repositories.flashcards.get_flashcard_by_id",
                    new=AsyncMock(return_value=MOCK_CARD),
                ),
                patch(
                    "database.repositories.flashcards.delete_flashcard",
                    new=AsyncMock(return_value=True),
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.delete(
                        "/api/v1/flashcards/1",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 204

    def test_delete_other_user_card_returns_404(self, app, mock_user):
        _override_auth(app, mock_user)
        other_card = {**MOCK_CARD, "created_by": 99}

        async def go():
            with patch(
                "database.repositories.flashcards.get_flashcard_by_id",
                new=AsyncMock(return_value=other_card),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.delete(
                        "/api/v1/flashcards/1",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 404

    def test_delete_not_found_returns_404(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.flashcards.get_flashcard_by_id",
                new=AsyncMock(return_value=None),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.delete(
                        "/api/v1/flashcards/1",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 404


# ── GET /units/{id}/flashcards ────────────────────────────────────────────────


class TestGetUnitFlashcards:
    def test_returns_visible_cards(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.flashcards.get_flashcards_for_unit",
                new=AsyncMock(return_value=[MOCK_CARD]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/api/v1/units/10/flashcards",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_returns_empty_when_no_cards(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.flashcards.get_flashcards_for_unit",
                new=AsyncMock(return_value=[]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/api/v1/units/10/flashcards",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert resp.json() == []


# ── GET /lessons/{id}/flashcards ──────────────────────────────────────────────


class TestGetLessonFlashcards:
    def test_returns_lesson_cards(self, app, mock_user):
        _override_auth(app, mock_user)
        lesson_card = {**MOCK_CARD, "unit_id": None, "lesson_id": 5}

        async def go():
            with patch(
                "database.repositories.flashcards.get_flashcards_for_lesson",
                new=AsyncMock(return_value=[lesson_card]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/api/v1/lessons/5/flashcards",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert resp.json()[0]["lesson_id"] == 5


# ── GET /courses/{id}/flashcards ──────────────────────────────────────────────


class TestGetCourseFlashcards:
    def test_returns_course_cards(self, app, mock_user):
        _override_auth(app, mock_user)
        course_card = {**MOCK_CARD, "user_id": None, "unit_id": None, "course_id": 2}

        async def go():
            with patch(
                "database.repositories.flashcards.get_flashcards_for_course",
                new=AsyncMock(return_value=[course_card]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        "/api/v1/courses/2/flashcards",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert resp.json()[0]["course_id"] == 2
