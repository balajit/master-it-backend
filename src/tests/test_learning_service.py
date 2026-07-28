"""Tests for the Learning Service layer (batch-optimized)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from services.learning import (
    get_unit_details,
    _study_page_cache,
    invalidate_study_page_cache,
)

# Reuse a single event loop for all tests in this module to avoid
# "Future attached to a different loop" errors from SQLAlchemy's async pool.
_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()


def run_sync(coro):
    """Run a coroutine on the module-level event loop."""
    return _loop.run_until_complete(coro)


def _dispose_engine() -> None:
    """Dispose the SQLAlchemy async engine pool so the next test gets fresh
    connections bound to _loop rather than a stale loop from a prior test file."""
    try:
        from db import engine  # type: ignore[import]

        run_sync(engine.dispose())
    except Exception:
        pass


async def _reset_engine() -> None:
    """Async variant — dispose engine inside the running loop."""
    try:
        from db import engine  # type: ignore[import]

        await engine.dispose()
    except Exception:
        pass


MOCK_UNIT: Dict[str, Any] = {
    "id": 1,
    "course_id": 1,
    "title": "Unit 1",
    "description": "Intro to ML",
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_SECTION: Dict[str, Any] = {
    "id": 10,
    "unit_id": 1,
    "title": "Section A",
    "estimated_minutes": 30,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_LESSON: Dict[str, Any] = {
    "id": 100,
    "section_id": 10,
    "title": "Lesson 1",
    "description": "What is ML?",
    "duration_minutes": 15,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_PRACTICE: Dict[str, Any] = {
    "id": 200,
    "section_id": 10,
    "title": "Practice 1",
    "required_correct": 8,
    "total_questions": 10,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_QUIZ: Dict[str, Any] = {
    "id": 300,
    "section_id": 10,
    "title": "Quiz 1",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}


def _patch_batch(
    unit: Dict[str, Any] | None = MOCK_UNIT,
    sections: List[Dict] | None = None,
    lessons: List[Dict] | None = None,
    practices: List[Dict] | None = None,
    quizzes: List[Dict] | None = None,
    lesson_progress: Dict[int, Dict] | None = None,
    practice_progress: Dict[int, Dict] | None = None,
    quiz_progress: Dict[int, Dict] | None = None,
):
    """Return a combined context manager that patches all batch functions."""
    from contextlib import ExitStack

    _study_page_cache.clear()

    sections = sections if sections is not None else [MOCK_SECTION]
    lessons = lessons if lessons is not None else [MOCK_LESSON]
    practices = practices if practices is not None else [MOCK_PRACTICE]
    quizzes = quizzes if quizzes is not None else [MOCK_QUIZ]
    lesson_progress = lesson_progress if lesson_progress is not None else {}
    practice_progress = practice_progress if practice_progress is not None else {}
    quiz_progress = quiz_progress if quiz_progress is not None else {}

    stack = ExitStack()
    stack.enter_context(
        patch(
            "services.learning.get_unit",
            new_callable=AsyncMock,
            return_value=unit,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.list_sections",
            new_callable=AsyncMock,
            return_value=sections,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.list_lessons_for_sections",
            new_callable=AsyncMock,
            return_value=lessons,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.list_practices_for_sections",
            new_callable=AsyncMock,
            return_value=practices,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.list_quizzes_for_sections",
            new_callable=AsyncMock,
            return_value=quizzes,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.get_lesson_progress_for_user",
            new_callable=AsyncMock,
            return_value=lesson_progress,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.get_practice_progress_for_user",
            new_callable=AsyncMock,
            return_value=practice_progress,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.get_quiz_progress_for_user",
            new_callable=AsyncMock,
            return_value=quiz_progress,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.has_notes_for_unit",
            new_callable=AsyncMock,
            return_value=False,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.has_flashcards_for_unit",
            new_callable=AsyncMock,
            return_value=False,
        )
    )
    stack.enter_context(
        patch(
            "services.learning.has_notes_for_lessons",
            new_callable=AsyncMock,
            return_value={},
        )
    )
    stack.enter_context(
        patch(
            "services.learning.has_flashcards_for_lessons",
            new_callable=AsyncMock,
            return_value={},
        )
    )
    return stack


class TestGetUnitDetails:
    def setup_method(self) -> None:
        _dispose_engine()

    def test_returns_none_when_unit_not_found(self):
        async def _run():
            with _patch_batch(unit=None):
                return await get_unit_details(unit_id=999, user_id=1)

        result = run_sync(_run())
        assert result is None

    def test_assembles_unit_with_sections(self):
        async def _run():
            with _patch_batch():
                return await get_unit_details(unit_id=1, user_id=1)

        result = run_sync(_run())
        assert result is not None
        assert result.id == 1
        assert result.title == "Unit 1"
        assert len(result.sections) == 1
        assert result.sections[0].title == "Section A"

    def test_includes_user_progress_for_lessons(self):
        async def _run():
            with _patch_batch(
                lesson_progress={
                    100: {
                        "user_id": 1,
                        "lesson_id": 100,
                        "status": "COMPLETED",
                        "completed_at": "2026-01-15T10:00:00",
                    }
                }
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = run_sync(_run())
        lesson = result.sections[0].lessons[0]
        assert lesson.status == "mastered"
        assert lesson.completed_at == "2026-01-15T10:00:00"

    def test_includes_user_progress_for_practices(self):
        async def _run():
            with _patch_batch(
                practice_progress={
                    200: {
                        "user_id": 1,
                        "practice_id": 200,
                        "attempts": 3,
                        "best_score": 9.0,
                        "status": "MASTERED",
                    }
                }
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = run_sync(_run())
        practice = result.sections[0].practices[0]
        assert practice.attempts == 3
        assert practice.best_score == 9.0
        assert practice.status == "mastered"

    def test_includes_user_progress_for_quizzes(self):
        async def _run():
            with _patch_batch(
                quiz_progress={
                    300: {
                        "user_id": 1,
                        "quiz_id": 300,
                        "score": 85.0,
                        "completed_at": "2026-01-15T10:00:00",
                    }
                }
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = run_sync(_run())
        goal = result.sections[0].goals[0]
        assert goal.score == 85.0
        assert goal.completed_at == "2026-01-15T10:00:00"

    def test_empty_sections_when_no_children(self):
        async def _run():
            with _patch_batch(lessons=[], practices=[], quizzes=[]):
                return await get_unit_details(unit_id=1, user_id=1)

        result = run_sync(_run())
        assert result is not None
        assert len(result.sections) == 1
        assert result.sections[0].lessons == []
        assert result.sections[0].practices == []
        assert result.sections[0].goals == []

    def test_multiple_sections_grouped_correctly(self):
        sec2: Dict[str, Any] = {
            "id": 20,
            "unit_id": 1,
            "title": "Section B",
            "estimated_minutes": 20,
            "display_order": 1,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        lesson_sec2: Dict[str, Any] = {
            "id": 101,
            "section_id": 20,
            "title": "Lesson 2",
            "description": "Deep Learning",
            "duration_minutes": 20,
            "display_order": 0,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }

        async def _run():
            with _patch_batch(
                sections=[MOCK_SECTION, sec2],
                lessons=[MOCK_LESSON, lesson_sec2],
                practices=[MOCK_PRACTICE],
                quizzes=[MOCK_QUIZ],
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = run_sync(_run())
        assert len(result.sections) == 2
        assert result.sections[0].title == "Section A"
        assert len(result.sections[0].lessons) == 1
        assert result.sections[0].lessons[0].id == 100
        assert result.sections[1].title == "Section B"
        assert len(result.sections[1].lessons) == 1
        assert result.sections[1].lessons[0].id == 101

    def test_progress_squares_populated(self):
        async def _run():
            with _patch_batch():
                return await get_unit_details(unit_id=1, user_id=1)

        result = run_sync(_run())
        assert len(result.progress.squares) > 0

    def test_progress_stats_computed(self):
        async def _run():
            with _patch_batch(
                lesson_progress={
                    100: {
                        "user_id": 1,
                        "lesson_id": 100,
                        "status": "COMPLETED",
                        "completed_at": "2026-01-15T10:00:00",
                    }
                }
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = run_sync(_run())
        assert result.progress is not None
        assert result.progress.completed >= 1


class TestStudyPageCache:
    def setup_method(self) -> None:
        _dispose_engine()

    def test_cache_hit_returns_same_object(self):
        async def _run():
            with _patch_batch():
                first = await get_unit_details(unit_id=1, user_id=1)
                second = await get_unit_details(unit_id=1, user_id=1)
                return first, second

        first, second = run_sync(_run())
        assert first is second

    def test_cache_miss_on_different_user(self):
        async def _run():
            with _patch_batch():
                a = await get_unit_details(unit_id=1, user_id=1)
                b = await get_unit_details(unit_id=1, user_id=2)
                return a, b

        a, b = run_sync(_run())
        assert a is not b

    def test_invalidate_specific_unit(self):
        async def _run():
            with _patch_batch():
                first = await get_unit_details(unit_id=1, user_id=1)
                invalidate_study_page_cache(unit_id=1)
                second = await get_unit_details(unit_id=1, user_id=1)
                return first, second

        first, second = run_sync(_run())
        assert first is not second

    def test_invalidate_all(self):
        async def _run():
            with _patch_batch():
                first = await get_unit_details(unit_id=1, user_id=1)
                invalidate_study_page_cache()
                second = await get_unit_details(unit_id=1, user_id=1)
                return first, second

        first, second = run_sync(_run())
        assert first is not second
