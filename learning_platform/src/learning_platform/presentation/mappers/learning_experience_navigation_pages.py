"""Navigation/page mapping and shared helpers for learning experience."""

from __future__ import annotations

from uuid import UUID

from learning_platform.models.learning_unit import LearningUnit, UnitType
from learning_platform.models.page_context import PageContext
from learning_platform.presentation.mappers.configuration import MappingConfiguration
from learning_platform.presentation.mappers.context import ProgressContext
from learning_platform.presentation.models import (
    CardStatus,
    NavigationNode,
    NavigationNodeType,
    PageView,
)


class LearningExperienceNavigationPagesMixin:
    """Builds navigation/page views and cross-cutting helper methods."""

    config: MappingConfiguration
    _units_by_id: dict[UUID, LearningUnit]
    _page_ranges: dict[UUID, tuple[int, int]]
    _descendant_ids: dict[UUID, set[UUID]]

    def _build_pages(
        self,
        pages: list[PageContext],
        units: list[LearningUnit],
    ) -> list[PageView]:
        """Build PageView objects from pipeline page contexts."""
        unit_lookup = {u.id: u for u in units}

        page_views: list[PageView] = []
        for page in pages:
            if page.page_number == 0:
                continue

            unit_ids: list[UUID] = []
            for unit in page.units:
                if unit.id not in unit_lookup:
                    continue
                unit_ids.append(unit.id)

            annotation_ids: list[UUID] = [ann.id for ann in page.annotations]
            concept_ids: list[UUID] = [concept.id for concept in page.concepts]
            title = page.heading or ""
            text_preview = page.page_text[:280]

            page_views.append(
                PageView(
                    page_number=page.page_number,
                    title=title,
                    text_preview=text_preview,
                    full_text=page.page_text,
                    unit_ids=unit_ids,
                    annotation_ids=annotation_ids,
                    concept_ids=concept_ids,
                )
            )

        return page_views

    def _build_navigation(
        self,
        root_unit: LearningUnit,
        progress: ProgressContext,
    ) -> list[NavigationNode]:
        """Build navigation hierarchy based on configuration."""
        nodes: list[NavigationNode] = []
        self._build_navigation_recursive(root_unit, None, nodes, progress, 0)
        return nodes

    def _build_navigation_recursive(
        self,
        unit: LearningUnit,
        parent_id: UUID | None,
        nodes: list[NavigationNode],
        progress: ProgressContext,
        depth: int,
    ) -> None:
        """Recursively build navigation nodes."""
        if (
            self.config.navigation.max_depth is not None
            and depth >= self.config.navigation.max_depth
        ):
            return

        node_type = self._map_unit_type_to_navigation_type(unit.unit_type)

        unit_progress = progress.get_unit_progress(unit.id)
        if self.config.navigation.show_status:
            card_status = (
                self.config.status_mapping.mastered
                if unit_progress.completed_items > 0
                else self.config.status_mapping.not_started
            )
        else:
            card_status = CardStatus.NOT_STARTED

        is_current = (
            self.config.navigation.highlight_current and progress.current_node_id == unit.id
        )

        node = NavigationNode(
            node_id=unit.id,
            node_type=node_type,
            title=unit.title,
            parent_id=parent_id,
            children_ids=unit.children_ids,
            unit_id=unit.id,
            order=len(nodes),
            is_current=is_current,
            is_accessible=True,
            status=card_status,
        )
        nodes.append(node)

        for child_id in unit.children_ids:
            child_unit = self._units_by_id.get(child_id)
            if child_unit:
                self._build_navigation_recursive(
                    child_unit,
                    unit.id,
                    nodes,
                    progress,
                    depth + 1,
                )

    def _find_start_page_for_unit(
        self,
        unit_id: UUID,
        pages: list[PageContext],
    ) -> int:
        """Find the first page number for a unit."""
        start, _end = self._find_page_range_for_unit(unit_id, pages)
        return start

    def _find_page_range_for_unit(
        self,
        unit_id: UUID,
        pages: list[PageContext],
    ) -> tuple[int, int]:
        """Find (start, end) page range for a unit (memoized)."""
        return self._page_ranges.get(unit_id, (0, 0))

    def _collect_descendant_ids(self, unit_id: UUID) -> set[UUID]:
        """Collect the IDs of a unit and all its descendants (memoized)."""
        return self._descendant_ids.get(unit_id, set())

    def _map_unit_type_to_navigation_type(self, unit_type: UnitType) -> NavigationNodeType:
        """Map UnitType to NavigationNodeType."""
        type_map = {
            UnitType.COURSE: NavigationNodeType.COURSE,
            UnitType.MODULE: NavigationNodeType.MODULE,
            UnitType.LESSON: NavigationNodeType.LESSON,
            UnitType.TOPIC: NavigationNodeType.TOPIC,
        }
        return type_map.get(unit_type, NavigationNodeType.TOPIC)
