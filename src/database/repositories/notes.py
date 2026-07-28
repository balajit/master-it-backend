from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserNoteModel
from database.session import engine


def _note_to_dict(note: UserNoteModel) -> Dict[str, Any]:
    return {
        "id": note.id,
        "user_id": note.user_id,
        "content": note.content,
        "unit_id": note.unit_id,
        "lesson_id": note.lesson_id,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
    }


async def create_note(
    user_id: int,
    content: str,
    unit_id: Optional[int],
    lesson_id: Optional[int],
) -> Dict[str, Any]:
    async with AsyncSession(engine) as session:
        note = UserNoteModel(
            user_id=user_id,
            content=content,
            unit_id=unit_id,
            lesson_id=lesson_id,
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)
        return _note_to_dict(note)


async def get_note_by_id(note_id: int) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserNoteModel).where(UserNoteModel.id == note_id)
        )
        note = result.scalars().first()
        return _note_to_dict(note) if note else None


async def update_note(
    note_id: int,
    user_id: int,
    content: str,
) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserNoteModel).where(
                UserNoteModel.id == note_id,
                UserNoteModel.user_id == user_id,
            )
        )
        note = result.scalars().first()
        if note is None:
            return None
        note.content = content
        await session.commit()
        await session.refresh(note)
        return _note_to_dict(note)


async def delete_note(note_id: int, user_id: int) -> bool:
    """Delete a note. Returns True if deleted, False if not found or not owner."""
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserNoteModel).where(
                UserNoteModel.id == note_id,
                UserNoteModel.user_id == user_id,
            )
        )
        note = result.scalars().first()
        if note is None:
            return False
        await session.delete(note)
        await session.commit()
        return True


async def get_notes_for_unit(unit_id: int, user_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserNoteModel)
            .where(
                UserNoteModel.unit_id == unit_id,
                UserNoteModel.user_id == user_id,
            )
            .order_by(UserNoteModel.created_at)
        )
        return [_note_to_dict(n) for n in result.scalars().all()]


async def get_notes_for_lesson(lesson_id: int, user_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserNoteModel)
            .where(
                UserNoteModel.lesson_id == lesson_id,
                UserNoteModel.user_id == user_id,
            )
            .order_by(UserNoteModel.created_at)
        )
        return [_note_to_dict(n) for n in result.scalars().all()]


async def get_notes_by_course(
    course_id: int,
    user_id: int,
    unit_ids: List[int],
    lesson_ids: List[int],
) -> List[Dict[str, Any]]:
    """Return all notes for a user scoped to a course's units and lessons."""
    async with AsyncSession(engine) as session:
        from sqlalchemy import or_

        result = await session.execute(
            select(UserNoteModel)
            .where(
                UserNoteModel.user_id == user_id,
                or_(
                    UserNoteModel.unit_id.in_(unit_ids) if unit_ids else False,
                    UserNoteModel.lesson_id.in_(lesson_ids) if lesson_ids else False,
                ),
            )
            .order_by(UserNoteModel.created_at)
        )
        return [_note_to_dict(n) for n in result.scalars().all()]


async def has_notes_for_unit(unit_id: int, user_id: int) -> bool:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(
                exists().where(
                    UserNoteModel.unit_id == unit_id,
                    UserNoteModel.user_id == user_id,
                )
            )
        )
        return bool(result.scalar())


async def has_notes_for_lessons(lesson_ids: List[int], user_id: int) -> Dict[int, bool]:
    """Return a mapping of lesson_id → bool for whether the user has notes."""
    if not lesson_ids:
        return {}
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserNoteModel.lesson_id)
            .where(
                UserNoteModel.lesson_id.in_(lesson_ids),
                UserNoteModel.user_id == user_id,
            )
            .distinct()
        )
        ids_with_notes = {row[0] for row in result.all()}
        return {lid: lid in ids_with_notes for lid in lesson_ids}
