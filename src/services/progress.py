"""Progress Service — reusable progress calculations for dashboards, reports, and profile pages."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from schemas import (
    GoalResponse,
    LessonResponse,
    PracticeResponse,
    ProgressResponse,
    ProgressSquareResponse,
    ProgressStatus,
    SectionResponse,
)


# ── Status Determination ────────────────────────────────────────────────────


def determine_lesson_status(
    progress: Optional[Dict[str, Any]],
    locked_ids: Optional[set[int]] = None,
) -> ProgressStatus:
    """Determine the status of a lesson from its progress record."""
    if locked_ids and progress and progress["lesson_id"] in locked_ids:
        return ProgressStatus.LOCKED
    if progress and progress.get("completed_at"):
        return ProgressStatus.MASTERED
    if progress and progress.get("status") == "IN_PROGRESS":
        return ProgressStatus.ATTEMPTED
    if progress and progress.get("status") == "VIEWED":
        return ProgressStatus.FAMILIAR
    return ProgressStatus.NOT_STARTED


def determine_practice_status(
    progress: Optional[Dict[str, Any]],
    required_correct: int = 0,
    locked_ids: Optional[set[int]] = None,
) -> ProgressStatus:
    """Determine the status of a practice activity from its progress record."""
    if locked_ids and progress and progress["practice_id"] in locked_ids:
        return ProgressStatus.LOCKED
    if (
        progress
        and required_correct > 0
        and progress.get("best_score", 0) >= required_correct
    ):
        return ProgressStatus.MASTERED
    if progress and progress.get("attempts", 0) > 0:
        return ProgressStatus.PRACTICED
    if progress and progress.get("status") == "IN_PROGRESS":
        return ProgressStatus.ATTEMPTED
    return ProgressStatus.NOT_STARTED


def determine_quiz_status(
    progress: Optional[Dict[str, Any]],
    locked_ids: Optional[set[int]] = None,
    passing_score: float = 70.0,
) -> ProgressStatus:
    """Determine the status of a quiz from its progress record."""
    if locked_ids and progress and progress["quiz_id"] in locked_ids:
        return ProgressStatus.LOCKED
    if progress and progress.get("score") is not None:
        if progress["score"] >= passing_score:
            return ProgressStatus.MASTERED
        return ProgressStatus.ATTEMPTED
    return ProgressStatus.NOT_STARTED


# ── Merge Status Into Content ──────────────────────────────────────────────


def merge_lesson_status(
    lessons: List[Dict[str, Any]],
    progress_map: Dict[int, Dict[str, Any]],
    locked_ids: Optional[set[int]] = None,
) -> List[LessonResponse]:
    """Merge progress status into lesson data, returning clean LessonResponse list."""
    from services.learning import format_duration  # avoid circular at module level

    result: list[LessonResponse] = []
    for lesson in lessons:
        progress = progress_map.get(lesson["id"])
        status = determine_lesson_status(progress, locked_ids)
        result.append(
            LessonResponse(
                id=lesson["id"],
                title=lesson["title"],
                description=lesson["description"],
                duration_minutes=lesson["duration_minutes"],
                duration_label=format_duration(lesson["duration_minutes"]),
                order=lesson["display_order"],
                status=status,
                completed_at=progress["completed_at"] if progress else None,
                sidebar_status=to_sidebar_status(status),
            )
        )
    return result


def merge_practice_status(
    practices: List[Dict[str, Any]],
    progress_map: Dict[int, Dict[str, Any]],
    locked_ids: Optional[set[int]] = None,
) -> List[PracticeResponse]:
    """Merge progress status into practice data, returning clean PracticeResponse list."""
    result: list[PracticeResponse] = []
    for practice in practices:
        progress = progress_map.get(practice["id"])
        status = determine_practice_status(
            progress,
            required_correct=practice.get("required_correct", 0),
            locked_ids=locked_ids,
        )
        req: int = practice["required_correct"]
        total: int = practice["total_questions"]
        progress_label: str = f"Score {req}/{total} to pass" if total > 0 else ""
        result.append(
            PracticeResponse(
                id=practice["id"],
                title=practice["title"],
                required_correct=req,
                total_questions=total,
                order=practice["display_order"],
                status=status,
                attempts=progress["attempts"] if progress else 0,
                best_score=progress["best_score"] if progress else 0.0,
                # TODO: derive from db column once added
                activity_type=practice.get("practice_type") or "practice",
                locked=status == ProgressStatus.LOCKED,
                progress_label=progress_label,
                action_label=_action_label(status),
                sidebar_status=to_sidebar_status(status),
            )
        )
    return result


def merge_quiz_status(
    quizzes: List[Dict[str, Any]],
    progress_map: Dict[int, Dict[str, Any]],
    locked_ids: Optional[set[int]] = None,
    passing_score: float = 70.0,
) -> List[GoalResponse]:
    """Merge progress status into quiz data, returning clean GoalResponse list."""
    result: list[GoalResponse] = []
    for quiz in quizzes:
        progress = progress_map.get(quiz["id"])
        status = determine_quiz_status(progress, locked_ids, passing_score)
        result.append(
            GoalResponse(
                id=quiz["id"],
                title=quiz["title"],
                score=progress["score"] if progress else None,
                completed_at=progress["completed_at"] if progress else None,
                status=status,
                locked=status == ProgressStatus.LOCKED,
                action_label=_action_label(status),
            )
        )
    return result


# ── Statistics ──────────────────────────────────────────────────────────────


def _count_statuses(
    sections: Sequence[SectionResponse],
) -> Dict[ProgressStatus, int]:
    """Count items per status across all sections."""
    counts: dict[ProgressStatus, int] = {s: 0 for s in ProgressStatus}
    for sec in sections:
        for lesson in sec.lessons:
            counts[lesson.status] += 1
        for practice in sec.practices:
            counts[practice.status] += 1
        for goal in sec.goals:
            counts[determine_goal_status(goal)] += 1
    return counts


def determine_goal_status(goal: GoalResponse) -> ProgressStatus:
    """Derive a status label from a GoalResponse model."""
    if goal.completed_at:
        return ProgressStatus.MASTERED
    if goal.score is not None:
        return ProgressStatus.ATTEMPTED
    return ProgressStatus.NOT_STARTED


def to_sidebar_status(status: ProgressStatus) -> str:
    """Collapse 6-state ProgressStatus into the 3-state sidebar ItemStatus."""
    if status == ProgressStatus.MASTERED:
        return "completed"
    if status in (
        ProgressStatus.PRACTICED,
        ProgressStatus.FAMILIAR,
        ProgressStatus.ATTEMPTED,
    ):
        return "in_progress"
    return "not_started"  # covers NOT_STARTED and LOCKED


def _action_label(status: ProgressStatus) -> str:
    """Derive action button label from status."""
    if status == ProgressStatus.MASTERED:
        return "Review"
    if status in (
        ProgressStatus.ATTEMPTED,
        ProgressStatus.PRACTICED,
        ProgressStatus.FAMILIAR,
    ):
        return "Continue"
    return "Start"


def calculate_completed(sections: Sequence[SectionResponse]) -> int:
    """Return the number of MASTERED items across all sections."""
    counts = _count_statuses(sections)
    return counts[ProgressStatus.MASTERED]


def mastery_pct(sections: Sequence[SectionResponse]) -> float:
    """Return the mastery percentage (0.0 – 100.0)."""
    counts = _count_statuses(sections)
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return round(counts[ProgressStatus.MASTERED] / total * 100, 2)


def stats(sections: Sequence[SectionResponse]) -> ProgressResponse:
    """Return full progress statistics for the given sections."""
    counts = _count_statuses(sections)
    total = sum(counts.values())
    return ProgressResponse(
        total=total,
        completed=counts[ProgressStatus.MASTERED],
        mastered_pct=round(counts[ProgressStatus.MASTERED] / total * 100, 2)
        if total > 0
        else 0.0,
    )


# ── Progress Squares ───────────────────────────────────────────────────────


def progress_squares(
    sections: Sequence[SectionResponse],
) -> List[ProgressSquareResponse]:
    """Build the progress squares shown in the UI grid."""
    squares: list[ProgressSquareResponse] = []
    for sec in sections:
        for lesson in sec.lessons:
            squares.append(
                ProgressSquareResponse(
                    id=lesson.id,
                    title=lesson.title,
                    section_id=sec.id,
                    section_title=sec.title,
                    order=lesson.order,
                    status=lesson.status,
                )
            )
        for practice in sec.practices:
            squares.append(
                ProgressSquareResponse(
                    id=practice.id,
                    title=practice.title,
                    section_id=sec.id,
                    section_title=sec.title,
                    order=practice.order,
                    status=practice.status,
                )
            )
        for goal in sec.goals:
            status = determine_goal_status(goal)
            squares.append(
                ProgressSquareResponse(
                    id=goal.id,
                    title=goal.title,
                    section_id=sec.id,
                    section_title=sec.title,
                    order=0,
                    status=status,
                )
            )
    squares.sort(key=lambda sq: (sq.section_id, sq.order))
    return squares
