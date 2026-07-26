"""Learning Service — assembles the complete study page from repository data.

Optimizations applied:
  • 8 batch queries (no N+1)
  • Per-user TTL cache avoids repeated DB hits for the same page
  • Pre-built section ID sets eliminate quadratic set construction
  • Single-pass stats + squares computation
"""

from __future__ import annotations

from typing import Dict, List, Optional

from cache import TTLCache
from database.repositories.learning import (
    get_lesson_progress_for_user,
    get_practice_progress_for_user,
    get_quiz_progress_for_user,
    get_unit,
    list_lessons_for_sections,
    list_practices_for_sections,
    list_quizzes_for_sections,
    list_sections,
)
from schemas import (
    ProgressResponse,
    ProgressSquareResponse,
    SectionResponse,
    UnitResponse,
)
from services.progress import (
    determine_goal_status,
    merge_lesson_status,
    merge_practice_status,
    merge_quiz_status,
)

# ── Cache ──────────────────────────────────────────────────────────────────
# Keyed by (unit_id, user_id).  TTL keeps stale data bounded while
# allowing rapid page-navigation without redundant DB round-trips.
_study_page_cache: TTLCache[UnitResponse] = TTLCache(ttl=60.0)


def invalidate_study_page_cache(unit_id: int | None = None) -> None:
    """Evict cached study pages.  Call after any write that affects progress
    or content structure.

    If *unit_id* is ``None`` the entire cache is cleared (safe fallback).
    """
    if unit_id is None:
        _study_page_cache.clear()
        return
    # Evict all users' caches for this unit
    keys_to_remove: list[str] = [
        k for k in list(_study_page_cache._store) if k.startswith(f"{unit_id}:")
    ]
    for k in keys_to_remove:
        _study_page_cache.invalidate(k)


# ── Main entry point ──────────────────────────────────────────────────────


async def get_unit_details(unit_id: int, user_id: int) -> Optional[UnitResponse]:
    """Return the complete study page for a unit, including user progress.

    Uses 8 queries total regardless of data size, and caches the result
    per ``(unit_id, user_id)`` for 60 seconds.

    Queries:
      1. get_unit
      2. list_sections
      3. list_lessons_for_sections (batch)
      4. list_practices_for_sections (batch)
      5. list_quizzes_for_sections (batch)
      6. get_lesson_progress_for_user (batch)
      7. get_practice_progress_for_user (batch)
      8. get_quiz_progress_for_user (batch)
    """
    cache_key: str = f"{unit_id}:{user_id}"
    cached = _study_page_cache.get(cache_key)
    if cached is not None:
        return cached

    result = await _build_study_page(unit_id, user_id)
    if result is not None:
        _study_page_cache.set(cache_key, result)
    return result


async def _build_study_page(unit_id: int, user_id: int) -> Optional[UnitResponse]:
    """Core assembly logic — runs only on cache miss."""
    unit = await get_unit(unit_id)
    if not unit:
        return None

    sections_data = await list_sections(unit_id)
    section_ids: List[int] = [s["id"] for s in sections_data]

    # Batch fetch all content for this unit's sections
    all_lessons = await list_lessons_for_sections(section_ids)
    all_practices = await list_practices_for_sections(section_ids)
    all_quizzes = await list_quizzes_for_sections(section_ids)

    # Batch fetch all user progress for this unit
    lesson_ids: List[int] = [lesson["id"] for lesson in all_lessons]
    practice_ids: List[int] = [p["id"] for p in all_practices]
    quiz_ids: List[int] = [q["id"] for q in all_quizzes]

    lesson_progress: Dict[int, Dict] = await get_lesson_progress_for_user(
        user_id, lesson_ids
    )
    practice_progress: Dict[int, Dict] = await get_practice_progress_for_user(
        user_id, practice_ids
    )
    quiz_progress: Dict[int, Dict] = await get_quiz_progress_for_user(user_id, quiz_ids)

    # Pre-build section → items indexes (avoids O(S × L) set construction)
    lessons_by_section: Dict[int, List[Dict]] = {}
    for lesson in all_lessons:
        lessons_by_section.setdefault(lesson["section_id"], []).append(lesson)

    practices_by_section: Dict[int, List[Dict]] = {}
    for practice in all_practices:
        practices_by_section.setdefault(practice["section_id"], []).append(practice)

    quizzes_by_section: Dict[int, List[Dict]] = {}
    for quiz in all_quizzes:
        quizzes_by_section.setdefault(quiz["section_id"], []).append(quiz)

    # Pre-compute per-section ID sets for O(1) membership tests
    lesson_ids_by_section: Dict[int, set[int]] = {
        sid: {item["id"] for item in items} for sid, items in lessons_by_section.items()
    }
    practice_ids_by_section: Dict[int, set[int]] = {
        sid: {item["id"] for item in items}
        for sid, items in practices_by_section.items()
    }
    quiz_ids_by_section: Dict[int, set[int]] = {
        sid: {item["id"] for item in items} for sid, items in quizzes_by_section.items()
    }

    # Assemble sections — single-pass: collect progress counts while building
    sections: List[SectionResponse] = []
    # Running totals for stats (avoids second pass through all items)
    total_items: int = 0
    mastered_count: int = 0

    for sec in sections_data:
        sec_id = sec["id"]

        sec_lesson_ids: set[int] = lesson_ids_by_section.get(sec_id, set())
        sec_practice_ids: set[int] = practice_ids_by_section.get(sec_id, set())
        sec_quiz_ids: set[int] = quiz_ids_by_section.get(sec_id, set())

        lessons = merge_lesson_status(
            lessons_by_section.get(sec_id, []),
            {
                lid: lesson_progress[lid]
                for lid in sec_lesson_ids
                if lid in lesson_progress
            },
        )
        practices = merge_practice_status(
            practices_by_section.get(sec_id, []),
            {
                pid: practice_progress[pid]
                for pid in sec_practice_ids
                if pid in practice_progress
            },
        )
        goals = merge_quiz_status(
            quizzes_by_section.get(sec_id, []),
            {qid: quiz_progress[qid] for qid in sec_quiz_ids if qid in quiz_progress},
        )

        # Accumulate stats inline
        for lesson in lessons:
            total_items += 1
            if lesson.status.value == "MASTERED":
                mastered_count += 1
        for practice in practices:
            total_items += 1
            if practice.status.value == "MASTERED":
                mastered_count += 1
        for goal in goals:
            total_items += 1
            goal_status = determine_goal_status(goal)
            if goal_status.value == "MASTERED":
                mastered_count += 1

        sections.append(
            SectionResponse(
                id=sec_id,
                title=sec["title"],
                estimated_minutes=sec["estimated_minutes"],
                order=sec["display_order"],
                lessons=lessons,
                practices=practices,
                goals=goals,
            )
        )

    # Build progress squares — sections are already ordered, so no sort needed
    squares: List[ProgressSquareResponse] = _progress_squares_ordered(sections)

    mastered_pct: float = (
        round(mastered_count / total_items * 100, 2) if total_items > 0 else 0.0
    )

    return UnitResponse(
        id=unit["id"],
        title=unit["title"],
        description=unit["description"],
        course_id=unit["course_id"],
        progress=ProgressResponse(
            total=total_items,
            completed=mastered_count,
            mastered_pct=mastered_pct,
            squares=squares,
        ),
        about=unit["description"],
        sections=sections,
    )


# ── Optimized progress squares (no sort needed) ──────────────────────────


def _progress_squares_ordered(
    sections: List[SectionResponse],
) -> List[ProgressSquareResponse]:
    """Build progress squares.  Sections and items are already in display
    order, so we skip the O(n log n) sort that ``progress_squares()`` does.
    """
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
            squares.append(
                ProgressSquareResponse(
                    id=goal.id,
                    title=goal.title,
                    section_id=sec.id,
                    section_title=sec.title,
                    order=0,
                    status=determine_goal_status(goal),
                )
            )
    return squares
