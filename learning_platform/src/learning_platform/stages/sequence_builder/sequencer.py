"""Learning Sequence Builder — derives an ordered study plan from the KnowledgeGraph.

The builder performs three key operations:

1. **Topological sort** — respects prerequisite constraints by walking
   the unit-node subgraph of the knowledge graph.

2. **Difficulty balancing** — when multiple unit nodes are available
   (all prerequisites satisfied), picks the one that best balances the
   current difficulty streak so that advanced topics are not clustered.

3. **Milestone grouping** — lessons are batched into milestones.  A new
   milestone starts when the batch size is reached *or* when the
   difficulty level changes.  A ``Checkpoint`` is inserted after each
   milestone.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

from learning_platform.models.knowledge_graph import EdgeType, KnowledgeGraph, NodeType
from learning_platform.models.sequence import (
    Checkpoint,
    CheckpointType,
    Lesson,
    LessonType,
    Milestone,
    StudyPlan,
)

if TYPE_CHECKING:
    from uuid import UUID

_LOG = logging.getLogger(__name__)

_DIFFICULTY_ORDER: dict[str, int] = {
    "basic": 0,
    "intermediate": 1,
    "advanced": 2,
}

_DEFAULT_MILESTONE_SIZE = 4


class TopologicalSequenceBuilder:
    """Orders learning units via topological sort with difficulty balancing."""

    def __init__(self, milestone_size: int = _DEFAULT_MILESTONE_SIZE) -> None:
        self._milestone_size = milestone_size

    def build(self, graph: KnowledgeGraph) -> StudyPlan:
        """Produce a StudyPlan respecting prerequisite constraints."""
        _LOG.info(
            "Building study plan from graph: %d nodes, %d edges",
            len(graph.nodes),
            len(graph.edges),
        )

        # ── 1. Extract unit subgraph ───────────────────────────────────────
        unit_nodes = graph.nodes_by_type(NodeType.UNIT)
        unit_ids = {n.id for n in unit_nodes}
        id_to_node = {n.id: n for n in unit_nodes}

        # Build adjacency and in-degree for unit→unit edges only
        adj: dict[UUID, list[UUID]] = defaultdict(list)
        in_degree: dict[UUID, int] = {uid: 0 for uid in unit_ids}

        for edge in graph.edges:
            if (
                edge.source_id in unit_ids
                and edge.target_id in unit_ids
                and edge.edge_type in (EdgeType.DEPENDS_ON, EdgeType.PREREQUISITE)
            ):
                adj[edge.source_id].append(edge.target_id)
                in_degree[edge.target_id] += 1

        # ── 2. Topological sort with difficulty balancing ───────────────────
        ordered_ids = _balanced_topological_sort(unit_ids, adj, in_degree, id_to_node)

        # ── 3. Build lessons ──────────────────────────────────────────────
        lessons: list[Lesson] = []
        milestone_id: UUID | None = None

        for order, uid in enumerate(ordered_ids):
            node = id_to_node[uid]
            lesson = Lesson(
                unit_id=uid,
                order=order,
                title=node.label,
                description=node.metadata.get("description", ""),
                learning_objectives=_extract_objectives(node),
                lesson_type=_classify_lesson_type(node, order, len(ordered_ids)),
                difficulty=node.metadata.get("difficulty", "basic"),
                estimated_minutes=node.metadata.get("estimated_minutes", 0),
                milestone_id=milestone_id,
                prerequisites=_prerequisite_ids_for(uid, adj, in_degree, unit_ids),
            )
            lessons.append(lesson)

        # ── 4. Group into milestones with checkpoints ──────────────────────
        milestones, checkpoints = _group_milestones(lessons, self._milestone_size)

        # ── 5. Assign milestone IDs back to lessons ───────────────────────
        for milestone in milestones:
            for lid in milestone.lesson_ids:
                for lesson in lessons:
                    if lesson.id == lid:
                        lesson.milestone_id = milestone.id

        # ── 6. Assemble study plan ─────────────────────────────────────────
        total_minutes = sum(lesson.estimated_minutes for lesson in lessons)

        plan = StudyPlan(
            title="Study Plan",
            description=(
                f"A structured plan covering {len(lessons)} lessons "
                f"across {len(milestones)} milestones."
            ),
            lessons=lessons,
            milestones=milestones,
            checkpoints=checkpoints,
            total_estimated_minutes=total_minutes,
            total_lessons=len(lessons),
        )

        _LOG.info(
            "Study plan built: %d lessons, %d milestones, %d checkpoints, %d min",
            len(lessons),
            len(milestones),
            len(checkpoints),
            total_minutes,
        )

        return plan


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _balanced_topological_sort(
    unit_ids: set[UUID],
    adj: dict[UUID, list[UUID]],
    in_degree: dict[UUID, int],
    id_to_node: dict[UUID, Any],
) -> list[UUID]:
    """Topological sort with greedy difficulty balancing.

    When multiple nodes have in-degree 0, pick the one whose difficulty
    best breaks any existing streak of the same level.
    """
    ready = deque(uid for uid, deg in in_degree.items() if deg == 0)
    result: list[UUID] = []
    recent_difficulties: list[str] = []

    while ready:
        # Pick the best candidate from the ready queue
        if len(ready) == 1:
            chosen = ready.popleft()
        else:
            chosen = _pick_best_ready(ready, id_to_node, recent_difficulties)

        result.append(chosen)
        node = id_to_node[chosen]
        recent_difficulties.append(node.metadata.get("difficulty", "basic"))
        # Keep a sliding window of recent difficulties
        if len(recent_difficulties) > 5:
            recent_difficulties.pop(0)

        # Update in-degree for neighbours
        for neighbour in adj.get(chosen, []):
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                ready.append(neighbour)

    return result


def _pick_best_ready(
    ready: deque[UUID],
    id_to_node: dict[UUID, Any],
    recent: list[str],
) -> UUID:
    """Choose the ready node that best balances recent difficulty streak."""
    if not recent:
        return ready.popleft()

    last_difficulty = recent[-1]
    same_streak = _count_streak(recent)

    # If we have a long streak of the same difficulty, prefer a different one
    prefer_different = same_streak >= 2

    best_uid: UUID | None = None
    best_score = float("-inf")

    for uid in list(ready):
        node = id_to_node[uid]
        diff = node.metadata.get("difficulty", "basic")
        diff_rank = _DIFFICULTY_ORDER.get(diff, 0)

        # Score: penalise same difficulty if streak is long
        score = 0.0
        if prefer_different and diff == last_difficulty:
            score -= 10.0
        elif prefer_different and diff != last_difficulty:
            score += 5.0

        # Slight preference for easier topics (scaffold)
        score += (2 - diff_rank) * 0.5

        if score > best_score:
            best_score = score
            best_uid = uid

    if best_uid is not None:
        ready.remove(best_uid)
        return best_uid

    return ready.popleft()


def _count_streak(difficulties: list[str]) -> int:
    """Count how many of the last N items are the same as the final item."""
    if not difficulties:
        return 0
    last = difficulties[-1]
    count = 0
    for d in reversed(difficulties):
        if d == last:
            count += 1
        else:
            break
    return count


def _group_milestones(
    lessons: list[Lesson],
    milestone_size: int,
) -> tuple[list[Milestone], list[Checkpoint]]:
    """Batch lessons into milestones and insert checkpoints."""
    milestones: list[Milestone] = []
    checkpoints: list[Checkpoint] = []

    if not lessons:
        return milestones, checkpoints

    # Split into batches; start a new batch on difficulty change or size limit
    batches: list[list[Lesson]] = []
    current_batch: list[Lesson] = []

    for lesson in lessons:
        should_split = False
        if current_batch and len(current_batch) >= milestone_size:
            should_split = True
        elif current_batch:
            prev_diff = current_batch[-1].difficulty
            if lesson.difficulty != prev_diff and len(current_batch) >= 2:
                should_split = True

        if should_split:
            batches.append(current_batch)
            current_batch = []
        current_batch.append(lesson)

    if current_batch:
        batches.append(current_batch)

    # Create milestones and checkpoints
    for idx, batch in enumerate(batches):
        milestone = Milestone(
            order=idx,
            title=f"Milestone {idx + 1}",
            description=_describe_milestone(batch, idx),
            lesson_ids=[lesson.id for lesson in batch],
            estimated_minutes=sum(lesson.estimated_minutes for lesson in batch),
        )
        milestones.append(milestone)

        checkpoint = Checkpoint(
            milestone_id=milestone.id,
            order=idx,
            title=f"Checkpoint {idx + 1}",
            checkpoint_type=_checkpoint_type_for_batch(batch),
            estimated_minutes=max(5, sum(lesson.estimated_minutes for lesson in batch) // 4),
            lesson_ids=[lesson.id for lesson in batch],
        )
        checkpoints.append(checkpoint)

    return milestones, checkpoints


def _describe_milestone(batch: list[Lesson], idx: int) -> str:
    """Generate a short description for a milestone."""
    if not batch:
        return f"Milestone {idx + 1}"
    diffs = {lesson.difficulty for lesson in batch}
    if len(diffs) == 1:
        level = next(iter(diffs))
        return f"Milestone {idx + 1}: {level.capitalize()} topics"
    return f"Milestone {idx + 1}: Mixed difficulty topics"


def _checkpoint_type_for_batch(batch: list[Lesson]) -> CheckpointType:
    """Determine checkpoint type based on lesson difficulty distribution."""
    if not batch:
        return CheckpointType.SELF_TEST
    max_diff = max(_DIFFICULTY_ORDER.get(lesson.difficulty, 0) for lesson in batch)
    if max_diff >= 2:
        return CheckpointType.PRACTICE
    if max_diff >= 1:
        return CheckpointType.QUIZ
    return CheckpointType.SELF_TEST


def _extract_objectives(node: Any) -> list[str]:
    """Pull learning objectives from node metadata."""
    raw = node.metadata.get("learning_objectives", [])
    if isinstance(raw, list):
        return [str(o) for o in raw]
    return []


def _classify_lesson_type(node: Any, order: int, total: int) -> LessonType:
    """Classify a lesson based on its difficulty and position.

    Difficulty is the primary classifier.  Position is used only when
    difficulty is ambiguous (e.g., basic at the very start or end).
    """
    diff = node.metadata.get("difficulty", "basic")
    if diff == "advanced":
        return LessonType.ADVANCED
    if order == 0:
        return LessonType.INTRODUCTION
    if order == total - 1:
        return LessonType.REVIEW
    if diff == "intermediate":
        return LessonType.CORE
    return LessonType.CORE


def _prerequisite_ids_for(
    uid: UUID,
    adj: dict[UUID, list[UUID]],
    in_degree: dict[UUID, int],
    unit_ids: set[UUID],
) -> list[UUID]:
    """Return the unit IDs that are direct prerequisites of *uid*."""
    result: list[UUID] = []
    for source, targets in adj.items():
        if uid in targets and source in unit_ids:
            result.append(source)
    return result
