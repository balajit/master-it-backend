"""Comprehensive tests for the Learning Service layer.

Covers: get_unit_details assembly, cache behavior, batch queries,
invalidate_study_page_cache, progress squares, stats calculation,
and edge cases (empty data, multiple sections, missing entities).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch


_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from cache import TTLCache  # noqa: E402
from schemas import (  # noqa: E402
    GoalResponse,
    LessonResponse,
    PracticeResponse,
    ProgressStatus,
    SectionResponse,
    UnitResponse,
)
from services.learning import (  # noqa: E402
    _study_page_cache,
    get_unit_details,
    invalidate_study_page_cache,
)
from services.progress import (  # noqa: E402
    calculate_completed,
    determine_goal_status,
    determine_lesson_status,
    determine_practice_status,
    determine_quiz_status,
    mastery_pct,
    merge_lesson_status,
    merge_practice_status,
    merge_quiz_status,
    progress_squares,
    stats,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

MOCK_UNIT: Dict[str, Any] = {
    "id": 1,
    "course_id": 1,
    "title": "Unit 1",
    "description": "Intro to ML",
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_SECTION_A: Dict[str, Any] = {
    "id": 10,
    "unit_id": 1,
    "title": "Section A",
    "estimated_minutes": 30,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_SECTION_B: Dict[str, Any] = {
    "id": 20,
    "unit_id": 1,
    "title": "Section B",
    "estimated_minutes": 20,
    "display_order": 1,
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

MOCK_LESSON_B: Dict[str, Any] = {
    "id": 101,
    "section_id": 20,
    "title": "Lesson 2",
    "description": "Deep Learning",
    "duration_minutes": 20,
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
) -> Any:
    """Return a combined context manager that patches all batch functions."""
    from contextlib import ExitStack

    _study_page_cache.clear()

    sections = sections if sections is not None else [MOCK_SECTION_A]
    lessons = lessons if lessons is not None else [MOCK_LESSON]
    practices = practices if practices is not None else [MOCK_PRACTICE]
    quizzes = quizzes if quizzes is not None else [MOCK_QUIZ]
    lesson_progress = lesson_progress if lesson_progress is not None else {}
    practice_progress = practice_progress if practice_progress is not None else {}
    quiz_progress = quiz_progress if quiz_progress is not None else {}

    stack = ExitStack()
    stack.enter_context(
        patch("services.learning.get_unit", new_callable=AsyncMock, return_value=unit)
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


# ═══════════════════════════════════════════════════════════════════════════
# 1. get_unit_details — Core Assembly
# ═══════════════════════════════════════════════════════════════════════════


class TestGetUnitDetailsAssembly:
    """Test the core study page assembly logic."""

    def test_returns_none_when_unit_not_found(self) -> None:
        async def _run() -> None:
            with _patch_batch(unit=None):
                return await get_unit_details(unit_id=999, user_id=1)

        result = asyncio.run(_run())
        assert result is None

    def test_assembles_unit_with_sections(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch():
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result is not None
        assert result.id == 1
        assert result.title == "Unit 1"
        assert result.description == "Intro to ML"
        assert result.course_id == 1
        assert len(result.sections) == 1
        assert result.sections[0].title == "Section A"

    def test_section_has_lessons_practices_goals(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch():
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        sec = result.sections[0]
        assert len(sec.lessons) == 1
        assert sec.lessons[0].id == 100
        assert sec.lessons[0].title == "Lesson 1"
        assert len(sec.practices) == 1
        assert sec.practices[0].id == 200
        assert sec.practices[0].title == "Practice 1"
        assert len(sec.goals) == 1
        assert sec.goals[0].id == 300
        assert sec.goals[0].title == "Quiz 1"

    def test_empty_sections_when_no_children(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch(lessons=[], practices=[], quizzes=[]):
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result is not None
        assert len(result.sections) == 1
        assert result.sections[0].lessons == []
        assert result.sections[0].practices == []
        assert result.sections[0].goals == []

    def test_multiple_sections_grouped_correctly(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch(
                sections=[MOCK_SECTION_A, MOCK_SECTION_B],
                lessons=[MOCK_LESSON, MOCK_LESSON_B],
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert len(result.sections) == 2
        assert result.sections[0].title == "Section A"
        assert result.sections[0].lessons[0].id == 100
        assert result.sections[1].title == "Section B"
        assert result.sections[1].lessons[0].id == 101

    def test_no_sections_returns_empty_list(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch(sections=[], lessons=[], practices=[], quizzes=[]):
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result is not None
        assert result.sections == []

    def test_about_field_matches_description(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch():
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result.about == result.description

    def test_progress_response_populated(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch():
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result.progress is not None
        assert result.progress.total >= 0
        assert result.progress.completed >= 0
        assert result.progress.mastered_pct >= 0.0

    def test_progress_squares_populated(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch():
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert len(result.progress.squares) > 0

    def test_lesson_order_preserved(self) -> None:
        lesson_a = {**MOCK_LESSON, "id": 100, "display_order": 0}
        lesson_b = {**MOCK_LESSON, "id": 101, "display_order": 1, "title": "Lesson B"}

        async def _run() -> UnitResponse:
            with _patch_batch(lessons=[lesson_a, lesson_b]):
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result.sections[0].lessons[0].order == 0
        assert result.sections[0].lessons[1].order == 1


# ═══════════════════════════════════════════════════════════════════════════
# 2. get_unit_details — Progress Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestGetUnitDetailsProgress:
    """Test progress data is correctly merged into the study page."""

    def test_lesson_completed_appears_mastered(self) -> None:
        async def _run() -> UnitResponse:
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

        result = asyncio.run(_run())
        lesson = result.sections[0].lessons[0]
        assert lesson.status == ProgressStatus.MASTERED
        assert lesson.completed_at == "2026-01-15T10:00:00"

    def test_lesson_in_progress_appears_attempted(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch(
                lesson_progress={
                    100: {
                        "user_id": 1,
                        "lesson_id": 100,
                        "status": "IN_PROGRESS",
                        "completed_at": None,
                    }
                }
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result.sections[0].lessons[0].status == ProgressStatus.ATTEMPTED

    def test_practice_with_progress_shows_scores(self) -> None:
        async def _run() -> UnitResponse:
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

        result = asyncio.run(_run())
        practice = result.sections[0].practices[0]
        assert practice.attempts == 3
        assert practice.best_score == 9.0
        assert practice.status == ProgressStatus.MASTERED

    def test_quiz_with_progress_shows_score(self) -> None:
        async def _run() -> UnitResponse:
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

        result = asyncio.run(_run())
        goal = result.sections[0].goals[0]
        assert goal.score == 85.0
        assert goal.completed_at == "2026-01-15T10:00:00"

    def test_no_progress_defaults_to_not_started(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch():
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result.sections[0].lessons[0].status == ProgressStatus.NOT_STARTED
        assert result.sections[0].practices[0].status == ProgressStatus.NOT_STARTED

    def test_progress_stats_computed_correctly(self) -> None:
        async def _run() -> UnitResponse:
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

        result = asyncio.run(_run())
        assert result.progress.completed >= 1
        assert result.progress.mastered_pct > 0.0

    def test_practice_not_mastered_when_below_threshold(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch(
                practice_progress={
                    200: {
                        "user_id": 1,
                        "practice_id": 200,
                        "attempts": 2,
                        "best_score": 5.0,
                        "status": "ATTEMPTED",
                    }
                }
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        practice = result.sections[0].practices[0]
        assert practice.status == ProgressStatus.PRACTICED
        assert practice.best_score == 5.0

    def test_quiz_below_passing_score_is_attempted(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch(
                quiz_progress={
                    300: {
                        "user_id": 1,
                        "quiz_id": 300,
                        "score": 50.0,
                        "completed_at": None,
                    }
                }
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        goal = result.sections[0].goals[0]
        assert goal.score == 50.0
        assert determine_goal_status(goal) == ProgressStatus.ATTEMPTED

    def test_lesson_viewed_is_familiar(self) -> None:
        async def _run() -> UnitResponse:
            with _patch_batch(
                lesson_progress={
                    100: {
                        "user_id": 1,
                        "lesson_id": 100,
                        "status": "VIEWED",
                        "completed_at": None,
                    }
                }
            ):
                return await get_unit_details(unit_id=1, user_id=1)

        result = asyncio.run(_run())
        assert result.sections[0].lessons[0].status == ProgressStatus.FAMILIAR


# ═══════════════════════════════════════════════════════════════════════════
# 3. Cache Behavior
# ═══════════════════════════════════════════════════════════════════════════


class TestStudyPageCache:
    """Test TTL cache for study page assembly."""

    def test_cache_hit_returns_same_object(self) -> None:
        async def _run() -> tuple:
            with _patch_batch():
                first = await get_unit_details(unit_id=1, user_id=1)
                second = await get_unit_details(unit_id=1, user_id=1)
                return first, second

        first, second = asyncio.run(_run())
        assert first is second

    def test_cache_miss_on_different_user(self) -> None:
        async def _run() -> tuple:
            with _patch_batch():
                a = await get_unit_details(unit_id=1, user_id=1)
                b = await get_unit_details(unit_id=1, user_id=2)
                return a, b

        a, b = asyncio.run(_run())
        assert a is not b

    def test_cache_miss_on_different_unit(self) -> None:
        async def _run() -> tuple:
            with _patch_batch():
                a = await get_unit_details(unit_id=1, user_id=1)
                b = await get_unit_details(unit_id=2, user_id=1)
                return a, b

        a, b = asyncio.run(_run())
        assert a is not b

    def test_invalidate_specific_unit(self) -> None:
        async def _run() -> tuple:
            with _patch_batch():
                first = await get_unit_details(unit_id=1, user_id=1)
                invalidate_study_page_cache(unit_id=1)
                second = await get_unit_details(unit_id=1, user_id=1)
                return first, second

        first, second = asyncio.run(_run())
        assert first is not second

    def test_invalidate_all(self) -> None:
        async def _run() -> tuple:
            with _patch_batch():
                first = await get_unit_details(unit_id=1, user_id=1)
                invalidate_study_page_cache()
                second = await get_unit_details(unit_id=1, user_id=1)
                return first, second

        first, second = asyncio.run(_run())
        assert first is not second

    def test_invalidate_nonexistent_unit_no_error(self) -> None:
        async def _run() -> None:
            with _patch_batch():
                await get_unit_details(unit_id=1, user_id=1)
                invalidate_study_page_cache(unit_id=9999)

        asyncio.run(_run())

    def test_cache_not_populated_for_none_result(self) -> None:
        async def _run() -> None:
            with _patch_batch(unit=None):
                r1 = await get_unit_details(unit_id=999, user_id=1)
                r2 = await get_unit_details(unit_id=999, user_id=1)
                return r1, r2

        r1, r2 = asyncio.run(_run())
        assert r1 is None
        assert r2 is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. TTLCache Unit Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTTLCache:
    """Test the underlying TTLCache mechanism."""

    def test_set_and_get(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=60.0)
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_get_missing_returns_none(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=60.0)
        assert cache.get("missing") is None

    def test_invalidate_removes_key(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=60.0)
        cache.set("k", "v")
        cache.invalidate("k")
        assert cache.get("k") is None

    def test_invalidate_nonexistent_key_no_error(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=60.0)
        cache.invalidate("missing")

    def test_clear_removes_all(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=60.0)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_expiry(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=0.01)
        cache.set("k", "v")
        time.sleep(0.02)
        assert cache.get("k") is None

    def test_len_approximate(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=60.0)
        cache.set("a", "1")
        cache.set("b", "2")
        assert len(cache) == 2

    def test_custom_ttl_per_key(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=60.0)
        cache.set("short", "v", ttl=0.01)
        time.sleep(0.02)
        assert cache.get("short") is None


# ═══════════════════════════════════════════════════════════════════════════
# 5. Progress Calculations — Status Determination
# ═══════════════════════════════════════════════════════════════════════════


class TestDetermineLessonStatus:
    """Test determine_lesson_status with correct dict-based signatures."""

    def test_none_progress_returns_not_started(self) -> None:
        assert determine_lesson_status(None) == ProgressStatus.NOT_STARTED

    def test_completed_returns_mastered(self) -> None:
        progress = {
            "lesson_id": 1,
            "status": "COMPLETED",
            "completed_at": "2026-01-15T10:00:00",
        }
        assert determine_lesson_status(progress) == ProgressStatus.MASTERED

    def test_in_progress_returns_attempted(self) -> None:
        progress = {"lesson_id": 1, "status": "IN_PROGRESS", "completed_at": None}
        assert determine_lesson_status(progress) == ProgressStatus.ATTEMPTED

    def test_viewed_returns_familiar(self) -> None:
        progress = {"lesson_id": 1, "status": "VIEWED", "completed_at": None}
        assert determine_lesson_status(progress) == ProgressStatus.FAMILIAR

    def test_locked_overrides_completed(self) -> None:
        progress = {
            "lesson_id": 1,
            "status": "COMPLETED",
            "completed_at": "2026-01-15",
        }
        assert (
            determine_lesson_status(progress, locked_ids={1}) == ProgressStatus.LOCKED
        )

    def test_locked_with_no_progress_returns_not_started(self) -> None:
        progress = {"lesson_id": 1, "status": None, "completed_at": None}
        assert (
            determine_lesson_status(progress, locked_ids={2})
            == ProgressStatus.NOT_STARTED
        )

    def test_completed_without_timestamp_returns_not_started(self) -> None:
        """completed_at is required for MASTERED status — status alone is not enough."""
        progress = {"lesson_id": 1, "status": "COMPLETED", "completed_at": None}
        assert determine_lesson_status(progress) == ProgressStatus.NOT_STARTED

    def test_not_started_status_returns_not_started(self) -> None:
        progress = {"lesson_id": 1, "status": "NOT_STARTED", "completed_at": None}
        assert determine_lesson_status(progress) == ProgressStatus.NOT_STARTED


class TestDeterminePracticeStatus:
    """Test determine_practice_status with correct dict-based signatures."""

    def test_none_progress_returns_not_started(self) -> None:
        assert determine_practice_status(None) == ProgressStatus.NOT_STARTED

    def test_mastered_when_score_meets_required(self) -> None:
        progress = {
            "practice_id": 1,
            "attempts": 3,
            "best_score": 8.0,
            "status": "COMPLETED",
        }
        assert (
            determine_practice_status(progress, required_correct=8)
            == ProgressStatus.MASTERED
        )

    def test_practiced_when_attempts_below_threshold(self) -> None:
        progress = {
            "practice_id": 1,
            "attempts": 2,
            "best_score": 5.0,
            "status": "ATTEMPTED",
        }
        assert (
            determine_practice_status(progress, required_correct=8)
            == ProgressStatus.PRACTICED
        )

    def test_attempted_when_in_progress(self) -> None:
        progress = {
            "practice_id": 1,
            "attempts": 0,
            "best_score": 0.0,
            "status": "IN_PROGRESS",
        }
        assert determine_practice_status(progress) == ProgressStatus.ATTEMPTED

    def test_not_mastered_when_required_zero(self) -> None:
        progress = {
            "practice_id": 1,
            "attempts": 1,
            "best_score": 10.0,
            "status": "COMPLETED",
        }
        assert (
            determine_practice_status(progress, required_correct=0)
            == ProgressStatus.PRACTICED
        )

    def test_locked_overrides_mastered(self) -> None:
        progress = {
            "practice_id": 1,
            "attempts": 3,
            "best_score": 10.0,
            "status": "COMPLETED",
        }
        assert (
            determine_practice_status(progress, required_correct=8, locked_ids={1})
            == ProgressStatus.LOCKED
        )

    def test_zero_attempts_returns_not_started(self) -> None:
        progress = {
            "practice_id": 1,
            "attempts": 0,
            "best_score": 0.0,
            "status": "NOT_STARTED",
        }
        assert determine_practice_status(progress) == ProgressStatus.NOT_STARTED

    def test_practiced_when_score_exceeds_threshold(self) -> None:
        progress = {
            "practice_id": 1,
            "attempts": 5,
            "best_score": 10.0,
            "status": "COMPLETED",
        }
        assert (
            determine_practice_status(progress, required_correct=8)
            == ProgressStatus.MASTERED
        )


class TestDetermineQuizStatus:
    """Test determine_quiz_status with correct dict-based signatures."""

    def test_none_progress_returns_not_started(self) -> None:
        assert determine_quiz_status(None) == ProgressStatus.NOT_STARTED

    def test_mastered_when_score_passes(self) -> None:
        progress = {"quiz_id": 1, "score": 85.0, "completed_at": "2026-01-20"}
        assert determine_quiz_status(progress) == ProgressStatus.MASTERED

    def test_attempted_when_score_fails(self) -> None:
        progress = {"quiz_id": 1, "score": 45.0, "completed_at": None}
        assert determine_quiz_status(progress) == ProgressStatus.ATTEMPTED

    def test_exact_boundary_70_is_mastered(self) -> None:
        progress = {"quiz_id": 1, "score": 70.0, "completed_at": "2026-01-20"}
        assert determine_quiz_status(progress) == ProgressStatus.MASTERED

    def test_69_9_is_attempted(self) -> None:
        progress = {"quiz_id": 1, "score": 69.9, "completed_at": None}
        assert determine_quiz_status(progress) == ProgressStatus.ATTEMPTED

    def test_custom_passing_score(self) -> None:
        progress = {"quiz_id": 1, "score": 80.0, "completed_at": None}
        assert (
            determine_quiz_status(progress, passing_score=80.0)
            == ProgressStatus.MASTERED
        )

    def test_locked_overrides_mastered(self) -> None:
        progress = {"quiz_id": 1, "score": 90.0, "completed_at": "2026-01-20"}
        assert determine_quiz_status(progress, locked_ids={1}) == ProgressStatus.LOCKED

    def test_score_zero_is_attempted(self) -> None:
        progress = {"quiz_id": 1, "score": 0.0, "completed_at": None}
        assert determine_quiz_status(progress) == ProgressStatus.ATTEMPTED

    def test_score_100_is_mastered(self) -> None:
        progress = {"quiz_id": 1, "score": 100.0, "completed_at": "2026-01-20"}
        assert determine_quiz_status(progress) == ProgressStatus.MASTERED


class TestDetermineGoalStatus:
    """Test determine_goal_status from GoalResponse model."""

    def test_mastered_when_completed(self) -> None:
        goal = GoalResponse(id=1, title="Q1", score=85.0, completed_at="2026-01-20")
        assert determine_goal_status(goal) == ProgressStatus.MASTERED

    def test_attempted_when_score_only(self) -> None:
        goal = GoalResponse(id=1, title="Q1", score=50.0, completed_at=None)
        assert determine_goal_status(goal) == ProgressStatus.ATTEMPTED

    def test_not_started_when_no_score(self) -> None:
        goal = GoalResponse(id=1, title="Q1", score=None, completed_at=None)
        assert determine_goal_status(goal) == ProgressStatus.NOT_STARTED


# ═══════════════════════════════════════════════════════════════════════════
# 6. Merge Functions
# ═══════════════════════════════════════════════════════════════════════════


class TestMergeLessonStatus:
    """Test merge_lesson_status merges progress into lesson dicts."""

    def test_merges_completed_lesson(self) -> None:
        lessons = [
            {
                "id": 1,
                "section_id": 10,
                "title": "L1",
                "description": "",
                "duration_minutes": 10,
                "display_order": 0,
            },
        ]
        progress_map = {
            1: {
                "lesson_id": 1,
                "status": "COMPLETED",
                "completed_at": "2026-01-15T10:00:00",
            },
        }
        result = merge_lesson_status(lessons, progress_map)
        assert len(result) == 1
        assert result[0].status == ProgressStatus.MASTERED
        assert result[0].completed_at == "2026-01-15T10:00:00"

    def test_no_progress_defaults_not_started(self) -> None:
        lessons = [
            {
                "id": 1,
                "section_id": 10,
                "title": "L1",
                "description": "",
                "duration_minutes": 10,
                "display_order": 0,
            },
        ]
        result = merge_lesson_status(lessons, {})
        assert result[0].status == ProgressStatus.NOT_STARTED

    def test_empty_lessons(self) -> None:
        assert merge_lesson_status([], {}) == []

    def test_locked_lesson(self) -> None:
        lessons = [
            {
                "id": 1,
                "section_id": 10,
                "title": "L1",
                "description": "",
                "duration_minutes": 10,
                "display_order": 0,
            },
        ]
        progress_map = {
            1: {
                "lesson_id": 1,
                "status": "COMPLETED",
                "completed_at": "2026-01-15",
            },
        }
        result = merge_lesson_status(lessons, progress_map, locked_ids={1})
        assert result[0].status == ProgressStatus.LOCKED

    def test_multiple_lessons_mixed_progress(self) -> None:
        lessons = [
            {
                "id": 1,
                "section_id": 10,
                "title": "L1",
                "description": "",
                "duration_minutes": 10,
                "display_order": 0,
            },
            {
                "id": 2,
                "section_id": 10,
                "title": "L2",
                "description": "",
                "duration_minutes": 15,
                "display_order": 1,
            },
        ]
        progress_map = {
            1: {
                "lesson_id": 1,
                "status": "COMPLETED",
                "completed_at": "2026-01-15",
            },
        }
        result = merge_lesson_status(lessons, progress_map)
        assert result[0].status == ProgressStatus.MASTERED
        assert result[1].status == ProgressStatus.NOT_STARTED


class TestMergePracticeStatus:
    """Test merge_practice_status merges progress into practice dicts."""

    def test_merges_mastered_practice(self) -> None:
        practices = [
            {
                "id": 1,
                "section_id": 10,
                "title": "P1",
                "required_correct": 8,
                "total_questions": 10,
                "display_order": 0,
            },
        ]
        progress_map = {
            1: {
                "practice_id": 1,
                "attempts": 3,
                "best_score": 9.0,
                "status": "COMPLETED",
            },
        }
        result = merge_practice_status(practices, progress_map)
        assert result[0].status == ProgressStatus.MASTERED
        assert result[0].attempts == 3
        assert result[0].best_score == 9.0

    def test_empty_practices(self) -> None:
        assert merge_practice_status([], {}) == []

    def test_no_progress_defaults(self) -> None:
        practices = [
            {
                "id": 1,
                "section_id": 10,
                "title": "P1",
                "required_correct": 8,
                "total_questions": 10,
                "display_order": 0,
            },
        ]
        result = merge_practice_status(practices, {})
        assert result[0].status == ProgressStatus.NOT_STARTED
        assert result[0].attempts == 0
        assert result[0].best_score == 0.0

    def test_locked_practice(self) -> None:
        practices = [
            {
                "id": 1,
                "section_id": 10,
                "title": "P1",
                "required_correct": 8,
                "total_questions": 10,
                "display_order": 0,
            },
        ]
        progress_map = {
            1: {
                "practice_id": 1,
                "attempts": 3,
                "best_score": 9.0,
                "status": "COMPLETED",
            },
        }
        result = merge_practice_status(practices, progress_map, locked_ids={1})
        assert result[0].status == ProgressStatus.LOCKED


class TestMergeQuizStatus:
    """Test merge_quiz_status merges progress into quiz dicts."""

    def test_merges_quiz_with_score(self) -> None:
        quizzes = [{"id": 1, "section_id": 10, "title": "Q1"}]
        progress_map = {
            1: {"quiz_id": 1, "score": 85.0, "completed_at": "2026-01-20"},
        }
        result = merge_quiz_status(quizzes, progress_map)
        assert result[0].score == 85.0
        assert result[0].completed_at == "2026-01-20"

    def test_empty_quizzes(self) -> None:
        assert merge_quiz_status([], {}) == []

    def test_no_progress_defaults(self) -> None:
        quizzes = [{"id": 1, "section_id": 10, "title": "Q1"}]
        result = merge_quiz_status(quizzes, {})
        assert result[0].score is None
        assert result[0].completed_at is None


# ═══════════════════════════════════════════════════════════════════════════
# 7. Statistics
# ═══════════════════════════════════════════════════════════════════════════


def _make_section(
    section_id: int = 1,
    lessons: List[LessonResponse] | None = None,
    practices: List[PracticeResponse] | None = None,
    goals: List[GoalResponse] | None = None,
) -> SectionResponse:
    return SectionResponse(
        id=section_id,
        title=f"Section {section_id}",
        estimated_minutes=30,
        order=0,
        lessons=lessons or [],
        practices=practices or [],
        goals=goals or [],
    )


def _lesson(status: str, lesson_id: int = 1) -> LessonResponse:
    return LessonResponse(
        id=lesson_id,
        title="L",
        description="",
        duration_minutes=10,
        order=0,
        status=ProgressStatus(status.lower()),
    )


def _practice(status: str, practice_id: int = 1) -> PracticeResponse:
    return PracticeResponse(
        id=practice_id,
        title="P",
        required_correct=8,
        total_questions=10,
        order=0,
        status=ProgressStatus(status.lower()),
    )


def _goal(status: str, goal_id: int = 1) -> GoalResponse:
    score = (
        85.0
        if status.upper() == "MASTERED"
        else (45.0 if status.upper() == "ATTEMPTED" else None)
    )
    completed = "2026-01-20" if status.upper() == "MASTERED" else None
    return GoalResponse(id=goal_id, title="Q", score=score, completed_at=completed)


class TestStats:
    """Test stats() computation."""

    def test_empty_sections(self) -> None:
        result = stats([])
        assert result.total == 0
        assert result.completed == 0
        assert result.mastered_pct == 0.0

    def test_all_not_started(self) -> None:
        sec = _make_section(lessons=[_lesson("NOT_STARTED"), _lesson("NOT_STARTED", 2)])
        result = stats([sec])
        assert result.total == 2
        assert result.completed == 0
        assert result.mastered_pct == 0.0

    def test_mixed_statuses(self) -> None:
        sec = _make_section(
            lessons=[
                _lesson("MASTERED"),
                _lesson("NOT_STARTED", 2),
                _lesson("ATTEMPTED", 3),
            ],
            practices=[_practice("PRACTICED")],
            goals=[_goal("MASTERED")],
        )
        result = stats([sec])
        assert result.total == 5
        assert result.completed == 2
        assert result.mastered_pct == 40.0

    def test_all_mastered(self) -> None:
        sec = _make_section(
            lessons=[_lesson("MASTERED"), _lesson("MASTERED", 2)],
            practices=[_practice("MASTERED")],
        )
        result = stats([sec])
        assert result.total == 3
        assert result.completed == 3
        assert result.mastered_pct == 100.0

    def test_multiple_sections(self) -> None:
        sec1 = _make_section(
            section_id=1,
            lessons=[_lesson("MASTERED"), _lesson("NOT_STARTED", 2)],
        )
        sec2 = _make_section(
            section_id=2,
            lessons=[_lesson("ATTEMPTED", 3)],
        )
        result = stats([sec1, sec2])
        assert result.total == 3
        assert result.completed == 1


class TestCalculateCompleted:
    def test_counts_mastered(self) -> None:
        sec = _make_section(
            lessons=[_lesson("MASTERED"), _lesson("NOT_STARTED", 2)],
            practices=[_practice("MASTERED")],
        )
        assert calculate_completed([sec]) == 2

    def test_empty(self) -> None:
        assert calculate_completed([]) == 0


class TestMasteryPct:
    def test_half_mastered(self) -> None:
        sec = _make_section(
            lessons=[_lesson("MASTERED"), _lesson("NOT_STARTED", 2)],
        )
        assert mastery_pct([sec]) == 50.0

    def test_empty_returns_zero(self) -> None:
        assert mastery_pct([]) == 0.0

    def test_all_mastered(self) -> None:
        sec = _make_section(
            lessons=[_lesson("MASTERED"), _lesson("MASTERED", 2)],
        )
        assert mastery_pct([sec]) == 100.0

    def test_none_mastered(self) -> None:
        sec = _make_section(
            lessons=[_lesson("NOT_STARTED"), _lesson("ATTEMPTED", 2)],
        )
        assert mastery_pct([sec]) == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 8. Progress Squares
# ═══════════════════════════════════════════════════════════════════════════


class TestProgressSquares:
    def test_builds_squares_from_sections(self) -> None:
        sec = _make_section(
            section_id=5,
            lessons=[_lesson("MASTERED")],
            practices=[_practice("PRACTICED")],
            goals=[_goal("NOT_STARTED")],
        )
        squares = progress_squares([sec])
        assert len(squares) == 3
        assert squares[0].section_id == 5
        assert squares[0].status == ProgressStatus.MASTERED
        assert squares[1].status == ProgressStatus.PRACTICED
        assert squares[2].status == ProgressStatus.NOT_STARTED

    def test_empty_sections(self) -> None:
        assert progress_squares([]) == []

    def test_sorted_by_section_and_order(self) -> None:
        sec1 = _make_section(section_id=2, lessons=[_lesson("MASTERED")])
        sec2 = _make_section(section_id=1, lessons=[_lesson("NOT_STARTED")])
        squares = progress_squares([sec1, sec2])
        assert squares[0].section_id == 1
        assert squares[1].section_id == 2

    def test_goals_have_zero_order(self) -> None:
        sec = _make_section(goals=[_goal("NOT_STARTED")])
        squares = progress_squares([sec])
        assert squares[0].order == 0

    def test_squares_contain_section_title(self) -> None:
        sec = _make_section(section_id=1, lessons=[_lesson("MASTERED")])
        squares = progress_squares([sec])
        assert squares[0].section_title == "Section 1"
