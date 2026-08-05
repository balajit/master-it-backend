"""Unit tests for image extraction pipeline: BridgeNode → Figure → DocumentImageRepository."""

from __future__ import annotations

import base64
import io
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from learning_platform.api.routes.documents_common import _has_figure_nodes, build_tree_node
from learning_platform.infrastructure.persistence.models.document_image import DocumentImageRow
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Figure,
    Heading,
    HeadingLevel,
    Paragraph,
    StyledText,
    TextRun,
)
from learning_platform.stages.parser2.docling_node_mapper import _map_bridge_node
from learning_platform.stages.parser2.docling_pymupdf_merger import BridgeNode


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_pil_image(width: int = 8, height: int = 8, fmt: str = "PNG") -> Any:
    """Return a minimal PIL Image object without requiring a real image file."""
    try:
        from PIL import Image  # noqa: PLC0415

        img = Image.new("RGB", (width, height), color=(255, 0, 0))
        img.format = fmt
        return img
    except ImportError:
        pytest.skip("Pillow not installed")


def _make_figure_node(with_image: bool = True) -> DocumentNode:
    """Build a DocumentNode with Figure content, optionally with image_base64."""
    figure = Figure(
        caption_text="Test caption",
        format="PNG",
        mimetype="image/png",
        width=8.0,
        height=8.0,
    )
    if with_image:
        # Use real PNG bytes for a 1x1 red image
        buf = io.BytesIO()
        try:
            from PIL import Image  # noqa: PLC0415

            Image.new("RGB", (1, 1), color=(255, 0, 0)).save(buf, format="PNG")
            figure.image_base64 = buf.getvalue()
        except ImportError:
            figure.image_base64 = b"\x89PNG\r\n"  # minimal fake bytes

    return DocumentNode(id=uuid.uuid4(), content=figure)


def _make_text_node(text: str = "hello") -> DocumentNode:
    return DocumentNode(
        id=uuid.uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
    )


# ── BridgeNode image fields ───────────────────────────────────────────────────


class TestBridgeNodeImageFields:
    def test_default_fields_are_falsy(self) -> None:
        node = BridgeNode(label="picture", name="PictureItem")
        assert node.is_image is False
        assert node.image_pil is None
        assert node.image_format is None
        assert node.image_width is None
        assert node.image_height is None

    def test_fields_can_be_set(self) -> None:
        mock_pil = MagicMock()
        node = BridgeNode(
            label="picture",
            name="PictureItem",
            is_image=True,
            image_pil=mock_pil,
            image_format="PNG",
            image_width=100,
            image_height=200,
        )
        assert node.is_image is True
        assert node.image_pil is mock_pil
        assert node.image_format == "PNG"
        assert node.image_width == 100
        assert node.image_height == 200


# ── _process_image_item ───────────────────────────────────────────────────────


class TestProcessImageItem:
    def _make_merger_stub(self) -> Any:
        """Return a minimal DoclingPyMuPDFMerger-like object without running Docling."""
        from learning_platform.stages.parser2.docling_pymupdf_merger import (  # noqa: PLC0415
            DoclingPyMuPDFMerger,
        )

        merger = object.__new__(DoclingPyMuPDFMerger)
        merger.docling_doc = MagicMock()
        merger.fitz_doc = None
        merger.page_style_caches = {}
        merger.ref_to_node = {}
        merger.nodes_by_id = {}
        merger.body_ref = "#/body"
        merger.source = "test.pdf"
        merger._is_pdf = False
        return merger

    def test_no_image_when_item_has_no_image(self) -> None:
        merger = self._make_merger_stub()
        node = BridgeNode(label="PICTURE", name="PictureItem")
        doc_item = MagicMock(spec=[])  # no get_image, no image attr

        merger._process_image_item(node, doc_item)

        assert node.is_image is False
        assert node.image_pil is None

    def test_image_extracted_from_get_image(self) -> None:
        merger = self._make_merger_stub()
        node = BridgeNode(label="PICTURE", name="PictureItem")
        mock_pil = _make_pil_image()

        doc_item = MagicMock()
        doc_item.get_image.return_value = mock_pil

        merger._process_image_item(node, doc_item)

        assert node.is_image is True
        assert node.image_pil is mock_pil
        assert node.image_format in {"PNG", "JPEG", "WEBP"}
        assert node.image_width == mock_pil.width
        assert node.image_height == mock_pil.height

    def test_image_extracted_from_image_attribute_fallback(self) -> None:
        merger = self._make_merger_stub()
        node = BridgeNode(label="FIGURE", name="PictureItem")
        mock_pil = _make_pil_image()

        doc_item = MagicMock(spec=["image"])
        doc_item.image = mock_pil

        merger._process_image_item(node, doc_item)

        assert node.is_image is True
        assert node.image_pil is mock_pil

    def test_unknown_format_defaults_to_png(self) -> None:
        merger = self._make_merger_stub()
        node = BridgeNode(label="PICTURE", name="PictureItem")
        mock_pil = MagicMock()
        mock_pil.width = 64
        mock_pil.height = 64
        mock_pil.format = "BMP"  # unsupported format
        doc_item = MagicMock()
        doc_item.get_image.return_value = mock_pil

        merger._process_image_item(node, doc_item)

        assert node.image_format == "PNG"


# ── docling_node_mapper Figure population ────────────────────────────────────


class TestDoclingNodeMapperFigure:
    def test_figure_with_pil_image_populates_image_base64(self) -> None:
        pil_img = _make_pil_image()
        node = BridgeNode(
            label="picture",
            name="PictureItem",
            is_image=True,
            image_pil=pil_img,
            image_format="PNG",
            image_width=pil_img.width,
            image_height=pil_img.height,
        )
        doc_node = _map_bridge_node(node, source="test.pdf")

        assert isinstance(doc_node.content, Figure)
        assert doc_node.content.image_base64 is not None
        assert isinstance(doc_node.content.image_base64, bytes)
        assert len(doc_node.content.image_base64) > 0
        assert doc_node.content.format == "PNG"
        assert doc_node.content.mimetype == "image/png"
        assert doc_node.content.width == float(pil_img.width)
        assert doc_node.content.height == float(pil_img.height)

    def test_figure_without_pil_image_has_no_image_base64(self) -> None:
        node = BridgeNode(label="picture", name="PictureItem", text="A figure")
        doc_node = _map_bridge_node(node, source="test.pdf")

        assert isinstance(doc_node.content, Figure)
        assert doc_node.content.image_base64 is None


# ── DocumentImageRepository ──────────────────────────────────────────────────


class TestDocumentImageRepository:
    @pytest.mark.asyncio
    async def test_save_for_document_inserts_rows_for_figures(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_image import (  # noqa: PLC0415
            DocumentImageRepository,
        )

        session = AsyncMock()
        session.execute = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        session.execute.return_value = result_mock
        session.add = MagicMock()
        session.flush = AsyncMock()

        doc_id = uuid.uuid4()
        figure_node = _make_figure_node(with_image=True)
        text_node = _make_text_node()
        # nest figure_node as child
        text_node.children.append(figure_node)

        repo = DocumentImageRepository(session)
        count = await repo.save_for_document(doc_id, [text_node])

        assert count == 1
        session.add.assert_called_once()
        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_for_document_skips_nodes_without_image(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_image import (  # noqa: PLC0415
            DocumentImageRepository,
        )

        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        doc_id = uuid.uuid4()
        nodes = [_make_figure_node(with_image=False), _make_text_node()]

        repo = DocumentImageRepository(session)
        count = await repo.save_for_document(doc_id, nodes)

        assert count == 0
        session.add.assert_not_called()
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_hydrate_document_images_populates_figure_base64(self) -> None:
        from learning_platform.infrastructure.persistence.models.document_image import (  # noqa: PLC0415
            DocumentImageRow,
        )
        from learning_platform.infrastructure.persistence.repositories.document_image import (  # noqa: PLC0415
            DocumentImageRepository,
        )

        doc_id = uuid.uuid4()
        figure_node = _make_figure_node(with_image=False)  # no image_base64 yet
        assert figure_node.content.image_base64 is None  # sanity

        fake_bytes = b"\x89PNG\r\nfakepng"
        fake_row = DocumentImageRow(
            document_id=doc_id,
            node_id=figure_node.id,
            image_format="PNG",
            image_data=fake_bytes,
        )

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [fake_row]
        session.execute = AsyncMock(return_value=result_mock)

        repo = DocumentImageRepository(session)
        count = await repo.hydrate_document_images(doc_id, [figure_node])

        assert count == 1
        assert figure_node.content.image_base64 == fake_bytes

    @pytest.mark.asyncio
    async def test_hydrate_document_images_skips_missing_rows(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_image import (  # noqa: PLC0415
            DocumentImageRepository,
        )

        doc_id = uuid.uuid4()
        figure_node = _make_figure_node(with_image=False)

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []  # no rows for this doc
        session.execute = AsyncMock(return_value=result_mock)

        repo = DocumentImageRepository(session)
        count = await repo.hydrate_document_images(doc_id, [figure_node])

        assert count == 0
        assert figure_node.content.image_base64 is None  # unchanged

    @pytest.mark.asyncio
    async def test_find_by_node_id_returns_none_when_not_found(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_image import (  # noqa: PLC0415
            DocumentImageRepository,
        )

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        repo = DocumentImageRepository(session)
        result = await repo.find_by_node_id(uuid.uuid4())

        assert result is None


# ── DocumentRepository._serialize_nodes strips image_base64 ─────────────────


class TestDocumentRepositorySerialize:
    def test_serialize_nodes_strips_image_base64_nested(self) -> None:
        """image_base64 must be stripped from figure nodes at any depth."""
        from learning_platform.infrastructure.persistence.repositories.document import (  # noqa: PLC0415
            DocumentRepository,
        )

        root = _make_text_node("root")
        child = _make_text_node("child")
        grandchild = _make_figure_node(with_image=True)
        child.children.append(grandchild)
        root.children.append(child)

        assert grandchild.content.image_base64 is not None  # sanity

        serialized = DocumentRepository._serialize_nodes([root])
        assert len(serialized) == 1

        # Navigate to the nested figure node in the serialized dict
        child_dict = serialized[0]["children"][0]
        grandchild_dict = child_dict["children"][0]
        assert grandchild_dict["content"]["type"] == "figure"
        assert "image_base64" not in grandchild_dict["content"]

    def test_serialize_nodes_strips_image_base64(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.document import (  # noqa: PLC0415
            DocumentRepository,
        )

        figure_node = _make_figure_node(with_image=True)
        assert figure_node.content.image_base64 is not None  # sanity

        serialized = DocumentRepository._serialize_nodes([figure_node])
        assert len(serialized) == 1
        content = serialized[0]["content"]
        assert isinstance(content, dict)
        assert "image_base64" not in content

    def test_serialize_nodes_preserves_other_figure_fields(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.document import (  # noqa: PLC0415
            DocumentRepository,
        )

        figure_node = _make_figure_node(with_image=True)
        figure_node.content.caption_text = "Test caption"
        figure_node.content.format = "PNG"

        serialized = DocumentRepository._serialize_nodes([figure_node])
        content = serialized[0]["content"]
        assert content["caption_text"] == "Test caption"
        assert content["format"] == "PNG"
        assert content["type"] == "figure"


# ── _has_figure_nodes ─────────────────────────────────────────────────────────


class TestHasFigureNodes:
    def test_returns_false_for_non_figure_tree(self) -> None:
        root = _make_text_node()
        root.children.append(_make_text_node())
        assert _has_figure_nodes(root) is False

    def test_returns_true_when_root_is_figure(self) -> None:
        assert _has_figure_nodes(_make_figure_node()) is True

    def test_returns_true_when_figure_is_nested(self) -> None:
        root = _make_text_node()
        child = _make_text_node()
        child.children.append(_make_figure_node())
        root.children.append(child)
        assert _has_figure_nodes(root) is True


# ── build_tree_node image_url / image_data ────────────────────────────────────


class TestBuildTreeNodeImages:
    def test_non_figure_has_empty_image_fields(self) -> None:
        node = _make_text_node("hello")
        resp = build_tree_node(node, doc_id=uuid.uuid4())
        assert resp.image_url == ""
        assert resp.image_data == ""

    def test_figure_default_mode_returns_image_url(self) -> None:
        doc_id = uuid.uuid4()
        node = _make_figure_node()
        resp = build_tree_node(node, doc_id=doc_id, figure_image_inline=False)
        assert f"/api/documents/{doc_id}/nodes/{node.id}/image" == resp.image_url
        assert resp.image_data == ""

    def test_figure_inline_mode_returns_image_data(self) -> None:
        node = _make_figure_node(with_image=True)
        resp = build_tree_node(node, doc_id=uuid.uuid4(), figure_image_inline=True)
        assert resp.image_url == ""
        assert resp.image_data != ""
        # Verify it's valid base64
        decoded = base64.b64decode(resp.image_data)
        assert len(decoded) > 0

    def test_figure_inline_mode_empty_when_no_bytes(self) -> None:
        node = _make_figure_node(with_image=False)
        resp = build_tree_node(node, doc_id=uuid.uuid4(), figure_image_inline=True)
        assert resp.image_data == ""

    def test_figure_url_mode_without_doc_id_returns_empty(self) -> None:
        node = _make_figure_node()
        resp = build_tree_node(node, doc_id=None, figure_image_inline=False)
        assert resp.image_url == ""


# ── BookAssembler figure → ImageItem ─────────────────────────────────────────


class TestBookAssemblerFigureToImageItem:
    def test_image_base64_bytes_become_base64_string(self) -> None:
        """Assembler correctly encodes Figure.image_base64 bytes into ImageItem.data."""
        from learning_platform.stages.book_assembler.assembler import BookAssembler  # noqa: PLC0415

        raw_bytes = b"\x89PNG\r\nFAKE"
        expected_b64 = base64.b64encode(raw_bytes).decode("ascii")

        figure = Figure(
            caption_text="fig",
            format="PNG",
            mimetype="image/png",
            image_base64=raw_bytes,
        )
        node = DocumentNode(id=uuid.uuid4(), content=figure)

        assembler = object.__new__(BookAssembler)
        result = assembler._node_to_item(node, order=0)

        assert result is not None
        assert result.type == "image"
        assert result.data == expected_b64

    def test_missing_image_base64_produces_empty_data(self) -> None:
        from learning_platform.stages.book_assembler.assembler import BookAssembler  # noqa: PLC0415

        figure = Figure(caption_text="no image", image_base64=None)
        node = DocumentNode(id=uuid.uuid4(), content=figure)

        assembler = object.__new__(BookAssembler)
        result = assembler._node_to_item(node, order=0)

        assert result is not None
        assert result.data == ""
