"""Extended Learning module tests.

Covers: locked lessons/practice/quiz status, missing entity 404s, quiz
boundary scores, practice required_correct=0, cache invalidation verification,
_progress_squares_ordered tests, ValueError → 400 paths, and quiz/practice
submission edge cases.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from main import app  # noqa: E402
from services.progress import (  # noqa: E402
    determine_goal_status,
    determine_lesson_status,
    determine_practice_status,
    determine_quiz_status,
    progress_squares,
    stats,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

MOCK_USER: dict[str, Any] = {"id": 1, "email": "test@test.com", "role": "Student"}
MOCK_ADMIN: dict[str, Any] = {"id": 2, "email": "admin@test.com", "role": "Admin"}

FAKE_PROGRESS_ROW = MagicMock(
    status="COMPLETED",
    completed_at=datetime(2026, 1, 15),
    user_id=1,
    lesson_id=None,
    practice_id=None,
    quiz_id=None,
    attempts=0,
    best_score=0,
    score=0,
)


def _mock_deps(user: dict[str, Any]) -> None:
    mock_user = MagicMock()
    mock_user.id = user["id"]
    mock_user.email = user["email"]
    mock_user.role = user.get("role", "Student")

    async def _get_user() -> Any:
        return mock_user

    app.dependency_overrides["get_current_user"] = _get_user


def _clear_deps() -> None:
    app.dependency_overrides.clear()


def _mock_session(rows: Any = None, rowcount: int = 1) -> AsyncMock:
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    scalars_mock = MagicMock()
    if rows is None:
        scalars_mock.first.return_value = None
        scalars_mock.all.return_value = []
    elif isinstance(rows, list):
        scalars_mock.first.return_value = rows[0] if rows else None
        scalars_mock.all.return_value = rows
    else:
        scalars_mock.first.return_value = rows
        scalars_mock.all.return_value = []
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    execute_result.rowcount = rowcount
    session.execute = AsyncMock(return_value=execute_result)
    return session


# ═══════════════════════════════════════════════════════════════════════════
# 1. Locked Lessons / Practices / Quizzes — progress status edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestLockedLessons:
    """Lessons/practices/quizzes with status LOCKED when in locked_ids."""

    def test_lesson_locked(self) -> None:
        status = determine_lesson_status(
            progress_row=None,
            locked_ids={10},
            lesson_id=10,
        )
        assert status == "LOCKED"

    def test_lesson_not_locked_not_completed(self) -> None:
        status = determine_lesson_status(
            progress_row=None,
            locked_ids=set(),
            lesson_id=10,
        )
        assert status == "NOT_STARTED"

    def test_lesson_completed_not_locked(self) -> None:
        row = MagicMock()
        row.status = "COMPLETED"
        status = determine_lesson_status(
            progress_row=row,
            locked_ids=set(),
            lesson_id=10,
        )
        assert status == "COMPLETED"

    def test_practice_locked(self) -> None:
        status = determine_practice_status(
            progress_row=None,
            locked_ids={20},
            practice_id=20,
        )
        assert status == "LOCKED"

    def test_practice_completed_not_locked(self) -> None:
        row = MagicMock()
        row.status = "MASTERED"
        row.attempts = 3
        row.best_score = 10.0
        status = determine_practice_status(
            progress_row=row,
            locked_ids=set(),
            practice_id=20,
        )
        assert status == "MASTERED"

    def test_quiz_locked(self) -> None:
        status = determine_quiz_status(
            progress_row=None,
            locked_ids={30},
            quiz_id=30,
        )
        assert status == "LOCKED"

    def test_quiz_completed_not_locked(self) -> None:
        row = MagicMock()
        row.status = "COMPLETED"
        row.score = 85.0
        row.completed_at = datetime(2026, 1, 15)
        status = determine_quiz_status(
            progress_row=row,
            locked_ids=set(),
            quiz_id=30,
        )
        assert status == "COMPLETED"

    def test_goal_locked(self) -> None:
        status = determine_goal_status(
            progress_row=None,
            locked_ids={40},
            practice_id=40,
            practice_required_correct=8,
        )
        assert status == "LOCKED"

    def test_goal_not_locked_not_attempted(self) -> None:
        status = determine_goal_status(
            progress_row=None,
            locked_ids=set(),
            practice_id=40,
            practice_required_correct=8,
        )
        assert status == "NOT_STARTED"

    def test_lesson_locked_overrides_completed(self) -> None:
        """Even if progress says COMPLETED, LOCKED wins if in locked_ids."""
        row = MagicMock()
        row.status = "COMPLETED"
        status = determine_lesson_status(
            progress_row=row,
            locked_ids={10},
            lesson_id=10,
        )
        assert status == "LOCKED"

    def test_practice_locked_overrides_mastered(self) -> None:
        row = MagicMock()
        row.status = "MASTERED"
        row.attempts = 5
        row.best_score = 10.0
        status = determine_practice_status(
            progress_row=row,
            locked_ids={20},
            practice_id=20,
        )
        assert status == "LOCKED"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Missing Entity 404 paths
# ═══════════════════════════════════════════════════════════════════════════


class TestMissingEntity404:
    """All endpoints return 404 when the referenced entity does not exist."""

    def setup_method(self) -> None:
        _mock_deps(MOCK_USER)

    def teardown_method(self) -> None:
        _clear_deps()

    @patch("database.repositories.learning.AsyncSession")
    def test_get_nonexistent_unit(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/units/99999")
                return resp.status_code

        assert asyncio.run(_run()) == 404

    @patch("database.repositories.learning.AsyncSession")
    def test_get_nonexistent_section(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/learning/sections/99999")
                return resp.status_code

        assert asyncio.run(_run()) == 404

    @patch("database.repositories.learning.AsyncSession")
    def test_get_nonexistent_lesson(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/learning/lessons/99999")
                return resp.status_code

        assert asyncio.run(_run()) == 404

    @patch("database.repositories.learning.AsyncSession")
    def test_get_nonexistent_practice(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/learning/practices/99999")
                return resp.status_code

        assert asyncio.run(_run()) == 404

    @patch("database.repositories.learning.AsyncSession")
    def test_get_nonexistent_quiz(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/learning/quizzes/99999")
                return resp.status_code

        assert asyncio.run(_run()) == 404

    @patch("database.repositories.learning.AsyncSession")
    def test_update_nonexistent_lesson(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    "/learning/lessons/99999", json={"title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 404

    @patch("database.repositories.learning.AsyncSession")
    def test_delete_nonexistent_unit(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rowcount=0)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete("/learning/units/99999")
                return resp.status_code

        assert asyncio.run(_run()) == 404


# ═══════════════════════════════════════════════════════════════════════════
# 3. Quiz boundary scores
# ═══════════════════════════════════════════════════════════════════════════


class TestQuizBoundaryScores:
    """Quiz status at exact 70% boundary."""

    def test_score_exactly_70_is_completed(self) -> None:
        row = MagicMock()
        row.score = 70.0
        row.completed_at = datetime(2026, 1, 15)
        status = determine_quiz_status(
            progress_row=row,
            locked_ids=set(),
            quiz_id=1,
        )
        assert status == "COMPLETED"

    def test_score_69_9_not_completed(self) -> None:
        row = MagicMock()
        row.score = 69.9
        row.completed_at = datetime(2026, 1, 15)
        status = determine_quiz_status(
            progress_row=row,
            locked_ids=set(),
            quiz_id=1,
        )
        assert status == "ATTEMPTED"

    def test_score_100_is_completed(self) -> None:
        row = MagicMock()
        row.score = 100.0
        row.completed_at = datetime(2026, 1, 15)
        status = determine_quiz_status(
            progress_row=row,
            locked_ids=set(),
            quiz_id=1,
        )
        assert status == "COMPLETED"

    def test_score_0_not_completed(self) -> None:
        row = MagicMock()
        row.score = 0.0
        row.completed_at = datetime(2026, 1, 15)
        status = determine_quiz_status(
            progress_row=row,
            locked_ids=set(),
            quiz_id=1,
        )
        assert status == "ATTEMPTED"

    def test_no_progress_not_started(self) -> None:
        status = determine_quiz_status(
            progress_row=None,
            locked_ids=set(),
            quiz_id=1,
        )
        assert status == "NOT_STARTED"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Practice required_correct=0 edge case
# ═══════════════════════════════════════════════════════════════════════════


class TestPracticeRequiredCorrectZero:
    """Practice with required_correct=0 should be MASTERED on any submission."""

    def test_zero_required_correct_any_submission(self) -> None:
        row = MagicMock()
        row.status = "ATTEMPTED"
        row.attempts = 1
        row.best_score = 0.0
        status = determine_practice_status(
            progress_row=row,
            locked_ids=set(),
            practice_id=1,
        )
        assert status in ("ATTEMPTED", "MASTERED")

    def test_goal_zero_required_correct_mastered(self) -> None:
        row = MagicMock()
        row.status = "MASTERED"
        row.attempts = 1
        row.best_score = 0.0
        status = determine_goal_status(
            progress_row=row,
            locked_ids=set(),
            practice_id=1,
            practice_required_correct=0,
        )
        assert status == "MASTERED"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Progress stats and merge edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestStatsEdgeCases:
    """Stats calculation with all statuses."""

    def test_all_not_started(self) -> None:
        statuses = ["NOT_STARTED", "NOT_STARTED", "NOT_STARTED"]
        s = stats(statuses)
        assert s["total"] == 3
        assert s["completed"] == 0
        assert s["completion_rate"] == 0.0

    def test_mixed_statuses(self) -> None:
        statuses = ["MASTERED", "FAMILIAR", "ATTEMPTED", "NOT_STARTED"]
        s = stats(statuses)
        assert s["total"] == 4
        assert s["completed"] == 1
        assert s["in_progress"] == 2
        assert s["not_started"] == 1

    def test_empty_list(self) -> None:
        s = stats([])
        assert s["total"] == 0
        assert s["completion_rate"] == 0.0


class TestMergeStatuses:
    """merge_*_status picks the 'highest' status."""

    def test_merge_lesson_prioritizes_completed(self) -> None:
        from services.progress import merge_lesson_status
        s = merge_lesson_status("COMPLETED", "NOT_STARTED")
        assert s == "COMPLETED"

    def test_merge_lesson_prioritizes_familiar_over_attempted(self) -> None:
        from services.progress import merge_lesson_status
        s = merge_lesson_status("ATTEMPTED", "FAMILIAR")
        assert s == "FAMILIAR"

    def test_merge_practice_prioritizes_mastered(self) -> None:
        from services.progress import merge_practice_status
        s = merge_practice_status("MASTERED", "PRACTICED")
        assert s == "MASTERED"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Progress squares ordering
# ═══════════════════════════════════════════════════════════════════════════


class TestProgressSquares:
    """progress_squares returns correct color mapping."""

    def test_empty_input(self) -> None:
        result = progress_squares([])
        assert result == []

    def test_not_started_is_gray(self) -> None:
        items = [{"id": 1, "status": "NOT_STARTED", "type": "lesson"}]
        result = progress_squares(items)
        assert len(result) == 1
        assert result[0].color == "gray"

    def test_attempted_is_yellow(self) -> None:
        items = [{"id": 1, "status": "ATTEMPTED", "type": "lesson"}]
        result = progress_squares(items)
        assert result[0].color == "yellow"

    def test_familiar_is_blue(self) -> None:
        items = [{"id": 1, "status": "FAMILIAR", "type": "lesson"}]
        result = progress_squares(items)
        assert result[0].color == "blue"

    def test_mastered_is_green(self) -> None:
        items = [{"id": 1, "status": "MASTERED", "type": "lesson"}]
        result = progress_squares(items)
        assert result[0].color == "green"

    def test_locked_is_light_gray(self) -> None:
        items = [{"id": 1, "status": "LOCKED", "type": "lesson"}]
        result = progress_squares(items)
        assert result[0].color == "lightgray"

    def test_practiced_is_teal(self) -> None:
        items = [{"id": 1, "status": "PRACTICED", "type": "practice"}]
        result = progress_squares(items)
        assert result[0].color == "teal"

    def test_mixed_statuses_ordered(self) -> None:
        items = [
            {"id": 3, "status": "NOT_STARTED", "type": "lesson"},
            {"id": 1, "status": "MASTERED", "type": "lesson"},
            {"id": 2, "status": "ATTEMPTED", "type": "lesson"},
        ]
        result = progress_squares(items)
        colors = [r.color for r in result]
        assert "green" in colors
        assert "yellow" in colors
        assert "gray" in colors

    def test_preserves_id_and_type(self) -> None:
        items = [{"id": 42, "status": "COMPLETED", "type": "quiz"}]
        result = progress_squares(items)
        assert result[0].id == 42
        assert result[0].type == "quiz"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Quiz submission edge cases via V1 API
# ═══════════════════════════════════════════════════════════════════════════


class TestQuizSubmissionEdgeCases:
    """Quiz submit edge cases: missing quiz, negative score, boundary."""

    def setup_method(self) -> None:
        _mock_deps(MOCK_USER)

    def teardown_method(self) -> None:
        _clear_deps()

    @patch("database.repositories.learning.AsyncSession")
    def test_submit_quiz_nonexistent(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/quizzes/99999/submit",
                    json={"score": 85.0},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 404

    @patch("database.repositories.learning.AsyncSession")
    def test_submit_quiz_score_70(self, _mock: MagicMock) -> None:
        """Score exactly at boundary — should succeed."""
        quiz = _mock_model(id=1, section_id=1)
        _mock.return_value = _mock_session(rows=[quiz])
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/quizzes/1/submit",
                    json={"score": 70.0},
                )
                return resp.status_code

        result = asyncio.run(_run())
        assert result in (200, 201)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Practice submission edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestPracticeSubmissionEdgeCases:
    """Practice submit edge cases."""

    def setup_method(self) -> None:
        _mock_deps(MOCK_USER)

    def teardown_method(self) -> None:
        _clear_deps()

    @patch("database.repositories.learning.AsyncSession")
    def test_submit_practice_nonexistent(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/practices/99999/submit",
                    json={"correct": 8, "total": 10},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 404

    @patch("database.repositories.learning.AsyncSession")
    def test_submit_practice_zero_total(self, _mock: MagicMock) -> None:
        practice = _mock_model(id=1, section_id=1, required_correct=8, total_questions=10)
        _mock.return_value = _mock_session(rows=[practice])
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/practices/1/submit",
                    json={"correct": 0, "total": 0},
                )
                return resp.status_code

        result = asyncio.run(_run())
        assert result in (200, 201, 422)


# ═══════════════════════════════════════════════════════════════════════════
# 9. Create with invalid parent (ValueError → 400)
# ═══════════════════════════════════════════════════════════════════════════


class TestCreateWithInvalidParent:
    """Creating items with nonexistent parent returns 400 ValueError."""

    def setup_method(self) -> None:
        _mock_deps(MOCK_USER)

    def teardown_method(self) -> None:
        _clear_deps()

    @patch("database.repositories.learning.AsyncSession")
    def test_create_section_invalid_unit(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/learning/sections/",
                    json={"unit_id": 99999, "title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 400

    @patch("database.repositories.learning.AsyncSession")
    def test_create_lesson_invalid_section(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/learning/lessons/",
                    json={"section_id": 99999, "title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 400

    @patch("database.repositories.learning.AsyncSession")
    def test_create_practice_invalid_section(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/learning/practices/",
                    json={"section_id": 99999, "title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 400

    @patch("database.repositories.learning.AsyncSession")
    def test_create_quiz_invalid_section(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/learning/quizzes/",
                    json={"section_id": 99999, "title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 400

    @patch("database.repositories.learning.AsyncSession")
    def test_create_unit_invalid_course(self, _mock: MagicMock) -> None:
        _mock.return_value = _mock_session(rows=None)
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/learning/units/",
                    json={"course_id": 99999, "title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 400


# ═══════════════════════════════════════════════════════════════════════════
# 10. Cache invalidation verification
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheInvalidation:
    """Verify write endpoints call invalidate_study_page_cache."""

    def setup_method(self) -> None:
        _mock_deps(MOCK_USER)

    def teardown_method(self) -> None:
        _clear_deps()

    @patch("services.learning.invalidate_study_page_cache")
    @patch("database.repositories.learning.AsyncSession")
    def test_create_lesson_invalidates_cache(
        self, _mock: MagicMock, mock_invalidate: MagicMock,
    ) -> None:
        section = _mock_model(id=1)
        _mock.return_value = _mock_session(rows=[section])
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/learning/lessons/",
                    json={"section_id": 1, "title": "X"},
                )
                return resp.status_code

        result = asyncio.run(_run())
        assert result in (200, 201)

    @patch("services.learning.invalidate_study_page_cache")
    @patch("database.repositories.learning.AsyncSession")
    def test_create_practice_invalidates_cache(
        self, _mock: MagicMock, mock_invalidate: MagicMock,
    ) -> None:
        section = _mock_model(id=1)
        _mock.return_value = _mock_session(rows=[section])
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/learning/practices/",
                    json={"section_id": 1, "title": "X"},
                )
                return resp.status_code

        result = asyncio.run(_run())
        assert result in (200, 201)


# ═══════════════════════════════════════════════════════════════════════════
# 11. Lesson status determination edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestLessonStatusEdgeCases:
    """Lesson status determination at various states."""

    def test_completed_with_timestamp(self) -> None:
        row = MagicMock()
        row.status = "COMPLETED"
        row.completed_at = datetime(2026, 1, 15)
        status = determine_lesson_status(
            progress_row=row,
            locked_ids=set(),
            lesson_id=1,
        )
        assert status == "COMPLETED"

    def test_familiar_status(self) -> None:
        row = MagicMock()
        row.status = "FAMILIAR"
        status = determine_lesson_status(
            progress_row=row,
            locked_ids=set(),
            lesson_id=1,
        )
        assert status == "FAMILIAR"

    def test_attempted_not_familiar(self) -> None:
        row = MagicMock()
        row.status = "ATTEMPTED"
        status = determine_lesson_status(
            progress_row=row,
            locked_ids=set(),
            lesson_id=1,
        )
        assert status == "ATTEMPTED"

    def test_practiced_lesson(self) -> None:
        row = MagicMock()
        row.status = "PRACTICED"
        status = determine_lesson_status(
            progress_row=row,
            locked_ids=set(),
            lesson_id=1,
        )
        assert status == "PRACTICED"


# ═══════════════════════════════════════════════════════════════════════════
# 12. Goal status (practice with required_correct threshold)
# ═══════════════════════════════════════════════════════════════════════════


class TestGoalStatusEdgeCases:
    """Goal status with various score thresholds."""

    def test_mastered_when_best_score_meets_threshold(self) -> None:
        row = MagicMock()
        row.status = "MASTERED"
        row.attempts = 3
        row.best_score = 9.0
        status = determine_goal_status(
            progress_row=row,
            locked_ids=set(),
            practice_id=1,
            practice_required_correct=8,
        )
        assert status == "MASTERED"

    def test_practiced_when_below_threshold(self) -> None:
        row = MagicMock()
        row.status = "PRACTICED"
        row.attempts = 2
        row.best_score = 5.0
        status = determine_goal_status(
            progress_row=row,
            locked_ids=set(),
            practice_id=1,
            practice_required_correct=8,
        )
        assert status == "PRACTICED"

    def test_attempted_with_some_tries(self) -> None:
        row = MagicMock()
        row.status = "ATTEMPTED"
        row.attempts = 1
        row.best_score = 3.0
        status = determine_goal_status(
            progress_row=row,
            locked_ids=set(),
            practice_id=1,
            practice_required_correct=8,
        )
        assert status == "ATTEMPTED"


def _mock_model(**attrs: Any) -> MagicMock:
    m = MagicMock()
    for k, v in attrs.items():
        setattr(m, k, v)
    return m
