from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import engine
from database.models import CourseDocumentModel, DocumentModel


async def create_document(
    doc_id: str,
    filename: str,
    storage_path: str,
    content_type: str,
    size_bytes: int,
) -> Dict[str, Any]:
    from datetime import datetime, timezone

    now: str = datetime.now(timezone.utc).isoformat()
    async with AsyncSession(engine) as session:
        doc = DocumentModel(
            id=doc_id,
            filename=filename,
            storage_path=storage_path,
            content_type=content_type,
            size_bytes=size_bytes,
            created_at=now,
        )
        session.add(doc)
        await session.commit()
        return {
            "id": doc_id,
            "filename": filename,
            "storage_path": storage_path,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "created_at": now,
        }


async def attach_document_to_course(course_id: int, document_id: str) -> None:
    async with AsyncSession(engine) as session:
        await session.execute(
            insert(CourseDocumentModel).values(
                course_id=course_id, document_id=document_id
            )
        )
        await session.commit()


async def get_document(document_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        doc: Optional[DocumentModel] = (
            (
                await session.execute(
                    select(DocumentModel).where(DocumentModel.id == document_id)
                )
            )
            .scalars()
            .first()
        )
        if not doc:
            return None
        return {
            "id": doc.id,
            "filename": doc.filename,
            "storage_path": doc.storage_path,
            "content_type": doc.content_type,
            "size_bytes": doc.size_bytes,
            "created_at": doc.created_at,
        }


async def get_course_documents(course_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        docs: List[DocumentModel] = (
            (
                await session.execute(
                    select(DocumentModel)
                    .join(
                        CourseDocumentModel,
                        DocumentModel.id == CourseDocumentModel.document_id,
                    )
                    .where(CourseDocumentModel.course_id == course_id)
                    .order_by(DocumentModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": d.id,
                "filename": d.filename,
                "storage_path": d.storage_path,
                "content_type": d.content_type,
                "size_bytes": d.size_bytes,
                "created_at": d.created_at,
            }
            for d in docs
        ]


async def delete_document(document_id: str) -> bool:
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(CourseDocumentModel).where(
                CourseDocumentModel.document_id == document_id
            )
        )
        result = await session.execute(
            delete(DocumentModel).where(DocumentModel.id == document_id)
        )
        await session.commit()
        return result.rowcount > 0


async def get_documents_by_course(course_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        docs: List[DocumentModel] = (
            (
                await session.execute(
                    select(DocumentModel)
                    .join(
                        CourseDocumentModel,
                        DocumentModel.id == CourseDocumentModel.document_id,
                    )
                    .where(CourseDocumentModel.course_id == course_id)
                    .order_by(DocumentModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": d.id,
                "filename": d.filename,
                "storage_path": d.storage_path,
                "content_type": d.content_type,
                "size_bytes": d.size_bytes,
                "created_at": d.created_at,
            }
            for d in docs
        ]
