"""Unit tests for has_notes / has_flashcards flag injection in the learning service.

Tests that _build_study_page correctly calls the EXISTS helpers and attaches
the resulting flags to UnitResponse and each LessonResponse.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch as _patch

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# ── Fixtures ─────────────────────────────────────────────────────────────────

UNIT_ROW = {
    "id": 1,
    "course_id": 2,
    "title": "Unit 1",
    "description": "Desc",
    "about": "About",
    "display_order": 0,
    "created_at": "2026-01-01",
    "updated_at": "2026-01-01",
}

SECTION_ROW = {
    "id": 10,
    "unit_id": 1,
    "title": "Sec 1",
    "estimated_minutes": 30,
    "display_order": 0,
}

LESSON_ROW = {
    "id": 100,
    "section_id": 10,
    "title": "Lesson A",
    "description": "",
    "duration_minutes": 10,
    "display_order": 0,
}


def _run(coro):
    return asyncio.run(coro)


def _patch_learning_repos(
    *,
    unit=UNIT_ROW,
    sections=None,
    lessons=None,
    practices=None,
    quizzes=None,
    lesson_progress=None,
    practice_progress=None,
    quiz_progress=None,
):
    sections = sections or [SECTION_ROW]
    lessons = lessons or [LESSON_ROW]
    practices = practices or []
    quizzes = quizzes or []
    lesson_progress = lesson_progress or {}
    practice_progress = practice_progress or {}
    quiz_progress = quiz_progress or {}

    # Patch at the import site — services.learning imports these names directly
    return {
        "services.learning.get_unit": AsyncMock(return_value=unit),
        "services.learning.list_sections": AsyncMock(return_value=sections),
        "services.learning.list_lessons_for_sections": AsyncMock(return_value=lessons),
        "services.learning.list_practices_for_sections": AsyncMock(
            return_value=practices
        ),
        "services.learning.list_quizzes_for_sections": AsyncMock(return_value=quizzes),
        "services.learning.get_lesson_progress_for_user": AsyncMock(
            return_value=lesson_progress
        ),
        "services.learning.get_practice_progress_for_user": AsyncMock(
            return_value=practice_progress
        ),
        "services.learning.get_quiz_progress_for_user": AsyncMock(
            return_value=quiz_progress
        ),
        # EXISTS helpers imported into services.learning namespace
        "services.learning.has_notes_for_unit": AsyncMock(return_value=False),
        "services.learning.has_notes_for_lessons": AsyncMock(return_value={}),
        "services.learning.has_flashcards_for_unit": AsyncMock(return_value=False),
        "services.learning.has_flashcards_for_lessons": AsyncMock(return_value={}),
    }


@contextmanager
def _multi_patch(patches: dict):
    """Apply multiple patches at once as a context manager."""
    with contextlib.ExitStack() as stack:
        for target, mock in patches.items():
            stack.enter_context(_patch(target, mock))
        yield


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestHasNotesFlag:
    def test_unit_has_notes_true_when_note_exists(self):
        patches = _patch_learning_repos()
        patches["services.learning.has_notes_for_unit"] = AsyncMock(return_value=True)

        async def go():
            from services.learning import _build_study_page

            with _multi_patch(patches):
                return await _build_study_page(unit_id=1, user_id=1)

        result = _run(go())
        assert result is not None
        assert result.has_notes is True

    def test_unit_has_notes_false_when_no_notes(self):
        patches = _patch_learning_repos()
        # default is False — no override needed

        async def go():
            from services.learning import _build_study_page

            with _multi_patch(patches):
                return await _build_study_page(unit_id=1, user_id=1)

        result = _run(go())
        assert result is not None
        assert result.has_notes is False

    def test_lesson_has_notes_true_propagates(self):
        patches = _patch_learning_repos()
        patches["services.learning.has_notes_for_lessons"] = AsyncMock(
            return_value={100: True}
        )

        async def go():
            from services.learning import _build_study_page

            with _multi_patch(patches):
                return await _build_study_page(unit_id=1, user_id=1)

        result = _run(go())
        assert result is not None
        lesson = result.sections[0].lessons[0]
        assert lesson.has_notes is True

    def test_lesson_has_notes_false_when_not_in_map(self):
        patches = _patch_learning_repos()
        patches["services.learning.has_notes_for_lessons"] = AsyncMock(return_value={})

        async def go():
            from services.learning import _build_study_page

            with _multi_patch(patches):
                return await _build_study_page(unit_id=1, user_id=1)

        result = _run(go())
        assert result is not None
        lesson = result.sections[0].lessons[0]
        assert lesson.has_notes is False


class TestHasFlashcardsFlag:
    def test_unit_has_flashcards_true_when_card_exists(self):
        patches = _patch_learning_repos()
        patches["services.learning.has_flashcards_for_unit"] = AsyncMock(
            return_value=True
        )

        async def go():
            from services.learning import _build_study_page

            with _multi_patch(patches):
                return await _build_study_page(unit_id=1, user_id=1)

        result = _run(go())
        assert result is not None
        assert result.has_flashcards is True

    def test_unit_has_flashcards_false_when_none(self):
        patches = _patch_learning_repos()
        # default is False — no override needed

        async def go():
            from services.learning import _build_study_page

            with _multi_patch(patches):
                return await _build_study_page(unit_id=1, user_id=1)

        result = _run(go())
        assert result is not None
        assert result.has_flashcards is False

    def test_lesson_has_flashcards_true_propagates(self):
        patches = _patch_learning_repos()
        patches["services.learning.has_flashcards_for_lessons"] = AsyncMock(
            return_value={100: True}
        )

        async def go():
            from services.learning import _build_study_page

            with _multi_patch(patches):
                return await _build_study_page(unit_id=1, user_id=1)

        result = _run(go())
        assert result is not None
        lesson = result.sections[0].lessons[0]
        assert lesson.has_flashcards is True


class TestUnitNotFound:
    def test_returns_none_when_unit_missing(self):
        patches = _patch_learning_repos(unit=None)

        async def go():
            from services.learning import _build_study_page

            with _multi_patch(patches):
                return await _build_study_page(unit_id=999, user_id=1)

        result = _run(go())
        assert result is None
