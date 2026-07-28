from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserFlashcardModel
from database.session import engine


def _card_to_dict(card: UserFlashcardModel) -> Dict[str, Any]:
    return {
        "id": card.id,
        "user_id": card.user_id,
        "created_by": card.created_by,
        "front": card.front,
        "back": card.back,
        "course_id": card.course_id,
        "unit_id": card.unit_id,
        "lesson_id": card.lesson_id,
        "is_generated": card.is_generated,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }


async def create_flashcard(
    created_by: int,
    front: str,
    back: str,
    user_id: Optional[int],
    course_id: Optional[int],
    unit_id: Optional[int],
    lesson_id: Optional[int],
    is_generated: bool = False,
) -> Dict[str, Any]:
    async with AsyncSession(engine) as session:
        card = UserFlashcardModel(
            created_by=created_by,
            front=front,
            back=back,
            user_id=user_id,
            course_id=course_id,
            unit_id=unit_id,
            lesson_id=lesson_id,
            is_generated=is_generated,
        )
        session.add(card)
        await session.commit()
        await session.refresh(card)
        return _card_to_dict(card)


async def bulk_create_flashcards(
    cards: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Insert multiple flashcards in a single transaction."""
    async with AsyncSession(engine) as session:
        models = [UserFlashcardModel(**c) for c in cards]
        session.add_all(models)
        await session.commit()
        for m in models:
            await session.refresh(m)
        return [_card_to_dict(m) for m in models]


async def get_flashcard_by_id(card_id: int) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardModel).where(UserFlashcardModel.id == card_id)
        )
        card = result.scalars().first()
        return _card_to_dict(card) if card else None


async def update_flashcard(
    card_id: int,
    created_by: int,
    front: Optional[str],
    back: Optional[str],
) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardModel).where(
                UserFlashcardModel.id == card_id,
                UserFlashcardModel.created_by == created_by,
            )
        )
        card = result.scalars().first()
        if card is None:
            return None
        if front is not None:
            card.front = front
        if back is not None:
            card.back = back
        await session.commit()
        await session.refresh(card)
        return _card_to_dict(card)


async def delete_flashcard(card_id: int, created_by: int) -> bool:
    """Delete a flashcard. Returns True if deleted, False if not found or not creator."""
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardModel).where(
                UserFlashcardModel.id == card_id,
                UserFlashcardModel.created_by == created_by,
            )
        )
        card = result.scalars().first()
        if card is None:
            return False
        await session.delete(card)
        await session.commit()
        return True


def _visibility_filter(
    user_id: int,
    course_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    lesson_id: Optional[int] = None,
) -> list:  # type: ignore[type-arg]
    """Build WHERE clauses: user-owned OR course-scoped within the same course/unit/lesson."""
    from sqlalchemy import or_

    user_owned = UserFlashcardModel.user_id == user_id
    if course_id is not None:
        course_scoped = (UserFlashcardModel.user_id.is_(None)) & (
            UserFlashcardModel.course_id == course_id
        )
        return [or_(user_owned, course_scoped)]
    if unit_id is not None:
        course_scoped = (UserFlashcardModel.user_id.is_(None)) & (
            UserFlashcardModel.unit_id == unit_id
        )
        return [or_(user_owned, course_scoped)]
    if lesson_id is not None:
        course_scoped = (UserFlashcardModel.user_id.is_(None)) & (
            UserFlashcardModel.lesson_id == lesson_id
        )
        return [or_(user_owned, course_scoped)]
    return [user_owned]


async def get_flashcards_for_unit(unit_id: int, user_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardModel)
            .where(
                UserFlashcardModel.unit_id == unit_id,
                *_visibility_filter(user_id, unit_id=unit_id),
            )
            .order_by(UserFlashcardModel.created_at)
        )
        return [_card_to_dict(c) for c in result.scalars().all()]


async def get_flashcards_for_lesson(
    lesson_id: int, user_id: int
) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardModel)
            .where(
                UserFlashcardModel.lesson_id == lesson_id,
                *_visibility_filter(user_id, lesson_id=lesson_id),
            )
            .order_by(UserFlashcardModel.created_at)
        )
        return [_card_to_dict(c) for c in result.scalars().all()]


async def get_flashcards_for_course(
    course_id: int, user_id: int
) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardModel)
            .where(
                UserFlashcardModel.course_id == course_id,
                *_visibility_filter(user_id, course_id=course_id),
            )
            .order_by(UserFlashcardModel.created_at)
        )
        return [_card_to_dict(c) for c in result.scalars().all()]


async def has_flashcards_for_unit(unit_id: int, user_id: int) -> bool:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(
                exists().where(
                    UserFlashcardModel.unit_id == unit_id,
                    *_visibility_filter(user_id, unit_id=unit_id),
                )
            )
        )
        return bool(result.scalar())


async def has_flashcards_for_lessons(
    lesson_ids: List[int], user_id: int
) -> Dict[int, bool]:
    """Return a mapping of lesson_id → bool for visible flashcard existence."""
    if not lesson_ids:
        return {}
    from sqlalchemy import or_

    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardModel.lesson_id)
            .where(
                UserFlashcardModel.lesson_id.in_(lesson_ids),
                or_(
                    UserFlashcardModel.user_id == user_id,
                    UserFlashcardModel.user_id.is_(None),
                ),
            )
            .distinct()
        )
        ids_with_cards = {row[0] for row in result.all()}
        return {lid: lid in ids_with_cards for lid in lesson_ids}


async def get_generated_flashcards(
    user_id: Optional[int],
    course_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    lesson_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fetch existing generated flashcards for a target+scope combination."""
    async with AsyncSession(engine) as session:
        filters = [UserFlashcardModel.is_generated.is_(True)]
        if user_id is not None:
            filters.append(UserFlashcardModel.user_id == user_id)
        else:
            filters.append(UserFlashcardModel.user_id.is_(None))
        if course_id is not None:
            filters.append(UserFlashcardModel.course_id == course_id)
        if unit_id is not None:
            filters.append(UserFlashcardModel.unit_id == unit_id)
        if lesson_id is not None:
            filters.append(UserFlashcardModel.lesson_id == lesson_id)
        result = await session.execute(select(UserFlashcardModel).where(*filters))
        return [_card_to_dict(c) for c in result.scalars().all()]


async def delete_generated_flashcards(
    user_id: Optional[int],
    course_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    lesson_id: Optional[int] = None,
) -> int:
    """Delete existing generated flashcards for a target+scope. Returns count deleted."""
    async with AsyncSession(engine) as session:
        filters = [UserFlashcardModel.is_generated.is_(True)]
        if user_id is not None:
            filters.append(UserFlashcardModel.user_id == user_id)
        else:
            filters.append(UserFlashcardModel.user_id.is_(None))
        if course_id is not None:
            filters.append(UserFlashcardModel.course_id == course_id)
        if unit_id is not None:
            filters.append(UserFlashcardModel.unit_id == unit_id)
        if lesson_id is not None:
            filters.append(UserFlashcardModel.lesson_id == lesson_id)
        result = await session.execute(delete(UserFlashcardModel).where(*filters))
        await session.commit()
        return result.rowcount
