"""Tests for strict enrollment source document resolution."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from services.enrollment import _resolve_source_document_lp_uuid


class TestResolveSourceDocumentLpUuid:
    def test_accepts_lp_uuid(self) -> None:
        source_document_id = "8b3f8683-d93d-f16c-0243-e02cf35d0c82"

        async def _run() -> UUID:
            return await _resolve_source_document_lp_uuid(source_document_id)

        resolved = asyncio.run(_run())
        assert resolved == UUID(source_document_id)

    def test_resolves_masterit_document_id_via_storage_path(self) -> None:
        source_document_id = "122e720903b24930af4f8485c8f8f25b"
        storage_path = "uploads/1851/Chemistry-study-guide.sample-p13-15.pdf"
        expected_lp_uuid = UUID("8b3f8683-d93d-f16c-0243-e02cf35d0c82")

        async def _run() -> UUID:
            with (
                patch(
                    "services.enrollment.get_document",
                    new_callable=AsyncMock,
                    return_value={
                        "id": source_document_id,
                        "storage_path": storage_path,
                    },
                ) as get_document_mock,
                patch(
                    "services.enrollment.lp_doc_uuid_from_storage_path",
                    return_value=expected_lp_uuid,
                ) as storage_to_lp_mock,
            ):
                resolved = await _resolve_source_document_lp_uuid(source_document_id)

            get_document_mock.assert_awaited_once_with(source_document_id)
            storage_to_lp_mock.assert_called_once_with(storage_path)
            return resolved

        resolved = asyncio.run(_run())
        assert resolved == expected_lp_uuid

    def test_rejects_unknown_document_id(self) -> None:
        source_document_id = "not-a-real-document"

        async def _run() -> None:
            with patch(
                "services.enrollment.get_document",
                new_callable=AsyncMock,
                return_value=None,
            ):
                await _resolve_source_document_lp_uuid(source_document_id)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_run())

        assert exc_info.value.status_code == 409
        assert "Invalid source_document_id" in str(exc_info.value.detail)

    def test_rejects_document_without_storage_path(self) -> None:
        source_document_id = "122e720903b24930af4f8485c8f8f25b"

        async def _run() -> None:
            with patch(
                "services.enrollment.get_document",
                new_callable=AsyncMock,
                return_value={"id": source_document_id, "storage_path": "   "},
            ):
                await _resolve_source_document_lp_uuid(source_document_id)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_run())

        assert exc_info.value.status_code == 409
        assert "no storage path" in str(exc_info.value.detail)
