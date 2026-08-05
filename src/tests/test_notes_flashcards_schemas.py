"""Unit tests for Notes and Flashcard Pydantic schemas.

Covers:
  - NoteCreate model_validator (exactly one of unit_id / lesson_id)
  - FlashcardCreate model_validator (scope + target constraints)
  - FlashcardUpdate model_validator (at least one field)
  - FlashcardGenerateRequest defaults and field types
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from schemas import (  # noqa: E402
    FlashcardCreate,
    FlashcardGenerateRequest,
    FlashcardUpdate,
    NoteCreate,
    NoteUpdate,
)


# ── NoteCreate ──────────────────────────────────────────────────────────────


class TestNoteCreate:
    def test_unit_target_valid(self):
        unit_id = uuid.uuid4()
        note = NoteCreate(content="hello", unit_id=unit_id)
        assert note.unit_id == unit_id
        assert note.lesson_id is None

    def test_lesson_target_valid(self):
        lesson_id = uuid.uuid4()
        note = NoteCreate(content="hello", lesson_id=lesson_id)
        assert note.lesson_id == lesson_id
        assert note.unit_id is None

    def test_neither_target_raises(self):
        with pytest.raises(ValueError, match="Exactly one"):
            NoteCreate(content="hello")

    def test_both_targets_raises(self):
        with pytest.raises(ValueError, match="Exactly one"):
            NoteCreate(content="hello", unit_id=uuid.uuid4(), lesson_id=uuid.uuid4())

    def test_content_required(self):
        with pytest.raises(Exception):
            NoteCreate(unit_id=uuid.uuid4())  # type: ignore[call-arg]


class TestNoteUpdate:
    def test_content_required(self):
        update = NoteUpdate(content="updated")
        assert update.content == "updated"

    def test_empty_content_allowed(self):
        update = NoteUpdate(content="")
        assert update.content == ""


# ── FlashcardCreate ─────────────────────────────────────────────────────────


class TestFlashcardCreate:
    def test_user_scope_with_unit_id_valid(self):
        unit_id = uuid.uuid4()
        card = FlashcardCreate(front="Q", back="A", scope="user", unit_id=unit_id)
        assert card.scope == "user"
        assert card.unit_id == unit_id
        assert card.course_id is None

    def test_user_scope_with_lesson_id_valid(self):
        lesson_id = uuid.uuid4()
        card = FlashcardCreate(front="Q", back="A", scope="user", lesson_id=lesson_id)
        assert card.lesson_id == lesson_id

    def test_course_scope_with_course_id_valid(self):
        card = FlashcardCreate(front="Q", back="A", scope="course", course_id=2)
        assert card.course_id == 2

    def test_no_target_raises(self):
        with pytest.raises(ValueError, match="Exactly one"):
            FlashcardCreate(front="Q", back="A", scope="user")

    def test_multiple_targets_raises(self):
        with pytest.raises(ValueError, match="Exactly one"):
            FlashcardCreate(
                front="Q",
                back="A",
                scope="user",
                unit_id=uuid.uuid4(),
                lesson_id=uuid.uuid4(),
            )

    def test_course_scope_without_course_id_raises(self):
        with pytest.raises(ValueError, match="scope='course' requires course_id"):
            FlashcardCreate(front="Q", back="A", scope="course", unit_id=uuid.uuid4())

    def test_user_scope_with_course_id_raises(self):
        with pytest.raises(ValueError, match="scope='user' cannot use course_id"):
            FlashcardCreate(front="Q", back="A", scope="user", course_id=1)

    def test_three_targets_raises(self):
        with pytest.raises(ValueError, match="Exactly one"):
            FlashcardCreate(
                front="Q",
                back="A",
                scope="user",
                unit_id=uuid.uuid4(),
                lesson_id=uuid.uuid4(),
                course_id=3,
            )


# ── FlashcardUpdate ─────────────────────────────────────────────────────────


class TestFlashcardUpdate:
    def test_front_only_valid(self):
        update = FlashcardUpdate(front="new front")
        assert update.front == "new front"
        assert update.back is None

    def test_back_only_valid(self):
        update = FlashcardUpdate(back="new back")
        assert update.back == "new back"
        assert update.front is None

    def test_both_fields_valid(self):
        update = FlashcardUpdate(front="F", back="B")
        assert update.front == "F"
        assert update.back == "B"

    def test_neither_field_raises(self):
        with pytest.raises(ValueError, match="At least one"):
            FlashcardUpdate()


# ── FlashcardGenerateRequest ─────────────────────────────────────────────────


class TestFlashcardGenerateRequest:
    def test_defaults(self):
        req = FlashcardGenerateRequest(
            scope="unit",
            target_id=uuid.uuid4(),
            card_scope="user",
        )
        assert req.force is False

    def test_force_true(self):
        req = FlashcardGenerateRequest(
            scope="lesson",
            target_id=uuid.uuid4(),
            card_scope="course",
            force=True,
        )
        assert req.force is True
        assert req.scope == "lesson"

    def test_invalid_scope_raises(self):
        with pytest.raises(Exception):
            FlashcardGenerateRequest(  # type: ignore[arg-type]
                scope="section", target_id=uuid.uuid4(), card_scope="user"
            )

    def test_invalid_card_scope_raises(self):
        with pytest.raises(Exception):
            FlashcardGenerateRequest(  # type: ignore[arg-type]
                scope="unit", target_id=uuid.uuid4(), card_scope="admin"
            )
