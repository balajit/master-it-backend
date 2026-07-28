from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import database.repositories.flashcards as fc_repo
from services.learning import invalidate_study_page_cache


async def generate_flashcards(
    *,
    scope: str,
    target_id: int,
    card_scope: str,
    user_id: int,
    force: bool = False,
) -> List[Dict[str, Any]]:
    """Generate flashcards for a unit or lesson via the learning platform.

    Parameters
    ----------
    scope:      "unit" or "lesson" — what the target_id refers to
    target_id:  The unit_id or lesson_id to generate flashcards for
    card_scope: "user" (user-owned) or "course" (course-scoped, user_id=None)
    user_id:    The requesting user — used as created_by and as user_id when card_scope='user'
    force:      If True, delete existing generated cards before inserting new ones.
                If False and generated cards already exist, raises HTTP 409.
    """
    owner_id: Optional[int] = user_id if card_scope == "user" else None
    unit_id: Optional[int] = target_id if scope == "unit" else None
    lesson_id: Optional[int] = target_id if scope == "lesson" else None

    # Check for existing generated cards
    existing = await fc_repo.get_generated_flashcards(
        user_id=owner_id,
        unit_id=unit_id,
        lesson_id=lesson_id,
    )

    if existing:
        if not force:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Generated flashcards already exist for this target. "
                    "Pass force=true to replace them."
                ),
            )
        # force=True: delete then regenerate
        await fc_repo.delete_generated_flashcards(
            user_id=owner_id,
            unit_id=unit_id,
            lesson_id=lesson_id,
        )

    seeds = await _get_seeds(scope=scope, target_id=target_id)

    if not seeds:
        return []

    records = [
        {
            "created_by": user_id,
            "front": s["front"],
            "back": s["back"],
            "user_id": owner_id,
            "course_id": None,
            "unit_id": unit_id,
            "lesson_id": lesson_id,
            "is_generated": True,
        }
        for s in seeds
    ]

    result = await fc_repo.bulk_create_flashcards(records)

    # Invalidate study page cache so has_flashcards flags update
    resolved_unit_id: Optional[int] = unit_id
    if lesson_id is not None:
        # We don't have unit_id here directly; pass None to clear all
        resolved_unit_id = None
    invalidate_study_page_cache(resolved_unit_id)

    return result


async def _get_seeds(scope: str, target_id: int) -> List[Dict[str, str]]:
    """Retrieve FlashcardSeed data from the learning platform for a unit or lesson.

    Returns a list of {"front": ..., "back": ...} dicts.
    Falls back to empty list if LP data is unavailable.
    """
    try:
        from learning_platform.stages.flashcard_generator.generator import (
            generate_seeds_for_unit,
            generate_seeds_for_lesson,
        )

        if scope == "unit":
            seeds = await generate_seeds_for_unit(target_id)
        else:
            seeds = await generate_seeds_for_lesson(target_id)

        return [{"front": s.front, "back": s.back} for s in seeds]
    except ImportError:
        # LP generator not yet implemented — return empty
        return []
    except Exception:
        # Graceful degradation: LP unavailable should not crash the endpoint
        return []
