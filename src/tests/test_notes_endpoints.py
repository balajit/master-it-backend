"""Integration tests for Notes API endpoints.

Tests /api/v1/notes (POST/PUT/DELETE) and
/api/v1/units/{id}/notes, /api/v1/lessons/{id}/notes,
/api/v1/courses/{id}/notes using mocked repositories.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
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

MOCK_NOTE: dict[str, Any] = {
    "id": uuid.uuid4(),
    "user_id": 1,
    "content": "My note content",
    "unit_id": uuid.uuid4(),
    "lesson_id": None,
    "created_at": NOW,
    "updated_at": None,
}

MOCK_LESSON_NOTE: dict[str, Any] = {
    "id": uuid.uuid4(),
    "user_id": 1,
    "content": "Lesson note",
    "unit_id": None,
    "lesson_id": uuid.uuid4(),
    "created_at": NOW,
    "updated_at": None,
}


@pytest.fixture()
def app():
    from main import app as _app

    yield _app
    _app.dependency_overrides.clear()


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


# ── POST /notes ──────────────────────────────────────────────────────────────


class TestCreateNote:
    def test_create_note_for_unit(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.notes.create_note",
                new=AsyncMock(return_value=MOCK_NOTE),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/notes",
                        json={
                            "content": "My note content",
                            "unit_id": str(MOCK_NOTE["unit_id"]),
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 201
        data = resp.json()
        assert data["unit_id"] == str(MOCK_NOTE["unit_id"])
        assert data["content"] == "My note content"

    def test_create_note_for_lesson(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.notes.create_note",
                new=AsyncMock(return_value=MOCK_LESSON_NOTE),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/notes",
                        json={
                            "content": "Lesson note",
                            "lesson_id": str(MOCK_LESSON_NOTE["lesson_id"]),
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 201
        assert resp.json()["lesson_id"] == str(MOCK_LESSON_NOTE["lesson_id"])

    def test_create_note_no_target_returns_422(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/notes",
                    json={"content": "orphan note"},
                    headers={"Authorization": "Bearer fake"},
                )
            return resp

        resp = _run(go())
        assert resp.status_code == 422

    def test_create_note_both_targets_returns_422(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/notes",
                    json={
                        "content": "bad",
                        "unit_id": str(uuid.uuid4()),
                        "lesson_id": str(uuid.uuid4()),
                    },
                    headers={"Authorization": "Bearer fake"},
                )
            return resp

        resp = _run(go())
        assert resp.status_code == 422


# ── PUT /notes/{id} ──────────────────────────────────────────────────────────


class TestUpdateNote:
    def test_update_own_note(self, app, mock_user):
        _override_auth(app, mock_user)
        updated = {**MOCK_NOTE, "content": "Updated content", "updated_at": NOW}

        async def go():
            with patch(
                "database.repositories.notes.update_note",
                new=AsyncMock(return_value=updated),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.put(
                        f"/api/v1/notes/{MOCK_NOTE['id']}",
                        json={"content": "Updated content"},
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert resp.json()["content"] == "Updated content"

    def test_update_not_found_returns_404(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.notes.update_note",
                new=AsyncMock(return_value=None),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.put(
                        f"/api/v1/notes/{uuid.uuid4()}",
                        json={"content": "x"},
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 404


# ── DELETE /notes/{id} ───────────────────────────────────────────────────────


class TestDeleteNote:
    def test_delete_own_note(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with (
                patch(
                    "database.repositories.notes.get_note_by_id",
                    new=AsyncMock(return_value=MOCK_NOTE),
                ),
                patch(
                    "database.repositories.notes.delete_note",
                    new=AsyncMock(return_value=True),
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.delete(
                        f"/api/v1/notes/{MOCK_NOTE['id']}",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 204

    def test_delete_not_found_returns_404(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.notes.get_note_by_id",
                new=AsyncMock(return_value=None),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.delete(
                        f"/api/v1/notes/{uuid.uuid4()}",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 404

    def test_delete_other_users_note_returns_404(self, app, mock_user):
        _override_auth(app, mock_user)
        other_user_note = {**MOCK_NOTE, "user_id": 99}

        async def go():
            with patch(
                "database.repositories.notes.get_note_by_id",
                new=AsyncMock(return_value=other_user_note),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.delete(
                        f"/api/v1/notes/{MOCK_NOTE['id']}",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 404


# ── GET /units/{id}/notes ─────────────────────────────────────────────────────


class TestGetUnitNotes:
    def test_returns_note_list(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.notes.get_notes_for_unit",
                new=AsyncMock(return_value=[MOCK_NOTE]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        f"/api/v1/units/{MOCK_NOTE['unit_id']}/notes",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["unit_id"] == str(MOCK_NOTE["unit_id"])

    def test_returns_empty_list_when_no_notes(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.notes.get_notes_for_unit",
                new=AsyncMock(return_value=[]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        f"/api/v1/units/{uuid.uuid4()}/notes",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert resp.json() == []


# ── GET /lessons/{id}/notes ───────────────────────────────────────────────────


class TestGetLessonNotes:
    def test_returns_lesson_note_list(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "database.repositories.notes.get_notes_for_lesson",
                new=AsyncMock(return_value=[MOCK_LESSON_NOTE]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        f"/api/v1/lessons/{MOCK_LESSON_NOTE['lesson_id']}/notes",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert resp.json()[0]["lesson_id"] == str(MOCK_LESSON_NOTE["lesson_id"])
