"""Tree/index building helpers for learning experience mapping."""

from __future__ import annotations

from uuid import UUID

from learning_platform.models.learning_unit import LearningUnit, UnitType
from learning_platform.models.page_context import PageContext


class LearningExperienceIndicesMixin:
    """Builds and serves memoized indices over learning units."""

    _units_by_id: dict[UUID, LearningUnit]
    _unit_ids_by_type: dict[UnitType, list[UUID]]
    _descendant_ids: dict[UUID, set[UUID]]
    _lesson_counts: dict[UUID, int]
    _exercise_counts: dict[UUID, int]
    _lesson_ids: dict[UUID, set[UUID]]
    _page_ranges: dict[UUID, tuple[int, int]]
    _section_ids: dict[UUID, UUID]
    _exercises_index: dict[UUID, list[tuple[UUID, str]]]

    def _build_indices(self, units: list[LearningUnit]) -> None:
        """Build internal lookup indices from the list of units."""
        self._units_by_id = {unit.id: unit for unit in units}
        self._unit_ids_by_type = {}
        for unit in units:
            self._unit_ids_by_type.setdefault(unit.unit_type, []).append(unit.id)

    def _compute_memoized_indices(self, pages: list[PageContext]) -> None:
        """Pre-compute recursive tree lookups for O(1) access."""
        unit_ids = list(self._units_by_id.keys())
        for uid in unit_ids:
            unit = self._units_by_id[uid]
            self._descendant_ids[uid] = {uid}
            self._lesson_counts[uid] = 1 if unit.unit_type == UnitType.LESSON else 0
            self._exercise_counts[uid] = len(unit.exercises)
            self._lesson_ids[uid] = {uid} if unit.unit_type == UnitType.LESSON else set()
            self._exercises_index[uid] = [
                (ref.node_id, ref.summary or f"Practice {str(ref.node_id)[:8]}")
                for ref in unit.exercises
            ]

        for page in pages:
            if page.page_number == 0:
                continue
            for page_unit in page.units:
                uid = page_unit.id
                if uid not in self._units_by_id:
                    continue
                cur_s, cur_e = self._page_ranges.get(uid, (0, 0))
                if cur_s == 0:
                    self._page_ranges[uid] = (
                        page.page_number,
                        page.page_number,
                    )
                else:
                    self._page_ranges[uid] = (
                        min(cur_s, page.page_number),
                        max(cur_e, page.page_number),
                    )

        children_done: set[UUID] = set()
        remaining = set(unit_ids)
        order: list[UUID] = []

        for uid in unit_ids:
            unit = self._units_by_id[uid]
            if not unit.children_ids or all(c not in self._units_by_id for c in unit.children_ids):
                order.append(uid)
                children_done.add(uid)
                remaining.discard(uid)

        while remaining:
            progress_made = False
            for uid in list(remaining):
                unit = self._units_by_id[uid]
                if all(
                    c in children_done or c not in self._units_by_id for c in unit.children_ids
                ):
                    order.append(uid)
                    children_done.add(uid)
                    remaining.discard(uid)
                    progress_made = True
            if not progress_made:
                order.extend(remaining)
                break

        for uid in order:
            unit = self._units_by_id.get(uid)
            if unit is None:
                continue
            for child_id in unit.children_ids:
                if child_id not in self._units_by_id:
                    continue
                self._descendant_ids[uid].update(
                    self._descendant_ids[child_id],
                )
                self._lesson_counts[uid] += self._lesson_counts[child_id]
                self._exercise_counts[uid] += self._exercise_counts[child_id]
                self._lesson_ids[uid].update(self._lesson_ids[child_id])
                self._exercises_index[uid].extend(
                    self._exercises_index[child_id],
                )

                child_range = self._page_ranges.get(child_id)
                if child_range is not None:
                    s, e = child_range
                    if s > 0:
                        cur_s, cur_e = self._page_ranges.get(uid, (0, 0))
                        if cur_s == 0:
                            self._page_ranges[uid] = (s, e)
                        else:
                            self._page_ranges[uid] = (
                                min(cur_s, s),
                                max(cur_e, e),
                            )

        root = self._find_root_unit(list(self._units_by_id.values()))
        if root is not None:
            self._section_ids[root.id] = root.id
            queue = list(root.children_ids)
            while queue:
                cid = queue.pop(0)
                unit = self._units_by_id.get(cid)
                if unit is None:
                    continue
                if unit.unit_type == UnitType.MODULE:
                    self._section_ids[cid] = cid
                else:
                    if unit.parent_id is None:
                        self._section_ids[cid] = cid
                    else:
                        self._section_ids[cid] = self._section_ids.get(
                            unit.parent_id,
                            cid,
                        )
                queue.extend(unit.children_ids)

    def _find_root_unit(self, units: list[LearningUnit]) -> LearningUnit | None:
        """Find the root COURSE-level unit."""
        for unit in units:
            if unit.unit_type == UnitType.COURSE and unit.parent_id is None:
                return unit
        return None

    def _get_children(self, unit_id: UUID) -> list[LearningUnit]:
        """Get child units for a given unit, in order."""
        unit = self._units_by_id.get(unit_id)
        if unit is None:
            return []
        return [
            self._units_by_id[child_id]
            for child_id in unit.children_ids
            if child_id in self._units_by_id
        ]
