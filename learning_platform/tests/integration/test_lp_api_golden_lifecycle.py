"""Golden lifecycle integration test for LP document APIs.

This test certifies the real in-process service path:
upload -> process -> study-plan.

Certification assertion:
- every deterministic marker in ``test_pipeline_e2e.pdf`` (E001..E032)
  must be represented by at least one lesson returned by
  ``GET /api/documents/{doc_id}/study-plan`` via lesson ``unit_id`` coverage.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from learning_platform.api.app import create_app
from learning_platform.api.auth import get_current_user
from learning_platform.api.deps import get_session
from learning_platform.cache import pipeline_cache
from learning_platform.config import Settings
from learning_platform.infrastructure.persistence.models import Base
from learning_platform.models.document import CanonicalDocument
from learning_platform.models.learning_unit import LearningUnit, UnitType
from tests.integration.test_pipeline_e2e_book_order import (
    EXPECTED_SEQUENCE,
    _ensure_test_pipeline_e2e_pdf,
    _flatten_nodes,
    _node_fragments,
)

MARKER_RE: re.Pattern[str] = re.compile(r"\bE\d{3}_[A-Z0-9_]+\b")
EXPECTED_MARKERS: list[str] = [element.marker for element in EXPECTED_SEQUENCE]
EXPECTED_MARKER_INDEX: dict[str, int] = {
    marker: index for index, marker in enumerate(EXPECTED_MARKERS)
}


@pytest.fixture(autouse=True)
def clear_pipeline_cache() -> Generator[None, None, None]:
    pipeline_cache.clear()
    yield
    pipeline_cache.clear()


@pytest.fixture()
def golden_pdf_path() -> Path:
    return _ensure_test_pipeline_e2e_pdf()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    db_path = tmp_path / "lp_api_golden_lifecycle.sqlite3"
    upload_path = tmp_path / "uploads"
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{db_path}",
        upload_path=str(upload_path),
        debug=True,
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="test-jwt-secret",
    )


@pytest.fixture()
async def session_factory(
    settings: Settings,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture()
def app(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "email": "golden-lifecycle@example.com",
    }

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = _session_override
    return application


def _assert_expected_markers(marker_to_node_id: dict[str, UUID]) -> None:
    observed = set(marker_to_node_id.keys())
    expected = set(EXPECTED_MARKERS)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    assert observed == expected, f"marker set mismatch: missing={missing} extra={extra}"


def _collect_marker_node_ids(document: CanonicalDocument) -> dict[str, UUID]:
    marker_to_node_id: dict[str, UUID] = {}
    for node in _flatten_nodes(document):
        fragments = _node_fragments(node)
        for fragment in fragments:
            for marker_match in MARKER_RE.finditer(fragment or ""):
                marker = marker_match.group(0)
                previous_node_id = marker_to_node_id.get(marker)
                assert previous_node_id in {None, node.id}, (
                    f"marker {marker} appears in multiple nodes: {previous_node_id} and {node.id}"
                )
                marker_to_node_id[marker] = node.id
    return marker_to_node_id


def _unit_specificity_rank(unit_type: UnitType) -> int:
    if unit_type == UnitType.TOPIC:
        return 3
    if unit_type == UnitType.LESSON:
        return 2
    if unit_type == UnitType.MODULE:
        return 1
    return 0


def _select_unit_for_marker_node(node_id: UUID, units: list[LearningUnit]) -> UUID:
    candidates = [unit for unit in units if node_id in set(unit.source_node_ids)]
    assert candidates, f"no learning unit references marker node {node_id}"
    candidates.sort(key=lambda unit: (-_unit_specificity_rank(unit.unit_type), str(unit.id)))
    return candidates[0].id


def _build_marker_unit_ids(
    marker_to_node_id: dict[str, UUID],
    units: list[LearningUnit],
) -> dict[str, UUID]:
    marker_to_unit_id: dict[str, UUID] = {}
    for marker in EXPECTED_MARKERS:
        node_id = marker_to_node_id[marker]
        marker_to_unit_id[marker] = _select_unit_for_marker_node(node_id, units)
    return marker_to_unit_id


def _assert_study_plan_lesson_marker_coverage(
    study_plan_payload: dict[str, Any],
    marker_to_unit_id: dict[str, UUID],
) -> None:
    lessons_raw = study_plan_payload.get("lessons")
    assert isinstance(lessons_raw, list), "study-plan lessons must be a list"

    lesson_unit_ids: set[str] = set()
    for lesson in lessons_raw:
        assert isinstance(lesson, dict), "each lesson payload must be an object"
        unit_id = lesson.get("unit_id")
        assert isinstance(unit_id, str) and unit_id.strip(), "lesson.unit_id must be a UUID string"
        lesson_unit_ids.add(unit_id)

    missing_markers = [
        marker
        for marker in EXPECTED_MARKERS
        if str(marker_to_unit_id[marker]) not in lesson_unit_ids
    ]
    assert not missing_markers, f"study-plan lesson coverage is missing markers: {missing_markers}"

    markers_by_unit_id: dict[str, list[str]] = defaultdict(list)
    for marker, unit_id in marker_to_unit_id.items():
        markers_by_unit_id[str(unit_id)].append(marker)

    lessons_without_markers: list[str] = []
    for lesson in lessons_raw:
        unit_id = str(lesson["unit_id"])
        if not markers_by_unit_id.get(unit_id):
            lessons_without_markers.append(str(lesson.get("title", "")))
    assert not lessons_without_markers, (
        f"study-plan contains lesson(s) with no mapped source markers: {lessons_without_markers}"
    )

    ordered_lessons = sorted(
        (lesson for lesson in lessons_raw if isinstance(lesson, dict)),
        key=lambda lesson: int(lesson.get("order", 0)),
    )
    covered_markers: list[str] = []
    for lesson in ordered_lessons:
        unit_id = str(lesson["unit_id"])
        unit_markers = markers_by_unit_id.get(unit_id, [])
        unit_markers_sorted = sorted(
            unit_markers, key=lambda marker: EXPECTED_MARKER_INDEX[marker]
        )
        covered_markers.extend(unit_markers_sorted)

    unique_covered_markers = sorted(
        set(covered_markers),
        key=lambda marker: EXPECTED_MARKER_INDEX[marker],
    )
    assert unique_covered_markers == EXPECTED_MARKERS, (
        "study-plan marker coverage mismatch. "
        f"expected={EXPECTED_MARKERS} observed={unique_covered_markers}"
    )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_golden_lifecycle_upload_process_study_plan_marker_coverage(
    app: FastAPI,
    golden_pdf_path: Path,
) -> None:
    pdf_bytes = golden_pdf_path.read_bytes()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=300.0,
    ) as client:
        upload_response = await client.post(
            "/api/documents/upload",
            files={"file": (golden_pdf_path.name, pdf_bytes, "application/pdf")},
        )
        assert upload_response.status_code == 201, upload_response.text
        upload_payload = upload_response.json()
        doc_id = str(upload_payload["doc_id"])
        assert upload_payload["filename"] == golden_pdf_path.name

        process_response = await client.post(f"/api/documents/{doc_id}/process")
        assert process_response.status_code == 200, process_response.text
        process_payload = process_response.json()
        assert process_payload["doc_id"] == doc_id
        assert int(process_payload["lessons"]) > 0
        assert int(process_payload["milestones"]) > 0

        study_plan_response = await client.get(f"/api/documents/{doc_id}/study-plan")
        assert study_plan_response.status_code == 200, study_plan_response.text
        study_plan_payload = study_plan_response.json()

        tree_response = await client.get(f"/api/documents/{doc_id}/tree")
        assert tree_response.status_code == 200, tree_response.text
        tree_payload = tree_response.json()

    assert study_plan_payload["doc_id"] == doc_id
    assert study_plan_payload["total_lessons"] == process_payload["lessons"]
    assert len(study_plan_payload["lessons"]) == study_plan_payload["total_lessons"]
    assert len(study_plan_payload["milestones"]) == process_payload["milestones"]
    assert len(study_plan_payload["checkpoints"]) == len(study_plan_payload["milestones"])

    cached_result = pipeline_cache.get(doc_id)
    assert cached_result is not None, f"pipeline_cache missing result for doc_id={doc_id}"

    marker_to_node_id = _collect_marker_node_ids(cached_result.document)
    _assert_expected_markers(marker_to_node_id)

    marker_to_unit_id = _build_marker_unit_ids(marker_to_node_id, cached_result.units)
    _assert_study_plan_lesson_marker_coverage(study_plan_payload, marker_to_unit_id)

    # ── Image processing verification ────────────────────────────────────────
    # The test PDF contains a figure (1×1 PNG) on page 2.
    # Assert that the document tree flags has_images and each figure node
    # carries a non-empty image_url pointing to the image endpoint.
    assert tree_payload["has_images"] is True, (
        "Document tree must report has_images=True for the test PDF which contains a figure"
    )

    def _collect_figure_nodes(node: dict) -> list[dict]:
        result = []
        if node.get("type") == "figure":
            result.append(node)
        for child in node.get("children", []):
            result.extend(_collect_figure_nodes(child))
        return result

    root_node = tree_payload.get("root")
    assert root_node is not None, "Document tree must have a root node"
    figure_nodes = _collect_figure_nodes(root_node)
    assert figure_nodes, "Document tree must contain at least one node with type='figure'"
    figure_nodes_with_url = [n for n in figure_nodes if n.get("image_url", "")]
    assert figure_nodes_with_url, (
        f"At least one figure node must have a non-empty image_url; "
        f"found {len(figure_nodes)} figure node(s), none had image_url set. "
        "Check FIGURE_IMAGE_INLINE setting or DocumentImageRepository."
    )
    expected_url_prefix = f"/api/documents/{doc_id}/nodes/"
    for figure_node in figure_nodes_with_url:
        assert figure_node["image_url"].startswith(expected_url_prefix), (
            f"image_url {figure_node['image_url']!r} must start with {expected_url_prefix!r}"
        )
        assert figure_node["image_url"].endswith("/image"), (
            f"image_url {figure_node['image_url']!r} must end with '/image'"
        )
