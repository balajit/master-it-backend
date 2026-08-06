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

MOCK_CARD: dict[str, Any] = {
    "id": uuid.uuid4(),
    "user_id": 1,
    "created_by": 1,
    "front": "What is SGD?",
    "back": "Stochastic Gradient Descent",
    "course_id": None,
    "unit_id": uuid.uuid4(),
    "lesson_id": None,
    "is_generated": False,
    "created_at": NOW,
    "updated_at": None,
}

MOCK_GEN_CARD: dict[str, Any] = {
    **MOCK_CARD,
    "id": uuid.uuid4(),
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
                            "unit_id": str(MOCK_CARD["unit_id"]),
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 201
        assert resp.json()["front"] == "What is SGD?"
        assert resp.json()["unit_id"] == str(MOCK_CARD["unit_id"])

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
                    json={
                        "front": "Q",
                        "back": "A",
                        "scope": "course",
                        "unit_id": str(uuid.uuid4()),
                    },
                    headers={"Authorization": "Bearer fake"},
                )
            return resp

        resp = _run(go())
        assert resp.status_code == 422


# ── POST /flashcards/generate ─────────────────────────────────────────────────


class TestGenerateFlashcards:
    def test_generate_returns_cards(self, app, mock_user):
        _override_auth(app, mock_user)
        target_id = str(uuid.uuid4())

        async def go():
            with patch(
                "routers.v1.generate_flashcards",
                new=AsyncMock(return_value=[MOCK_GEN_CARD]),
            ) as mock_generate:
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "unit",
                            "target_id": target_id,
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_generate

        resp, mock_generate = _run(go())
        assert resp.status_code == 201
        assert resp.json()[0]["is_generated"] is True
        mock_generate.assert_awaited_once()
        mock_generate.assert_awaited_once()

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
            ) as mock_generate:
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "unit",
                            "target_id": str(uuid.uuid4()),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_generate

        resp, mock_generate = _run(go())
        assert resp.status_code == 409
        assert "force=true" in resp.json()["detail"]
        mock_generate.assert_awaited_once()

    def test_generate_with_force_replaces_cards(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "routers.v1.generate_flashcards",
                new=AsyncMock(return_value=[MOCK_GEN_CARD]),
            ) as mock_generate:
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "unit",
                            "target_id": str(uuid.uuid4()),
                            "card_scope": "user",
                            "force": True,
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_generate

        resp, mock_generate = _run(go())
        assert resp.status_code == 201
        mock_generate.assert_awaited_once()

    def test_generate_empty_when_no_lp_data(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with patch(
                "routers.v1.generate_flashcards",
                new=AsyncMock(return_value=[]),
            ) as mock_generate:
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "unit",
                            "target_id": str(uuid.uuid4()),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_generate

        resp, mock_generate = _run(go())
        assert resp.status_code == 201
        assert resp.json() == []
        mock_generate.assert_awaited_once()


# ── POST /flashcards/generate (lesson scope) ──────────────────────────────────


class _FakeLessonGenerator:
    def __init__(self, seeds: list[dict[str, str]]):
        self.seeds = seeds

    async def generate(self) -> list[dict[str, str]]:
        return self.seeds


class _RaisingLessonGenerator:
    async def generate(self) -> list[dict[str, str]]:
        raise RuntimeError("boom")


class TestGenerateLessonFlashcards:
    def _lesson_card(self, target_id):
        return {
            **MOCK_GEN_CARD,
            "id": uuid.uuid4(),
            "unit_id": None,
            "lesson_id": target_id,
        }

    @staticmethod
    def _request_dict(target_id, status="in_progress", request_id=None):
        return {
            "request_id": request_id or uuid.uuid4(),
            "user_id": 1,
            "scope": "lesson",
            "target_id": target_id,
            "status": status,
            "created_at": NOW,
            "updated_at": None,
        }

    def _patch_request_repo(self, target_id, created=True, status="in_progress"):
        request = self._request_dict(target_id, status=status)
        create_mock = AsyncMock(return_value=(request, created))
        complete_mock = AsyncMock()
        return (
            patch(
                "database.repositories.flashcard_requests.create_flashcards_request",
                new=create_mock,
            ),
            patch(
                "database.repositories.flashcard_requests.complete_flashcards_request",
                new=complete_mock,
            ),
            create_mock,
            complete_mock,
        )

    def test_lesson_scope_generates_and_persists_cards(self, app, mock_user):
        _override_auth(app, mock_user)
        target_id = uuid.uuid4()

        async def go():
            create_patch, complete_patch, create_mock, complete_mock = (
                self._patch_request_repo(target_id)
            )
            with (
                create_patch,
                complete_patch,
                patch(
                    "routers.v1.FlashCardGenerator",
                    return_value=_FakeLessonGenerator(
                        [{"front": "Gradient", "back": "Rate of change"}]
                    ),
                ) as mock_generator,
                patch("routers.v1.CuratorAgent", return_value=object()) as mock_curator,
                patch(
                    "database.repositories.flashcards.bulk_create_flashcards",
                    new=AsyncMock(return_value=[self._lesson_card(target_id)]),
                ) as mock_bulk,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "lesson",
                            "target_id": str(target_id),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return (
                resp,
                mock_generator,
                mock_curator,
                mock_bulk,
                create_mock,
                complete_mock,
            )

        (
            resp,
            mock_generator,
            mock_curator,
            mock_bulk,
            create_mock,
            complete_mock,
        ) = _run(go())
        assert resp.status_code == 201
        assert resp.json()[0]["lesson_id"] == str(target_id)
        assert resp.json()[0]["is_generated"] is True
        mock_generator.assert_called_once_with(
            lesson_id=target_id, curator=mock_curator.return_value
        )
        create_mock.assert_awaited_once_with(
            scope="lesson", target_id=target_id, user_id=1
        )
        mock_bulk.assert_awaited_once()
        record = mock_bulk.await_args.args[0][0]
        assert record["lesson_id"] == target_id
        assert record["unit_id"] is None
        assert record["course_id"] is None
        assert record["user_id"] == 1
        assert record["created_by"] == 1
        assert record["is_generated"] is True
        complete_mock.assert_awaited_once_with(
            create_mock.return_value[0]["request_id"], "completed"
        )

    def test_lesson_scope_duplicate_inflight_returns_request_info(self, app, mock_user):
        _override_auth(app, mock_user)
        target_id = uuid.uuid4()

        async def go():
            create_patch, complete_patch, create_mock, complete_mock = (
                self._patch_request_repo(target_id, created=False, status="in_progress")
            )
            with (
                create_patch,
                complete_patch,
                patch(
                    "routers.v1.FlashCardGenerator",
                    new=AsyncMock(side_effect=AssertionError("must not be used")),
                ) as mock_generator,
                patch("routers.v1.CuratorAgent", return_value=object()),
                patch(
                    "database.repositories.flashcards.bulk_create_flashcards",
                    new=AsyncMock(),
                ) as mock_bulk,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "lesson",
                            "target_id": str(target_id),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_generator, mock_bulk, create_mock, complete_mock

        resp, mock_generator, mock_bulk, create_mock, complete_mock = _run(go())
        assert resp.status_code == 200
        body = resp.json()
        assert body["request_id"] == str(create_mock.return_value[0]["request_id"])
        assert body["scope"] == "lesson"
        assert body["target_id"] == str(target_id)
        assert body["status"] == "in_progress"
        mock_generator.assert_not_called()
        mock_bulk.assert_not_awaited()
        complete_mock.assert_not_awaited()

    def test_lesson_scope_course_card_scope_leaves_user_id_none(self, app, mock_user):
        _override_auth(app, mock_user)
        target_id = uuid.uuid4()

        async def go():
            create_patch, complete_patch, create_mock, complete_mock = (
                self._patch_request_repo(target_id)
            )
            with (
                create_patch,
                complete_patch,
                patch(
                    "routers.v1.FlashCardGenerator",
                    return_value=_FakeLessonGenerator([{"front": "F", "back": "B"}]),
                ),
                patch("routers.v1.CuratorAgent", return_value=object()),
                patch(
                    "database.repositories.flashcards.bulk_create_flashcards",
                    new=AsyncMock(return_value=[self._lesson_card(target_id)]),
                ) as mock_bulk,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "lesson",
                            "target_id": str(target_id),
                            "card_scope": "course",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_bulk

        resp, mock_bulk = _run(go())
        assert resp.status_code == 201
        assert mock_bulk.await_args.args[0][0]["user_id"] is None

    def test_lesson_scope_existing_cards_are_not_a_conflict(self, app, mock_user):
        _override_auth(app, mock_user)
        target_id = uuid.uuid4()

        async def go():
            create_patch, complete_patch, create_mock, complete_mock = (
                self._patch_request_repo(target_id)
            )
            with (
                create_patch,
                complete_patch,
                patch(
                    "routers.v1.FlashCardGenerator",
                    return_value=_FakeLessonGenerator(
                        [{"front": "Gradient", "back": "Rate of change"}]
                    ),
                ),
                patch("routers.v1.CuratorAgent", return_value=object()),
                patch(
                    "database.repositories.flashcards.get_generated_flashcards",
                    new=AsyncMock(return_value=[self._lesson_card(target_id)]),
                ) as mock_get,
                patch(
                    "database.repositories.flashcards.delete_generated_flashcards",
                    new=AsyncMock(),
                ) as mock_delete,
                patch(
                    "database.repositories.flashcards.bulk_create_flashcards",
                    new=AsyncMock(return_value=[self._lesson_card(target_id)]),
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "lesson",
                            "target_id": str(target_id),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_get, mock_delete

        resp, mock_get, mock_delete = _run(go())
        assert resp.status_code == 201
        mock_get.assert_not_awaited()
        mock_delete.assert_not_awaited()

    def test_lesson_scope_force_does_not_delete_existing(self, app, mock_user):
        _override_auth(app, mock_user)
        target_id = uuid.uuid4()

        async def go():
            create_patch, complete_patch, create_mock, complete_mock = (
                self._patch_request_repo(target_id)
            )
            with (
                create_patch,
                complete_patch,
                patch(
                    "routers.v1.FlashCardGenerator",
                    return_value=_FakeLessonGenerator(
                        [{"front": "Gradient", "back": "Rate of change"}]
                    ),
                ),
                patch("routers.v1.CuratorAgent", return_value=object()),
                patch(
                    "database.repositories.flashcards.delete_generated_flashcards",
                    new=AsyncMock(),
                ) as mock_delete,
                patch(
                    "database.repositories.flashcards.bulk_create_flashcards",
                    new=AsyncMock(return_value=[self._lesson_card(target_id)]),
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "lesson",
                            "target_id": str(target_id),
                            "card_scope": "user",
                            "force": True,
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_delete

        resp, mock_delete = _run(go())
        assert resp.status_code == 201
        mock_delete.assert_not_awaited()

    def test_lesson_scope_no_cards_returns_empty(self, app, mock_user):
        _override_auth(app, mock_user)
        target_id = uuid.uuid4()

        async def go():
            create_patch, complete_patch, create_mock, complete_mock = (
                self._patch_request_repo(target_id)
            )
            with (
                create_patch,
                complete_patch,
                patch(
                    "routers.v1.FlashCardGenerator",
                    return_value=_FakeLessonGenerator([]),
                ),
                patch("routers.v1.CuratorAgent", return_value=object()),
                patch(
                    "database.repositories.flashcards.bulk_create_flashcards",
                    new=AsyncMock(return_value=[]),
                ) as mock_bulk,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "lesson",
                            "target_id": str(target_id),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_bulk, create_mock, complete_mock

        resp, mock_bulk, create_mock, complete_mock = _run(go())
        assert resp.status_code == 201
        assert resp.json() == []
        mock_bulk.assert_awaited_once()
        complete_mock.assert_awaited_once_with(
            create_mock.return_value[0]["request_id"], "completed"
        )

    def test_lesson_scope_generator_failure_returns_empty_and_marks_failed(
        self, app, mock_user
    ):
        _override_auth(app, mock_user)
        target_id = uuid.uuid4()

        async def go():
            create_patch, complete_patch, create_mock, complete_mock = (
                self._patch_request_repo(target_id)
            )
            with (
                create_patch,
                complete_patch,
                patch(
                    "routers.v1.FlashCardGenerator",
                    return_value=_RaisingLessonGenerator(),
                ),
                patch("routers.v1.CuratorAgent", return_value=object()),
                patch(
                    "database.repositories.flashcards.bulk_create_flashcards",
                    new=AsyncMock(),
                ) as mock_bulk,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "lesson",
                            "target_id": str(target_id),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_bulk, create_mock, complete_mock

        resp, mock_bulk, create_mock, complete_mock = _run(go())
        assert resp.status_code == 201
        assert resp.json() == []
        mock_bulk.assert_not_awaited()
        complete_mock.assert_awaited_once_with(
            create_mock.return_value[0]["request_id"], "failed"
        )

    def test_lesson_scope_constructor_failure_marks_failed(self, app, mock_user):
        """An exception while constructing the generator (right after the
        request is recorded) must mark the request failed, not leave it stuck
        ``in_progress`` forever (which would block reprocessing)."""
        _override_auth(app, mock_user)
        target_id = uuid.uuid4()

        async def go():
            create_patch, complete_patch, create_mock, complete_mock = (
                self._patch_request_repo(target_id)
            )
            with (
                create_patch,
                complete_patch,
                patch(
                    "routers.v1.FlashCardGenerator",
                    side_effect=RuntimeError("boom"),
                ),
                patch("routers.v1.CuratorAgent", return_value=object()),
                patch(
                    "database.repositories.flashcards.bulk_create_flashcards",
                    new=AsyncMock(),
                ) as mock_bulk,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "lesson",
                            "target_id": str(target_id),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_bulk, create_mock, complete_mock

        resp, mock_bulk, create_mock, complete_mock = _run(go())
        assert resp.status_code == 201
        assert resp.json() == []
        mock_bulk.assert_not_awaited()
        complete_mock.assert_awaited_once_with(
            create_mock.return_value[0]["request_id"], "failed"
        )

    def test_unit_scope_does_not_use_lesson_generator(self, app, mock_user):
        _override_auth(app, mock_user)

        async def go():
            with (
                patch(
                    "routers.v1.FlashCardGenerator",
                    new=AsyncMock(side_effect=AssertionError("must not be used")),
                ) as mock_generator,
                patch(
                    "routers.v1.generate_flashcards",
                    new=AsyncMock(return_value=[MOCK_GEN_CARD]),
                ) as mock_generate,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/flashcards/generate",
                        json={
                            "scope": "unit",
                            "target_id": str(uuid.uuid4()),
                            "card_scope": "user",
                        },
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp, mock_generator, mock_generate

        resp, mock_generator, mock_generate = _run(go())
        assert resp.status_code == 201
        mock_generator.assert_not_awaited()
        mock_generate.assert_awaited_once()


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
                        f"/api/v1/flashcards/{MOCK_CARD['id']}",
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
                    f"/api/v1/flashcards/{uuid.uuid4()}",
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
                        f"/api/v1/flashcards/{uuid.uuid4()}",
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
                        f"/api/v1/flashcards/{MOCK_CARD['id']}",
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
                        f"/api/v1/flashcards/{MOCK_CARD['id']}",
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
                        f"/api/v1/flashcards/{uuid.uuid4()}",
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
                        f"/api/v1/units/{MOCK_CARD['unit_id']}/flashcards",
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
                        f"/api/v1/units/{uuid.uuid4()}/flashcards",
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
        lesson_card = {**MOCK_CARD, "unit_id": None, "lesson_id": uuid.uuid4()}

        async def go():
            with patch(
                "database.repositories.flashcards.get_flashcards_for_lesson",
                new=AsyncMock(return_value=[lesson_card]),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(
                        f"/api/v1/lessons/{lesson_card['lesson_id']}/flashcards",
                        headers={"Authorization": "Bearer fake"},
                    )
            return resp

        resp = _run(go())
        assert resp.status_code == 200
        assert resp.json()[0]["lesson_id"] == str(lesson_card["lesson_id"])


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
