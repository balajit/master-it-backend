"""Tests for the Progress Service."""

from __future__ import annotations

import sys
from pathlib import Path

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from schemas import (  # noqa: E402
    GoalResponse,
    LessonResponse,
    PracticeResponse,
    ProgressResponse,
    ProgressSquareResponse,
    ProgressStatus,
    SectionResponse,
)
from services.progress import (  # noqa: E402
    calculate_completed,
    determine_lesson_status,
    determine_practice_status,
    determine_goal_status,
    determine_quiz_status,
    mastery_pct,
    merge_lesson_status,
    merge_practice_status,
    merge_quiz_status,
    progress_squares,
    stats,
)


# ── Status Determination ────────────────────────────────────────────────────


class TestDetermineLessonStatus:
    def test_mastered_when_completed(self):
        progress = {
            "lesson_id": 1,
            "status": "COMPLETED",
            "completed_at": "2026-01-15T10:00:00",
        }
        assert determine_lesson_status(progress) == ProgressStatus.MASTERED

    def test_not_started_when_no_progress(self):
        assert determine_lesson_status(None) == ProgressStatus.NOT_STARTED

    def test_attempted_when_in_progress(self):
        progress = {"lesson_id": 1, "status": "IN_PROGRESS", "completed_at": None}
        assert determine_lesson_status(progress) == ProgressStatus.ATTEMPTED

    def test_familiar_when_viewed(self):
        progress = {"lesson_id": 1, "status": "VIEWED", "completed_at": None}
        assert determine_lesson_status(progress) == ProgressStatus.FAMILIAR

    def test_locked_when_in_locked_ids(self):
        progress = {
            "lesson_id": 1,
            "status": "COMPLETED",
            "completed_at": "2026-01-15T10:00:00",
        }
        assert (
            determine_lesson_status(progress, locked_ids={1}) == ProgressStatus.LOCKED
        )


class TestDeterminePracticeStatus:
    def test_mastered_when_score_meets_required(self):
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

    def test_practiced_when_attempts_but_not_mastered(self):
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

    def test_not_started_when_no_progress(self):
        assert determine_practice_status(None) == ProgressStatus.NOT_STARTED

    def test_attempted_when_in_progress(self):
        progress = {
            "practice_id": 1,
            "attempts": 0,
            "best_score": 0.0,
            "status": "IN_PROGRESS",
        }
        assert determine_practice_status(progress) == ProgressStatus.ATTEMPTED

    def test_locked_when_in_locked_ids(self):
        progress = {
            "practice_id": 1,
            "attempts": 3,
            "best_score": 8.0,
            "status": "COMPLETED",
        }
        assert (
            determine_practice_status(progress, required_correct=8, locked_ids={1})
            == ProgressStatus.LOCKED
        )

    def test_not_mastered_when_required_zero(self):
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


class TestDetermineQuizStatus:
    def test_mastered_when_score_passes(self):
        progress = {"quiz_id": 1, "score": 85.0, "completed_at": "2026-01-20T12:00:00"}
        assert determine_quiz_status(progress) == ProgressStatus.MASTERED

    def test_attempted_when_score_fails(self):
        progress = {"quiz_id": 1, "score": 45.0, "completed_at": None}
        assert determine_quiz_status(progress) == ProgressStatus.ATTEMPTED

    def test_not_started_when_no_progress(self):
        assert determine_quiz_status(None) == ProgressStatus.NOT_STARTED

    def test_locked_when_in_locked_ids(self):
        progress = {"quiz_id": 1, "score": 85.0, "completed_at": "2026-01-20T12:00:00"}
        assert determine_quiz_status(progress, locked_ids={1}) == ProgressStatus.LOCKED

    def test_custom_passing_score(self):
        progress = {"quiz_id": 1, "score": 80.0, "completed_at": None}
        assert (
            determine_quiz_status(progress, passing_score=80.0)
            == ProgressStatus.MASTERED
        )


class TestDetermineGoalStatus:
    def test_mastered_when_completed(self):
        goal = GoalResponse(
            id=1, title="Q1", score=85.0, completed_at="2026-01-20T12:00:00"
        )
        assert determine_goal_status(goal) == ProgressStatus.MASTERED

    def test_attempted_when_score_only(self):
        goal = GoalResponse(id=1, title="Q1", score=50.0, completed_at=None)
        assert determine_goal_status(goal) == ProgressStatus.ATTEMPTED

    def test_not_started_when_no_score(self):
        goal = GoalResponse(id=1, title="Q1", score=None, completed_at=None)
        assert determine_goal_status(goal) == ProgressStatus.NOT_STARTED


# ── Merge Functions ─────────────────────────────────────────────────────────


class TestMergeLessonStatus:
    def test_merges_progress_into_lessons(self):
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
                "completed_at": "2026-01-15T10:00:00",
            },
        }
        result = merge_lesson_status(lessons, progress_map)
        assert len(result) == 2
        assert result[0].status == ProgressStatus.MASTERED
        assert result[0].completed_at == "2026-01-15T10:00:00"
        assert result[1].status == ProgressStatus.NOT_STARTED

    def test_empty_lessons(self):
        assert merge_lesson_status([], {}) == []


class TestMergePracticeStatus:
    def test_merges_progress_into_practices(self):
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
        assert len(result) == 1
        assert result[0].status == ProgressStatus.MASTERED
        assert result[0].attempts == 3

    def test_empty_practices(self):
        assert merge_practice_status([], {}) == []


class TestMergeQuizStatus:
    def test_merges_progress_into_quizzes(self):
        quizzes = [
            {"id": 1, "section_id": 10, "title": "Q1"},
        ]
        progress_map = {
            1: {"quiz_id": 1, "score": 85.0, "completed_at": "2026-01-20T12:00:00"},
        }
        result = merge_quiz_status(quizzes, progress_map)
        assert len(result) == 1
        assert result[0].score == 85.0

    def test_empty_quizzes(self):
        assert merge_quiz_status([], {}) == []


# ── Statistics ──────────────────────────────────────────────────────────────


def _make_section(
    section_id: int = 1,
    lessons: list[LessonResponse] | None = None,
    practices: list[PracticeResponse] | None = None,
    goals: list[GoalResponse] | None = None,
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
    score = 85.0 if status == "MASTERED" else (45.0 if status == "ATTEMPTED" else None)
    completed = "2026-01-20T12:00:00" if status == "MASTERED" else None
    return GoalResponse(
        id=goal_id,
        title="Q",
        score=score,
        completed_at=completed,
    )


class TestCalculateCompleted:
    def test_counts_mastered(self):
        sec = _make_section(
            lessons=[_lesson("MASTERED"), _lesson("NOT_STARTED", 2)],
            practices=[_practice("MASTERED")],
        )
        assert calculate_completed([sec]) == 2

    def test_empty_sections(self):
        assert calculate_completed([]) == 0


class TestMasteryPct:
    def test_half_mastered(self):
        sec = _make_section(
            lessons=[_lesson("MASTERED"), _lesson("NOT_STARTED", 2)],
        )
        assert mastery_pct([sec]) == 50.0

    def test_empty_returns_zero(self):
        assert mastery_pct([]) == 0.0

    def test_all_mastered(self):
        sec = _make_section(
            lessons=[_lesson("MASTERED"), _lesson("MASTERED", 2)],
        )
        assert mastery_pct([sec]) == 100.0


class TestStats:
    def test_mixed_statuses(self):
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

    def test_all_not_started(self):
        sec = _make_section(lessons=[_lesson("NOT_STARTED"), _lesson("NOT_STARTED", 2)])
        result = stats([sec])
        assert result.total == 2
        assert result.completed == 0
        assert result.mastered_pct == 0.0


# ── Progress Squares ───────────────────────────────────────────────────────


class TestProgressSquares:
    def test_builds_squares_from_sections(self):
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

    def test_empty_sections(self):
        assert progress_squares([]) == []

    def test_sorted_by_section_and_order(self):
        sec1 = _make_section(section_id=2, lessons=[_lesson("MASTERED")])
        sec2 = _make_section(section_id=1, lessons=[_lesson("NOT_STARTED")])
        squares = progress_squares([sec1, sec2])
        assert squares[0].section_id == 1
        assert squares[1].section_id == 2


class TestProgressResponseModel:
    def test_model_serialization(self):
        s = ProgressResponse(total=10, completed=5, mastered_pct=50.0)
        d = s.model_dump()
        assert d["total"] == 10
        assert d["mastered_pct"] == 50.0


class TestProgressSquareResponseModel:
    def test_model_serialization(self):
        sq = ProgressSquareResponse(
            id=1,
            title="L1",
            section_id=10,
            section_title="S1",
            order=0,
            status=ProgressStatus.MASTERED,
        )
        d = sq.model_dump()
        assert d["status"] == "mastered"
