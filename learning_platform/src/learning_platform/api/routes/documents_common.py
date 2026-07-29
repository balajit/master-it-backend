"""Shared document-route models and helpers."""

from __future__ import annotations

import inspect
import logging
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.api.schemas import DocumentTreeNodeResponse
from learning_platform.models.document import DocumentNode
from learning_platform.security import InvalidPathError, resolve_safe_path

logger = logging.getLogger(__name__)

_OWNER_MARKER_FILENAME = ".owner_sub"


def _get_documents_module() -> Any:
    """Load the documents aggregator module for compatibility lookups."""
    from learning_platform.api.routes import documents as documents_routes

    return documents_routes


def get_path_class() -> type[Path]:
    """Return the path class used by document routes."""
    documents_routes = _get_documents_module()
    return documents_routes.Path


def get_document_repository_class() -> Any:
    """Return the document repository class used by document routes."""
    documents_routes = _get_documents_module()
    return documents_routes.DocumentRepository


def get_learning_unit_repository_class() -> Any:
    """Return the learning-unit repository class used by document routes."""
    documents_routes = _get_documents_module()
    return documents_routes.LearningUnitRepository


def get_concept_repository_class() -> Any:
    """Return the concept repository class used by document routes."""
    documents_routes = _get_documents_module()
    return documents_routes.ConceptRepository


def get_study_plan_repository_class() -> Any:
    """Return the study-plan repository class used by document routes."""
    documents_routes = _get_documents_module()
    return documents_routes.StudyPlanRepository


def build_tree_node(node: DocumentNode) -> DocumentTreeNodeResponse:
    """Recursively build a tree response from a DocumentNode."""
    content = node.content
    content_type = content.type
    title = ""
    text = ""

    if hasattr(content, "level"):
        title = content_type
    if hasattr(content, "text") and hasattr(content.text, "plain_text"):
        text = content.text.plain_text
    elif hasattr(content, "code"):
        text = content.code[:200]
    elif hasattr(content, "latex"):
        text = content.latex[:200]
    elif hasattr(content, "term"):
        title = content.term
        text = content.definition

    return DocumentTreeNodeResponse(
        id=node.id,
        type=content_type,
        page=node.page,
        level=node.level,
        title=title,
        text=text[:500] if text else "",
        children=[build_tree_node(child) for child in node.children],
    )


def user_subject(user: dict[str, Any]) -> str:
    """Return a stable user subject identifier for ownership checks."""
    sub = user.get("sub")
    if isinstance(sub, str) and sub:
        return sub
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid user identity")
    return str(user_id)


def owner_marker_path(upload_dir: Path) -> Path:
    """Return the owner marker file path under an upload directory."""
    return upload_dir / _OWNER_MARKER_FILENAME


def read_upload_owner_sub(upload_dir: Path) -> str | None:
    """Read owner subject from upload marker file, if present."""
    marker_path = owner_marker_path(upload_dir)
    if not marker_path.exists():
        return None
    owner_sub = marker_path.read_text(encoding="utf-8").strip()
    return owner_sub or None


def write_upload_owner_sub(upload_dir: Path, owner_sub: str) -> None:
    """Persist owner subject marker for a newly uploaded document."""
    marker_path = owner_marker_path(upload_dir)
    marker_path.write_text(owner_sub, encoding="utf-8")


def copy_upload_file(src_file: Any, destination: Path) -> None:
    """Copy uploaded file object to destination path."""
    with destination.open("wb") as file_handle:
        shutil.copyfileobj(src_file, file_handle)


def resolve_uploaded_source(upload_dir: Path, doc_id: UUID) -> Path:
    """Return the first safe uploaded file path for the given document."""
    safe_candidates: list[Path] = []
    for file_path in upload_dir.iterdir():
        if not file_path.is_file() or file_path.name == _OWNER_MARKER_FILENAME:
            continue
        try:
            resolved = resolve_safe_path(upload_dir, file_path.name)
        except InvalidPathError:
            logger.warning(
                "Skipping unsafe file entry in upload dir for doc_id=%s: %s",
                doc_id,
                file_path,
            )
            continue
        if resolved.is_file():
            safe_candidates.append(resolved)

    if not safe_candidates:
        raise HTTPException(status_code=404, detail=f"No uploaded file found for {doc_id}")

    return safe_candidates[0]


def authorize_upload_owner(upload_dir: Path, user: dict[str, Any]) -> None:
    """Authorize access to a pre-processed upload directory."""
    owner_sub = read_upload_owner_sub(upload_dir)
    if owner_sub is None:
        return
    if owner_sub != user_subject(user):
        raise HTTPException(status_code=403, detail="Forbidden")


async def authorize_persisted_document_owner(
    session: AsyncSession,
    doc_id: UUID,
    user: dict[str, Any],
) -> None:
    """Authorize access to a persisted document by owner."""
    repo_class = get_document_repository_class()
    repo = repo_class(session)
    maybe_row = repo.find_by_id(doc_id)
    if inspect.isawaitable(maybe_row):
        row = await maybe_row
    else:
        row = None
    if row is None:
        return
    owner_sub = getattr(row, "owner_sub", None)
    if not isinstance(owner_sub, str) or not owner_sub:
        return
    if owner_sub != user_subject(user):
        raise HTTPException(status_code=403, detail="Forbidden")
