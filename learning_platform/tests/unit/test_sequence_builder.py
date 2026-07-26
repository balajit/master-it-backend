"""Unit tests for LearningSequenceBuilder, models, and difficulty balancing."""

from __future__ import annotations

from uuid import UUID, uuid4

from learning_platform.models.knowledge_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)
from learning_platform.models.sequence import (
    Checkpoint,
    CheckpointType,
    Lesson,
    LessonType,
    Milestone,
    StudyPlan,
)
from learning_platform.stages.sequence_builder.sequencer import (
    TopologicalSequenceBuilder,
    _balanced_topological_sort,
    _count_streak,
    _group_milestones,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _unit_node(
    label: str,
    *,
    difficulty: str = "basic",
    estimated_minutes: int = 10,
    learning_objectives: list[str] | None = None,
    description: str = "",
) -> tuple[GraphNode, UUID]:
    """Create a UNIT GraphNode and return it with its UUID."""
    uid = uuid4()
    node = GraphNode(
        id=uid,
        node_type=NodeType.UNIT,
        label=label,
        unit_id=uid,
        metadata={
            "difficulty": difficulty,
            "estimated_minutes": estimated_minutes,
            "learning_objectives": learning_objectives or [],
            "description": description,
        },
    )
    return node, uid


def _prereq_edge(source: UUID, target: UUID) -> GraphEdge:
    """Create a DEPENDS_ON edge between two unit nodes."""
    return GraphEdge(
        source_id=source,
        target_id=target,
        edge_type=EdgeType.DEPENDS_ON,
        metadata={"source": "test"},
    )


def _contains_edge(parent: UUID, child: UUID) -> GraphEdge:
    """Create a CONTAINS edge."""
    return GraphEdge(
        source_id=parent,
        target_id=child,
        edge_type=EdgeType.CONTAINS,
        metadata={"source": "test"},
    )


def _graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> KnowledgeGraph:
    return KnowledgeGraph(nodes=nodes, edges=edges)


# ══════════════════════════════════════════════════════════════════════════════
# Model tests
# ══════════════════════════════════════════════════════════════════════════════


class TestStudyPlanModel:
    def test_lesson_defaults(self) -> None:
        lesson = Lesson(unit_id=uuid4())
        assert lesson.order == 0
        assert lesson.lesson_type == LessonType.CORE
        assert lesson.difficulty == "basic"
        assert lesson.estimated_minutes == 0
        assert lesson.prerequisites == []
        assert lesson.milestone_id is None

    def test_lesson_with_objectives(self) -> None:
        lesson = Lesson(
            unit_id=uuid4(),
            learning_objectives=["Understand X", "Apply Y"],
        )
        assert len(lesson.learning_objectives) == 2

    def test_milestone_defaults(self) -> None:
        m = Milestone()
        assert m.order == 0
        assert m.lesson_ids == []
        assert m.estimated_minutes == 0

    def test_checkpoint_defaults(self) -> None:
        cp = Checkpoint(milestone_id=uuid4())
        assert cp.checkpoint_type == CheckpointType.SELF_TEST
        assert cp.lesson_ids == []

    def test_study_plan_totals(self) -> None:
        l1 = Lesson(unit_id=uuid4(), estimated_minutes=10)
        l2 = Lesson(unit_id=uuid4(), estimated_minutes=20)
        m = Milestone(lesson_ids=[l1.id, l2.id])
        cp = Checkpoint(milestone_id=m.id)
        plan = StudyPlan(
            lessons=[l1, l2],
            milestones=[m],
            checkpoints=[cp],
            total_estimated_minutes=30,
            total_lessons=2,
        )
        assert plan.total_lessons == 2
        assert plan.total_estimated_minutes == 30

    def test_lesson_type_values(self) -> None:
        assert LessonType.INTRODUCTION.value == "introduction"
        assert LessonType.CORE.value == "core"
        assert LessonType.ADVANCED.value == "advanced"
        assert LessonType.REVIEW.value == "review"

    def test_checkpoint_type_values(self) -> None:
        assert CheckpointType.QUIZ.value == "quiz"
        assert CheckpointType.PRACTICE.value == "practice"
        assert CheckpointType.PROJECT.value == "project"
        assert CheckpointType.SELF_TEST.value == "self_test"


# ══════════════════════════════════════════════════════════════════════════════
# Topological sort tests
# ══════════════════════════════════════════════════════════════════════════════


class TestBalancedTopologicalSort:
    def test_empty_graph(self) -> None:
        result = _balanced_topological_sort(set(), {}, {}, {})
        assert result == []

    def test_single_node(self) -> None:
        node, uid = _unit_node("A")
        result = _balanced_topological_sort({uid}, {}, {uid: 0}, {uid: node})
        assert result == [uid]

    def test_linear_chain(self) -> None:
        n1, u1 = _unit_node("A")
        n2, u2 = _unit_node("B")
        n3, u3 = _unit_node("C")
        adj = {u1: [u2], u2: [u3]}
        in_degree = {u1: 0, u2: 1, u3: 1}
        id_to_node = {u1: n1, u2: n2, u3: n3}
        result = _balanced_topological_sort({u1, u2, u3}, adj, in_degree, id_to_node)
        assert result == [u1, u2, u3]

    def test_diamond_graph(self) -> None:
        n1, u1 = _unit_node("A")
        n2, u2 = _unit_node("B")
        n3, u3 = _unit_node("C")
        n4, u4 = _unit_node("D")
        adj = {u1: [u2, u3], u2: [u4], u3: [u4]}
        in_degree = {u1: 0, u2: 1, u3: 1, u4: 2}
        id_to_node = {u1: n1, u2: n2, u3: n3, u4: n4}
        result = _balanced_topological_sort({u1, u2, u3, u4}, adj, in_degree, id_to_node)
        assert result[0] == u1  # A must be first
        assert result[-1] == u4  # D must be last
        assert len(result) == 4

    def test_disconnected_nodes(self) -> None:
        n1, u1 = _unit_node("A")
        n2, u2 = _unit_node("B")
        n3, u3 = _unit_node("C")
        adj: dict = {}
        in_degree = {u1: 0, u2: 0, u3: 0}
        id_to_node = {u1: n1, u2: n2, u3: n3}
        result = _balanced_topological_sort({u1, u2, u3}, adj, in_degree, id_to_node)
        assert len(result) == 3
        assert set(result) == {u1, u2, u3}

    def test_prerequisite_order_respected(self) -> None:
        """A → B means A must come before B."""
        n1, u1 = _unit_node("Basic", difficulty="basic")
        n2, u2 = _unit_node("Advanced", difficulty="advanced")
        adj = {u1: [u2]}
        in_degree = {u1: 0, u2: 1}
        id_to_node = {u1: n1, u2: n2}
        result = _balanced_topological_sort({u1, u2}, adj, in_degree, id_to_node)
        assert result == [u1, u2]

    def test_difficulty_balanced_across_disconnected(self) -> None:
        """Disconnected nodes should be interleaved by difficulty."""
        n1, u1 = _unit_node("A", difficulty="basic")
        n2, u2 = _unit_node("B", difficulty="advanced")
        n3, u3 = _unit_node("C", difficulty="basic")
        n4, u4 = _unit_node("D", difficulty="advanced")
        adj: dict = {}
        in_degree = {u1: 0, u2: 0, u3: 0, u4: 0}
        id_to_node = {u1: n1, u2: n2, u3: n3, u4: n4}
        result = _balanced_topological_sort({u1, u2, u3, u4}, adj, in_degree, id_to_node)
        # Check that we don't get 4 basics in a row or 4 advanced in a row
        difficulties = [id_to_node[uid].metadata["difficulty"] for uid in result]
        # At most 2 consecutive same difficulty (greedy heuristic)
        for i in range(len(difficulties) - 2):
            assert not (difficulties[i] == difficulties[i + 1] == difficulties[i + 2]), (
                f"3 consecutive {difficulties[i]} at index {i}: {difficulties}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Milestone grouping tests
# ══════════════════════════════════════════════════════════════════════════════


class TestMilestoneGrouping:
    def test_empty_lessons(self) -> None:
        milestones, checkpoints = _group_milestones([], 4)
        assert milestones == []
        assert checkpoints == []

    def test_single_lesson(self) -> None:
        l1 = Lesson(unit_id=uuid4(), difficulty="basic")
        milestones, checkpoints = _group_milestones([l1], 4)
        assert len(milestones) == 1
        assert len(checkpoints) == 1
        assert milestones[0].lesson_ids == [l1.id]
        assert checkpoints[0].milestone_id == milestones[0].id

    def test_batch_by_size(self) -> None:
        lessons = [Lesson(unit_id=uuid4(), difficulty="basic") for _ in range(5)]
        milestones, checkpoints = _group_milestones(lessons, 3)
        # 5 lessons, batch size 3 → 2 milestones
        assert len(milestones) == 2
        assert len(checkpoints) == 2
        assert len(milestones[0].lesson_ids) == 3
        assert len(milestones[1].lesson_ids) == 2

    def test_batch_by_difficulty_change(self) -> None:
        lessons = [
            Lesson(unit_id=uuid4(), difficulty="basic"),
            Lesson(unit_id=uuid4(), difficulty="basic"),
            Lesson(unit_id=uuid4(), difficulty="advanced"),
            Lesson(unit_id=uuid4(), difficulty="advanced"),
        ]
        milestones, _ = _group_milestones(lessons, 10)
        # Should split at difficulty change (after 2 basics)
        assert len(milestones) == 2
        assert len(milestones[0].lesson_ids) == 2
        assert len(milestones[1].lesson_ids) == 2

    def test_checkpoint_after_each_milestone(self) -> None:
        lessons = [Lesson(unit_id=uuid4()) for _ in range(8)]
        milestones, checkpoints = _group_milestones(lessons, 4)
        assert len(checkpoints) == len(milestones)
        for cp, ms in zip(checkpoints, milestones, strict=True):
            assert cp.milestone_id == ms.id

    def test_lesson_ids_match(self) -> None:
        l1 = Lesson(unit_id=uuid4(), difficulty="basic")
        l2 = Lesson(unit_id=uuid4(), difficulty="basic")
        milestones, _ = _group_milestones([l1, l2], 4)
        assert milestones[0].lesson_ids == [l1.id, l2.id]

    def test_milestone_estimated_minutes(self) -> None:
        l1 = Lesson(unit_id=uuid4(), estimated_minutes=10)
        l2 = Lesson(unit_id=uuid4(), estimated_minutes=15)
        milestones, _ = _group_milestones([l1, l2], 4)
        assert milestones[0].estimated_minutes == 25

    def test_checkpoint_self_test_for_basic(self) -> None:
        lessons = [Lesson(unit_id=uuid4(), difficulty="basic")]
        _, checkpoints = _group_milestones(lessons, 4)
        assert checkpoints[0].checkpoint_type == CheckpointType.SELF_TEST

    def test_checkpoint_quiz_for_intermediate(self) -> None:
        lessons = [Lesson(unit_id=uuid4(), difficulty="intermediate")]
        _, checkpoints = _group_milestones(lessons, 4)
        assert checkpoints[0].checkpoint_type == CheckpointType.QUIZ

    def test_checkpoint_practice_for_advanced(self) -> None:
        lessons = [Lesson(unit_id=uuid4(), difficulty="advanced")]
        _, checkpoints = _group_milestones(lessons, 4)
        assert checkpoints[0].checkpoint_type == CheckpointType.PRACTICE

    def test_checkpoint_estimated_minutes(self) -> None:
        lessons = [Lesson(unit_id=uuid4(), estimated_minutes=20)]
        _, checkpoints = _group_milestones(lessons, 4)
        assert checkpoints[0].estimated_minutes >= 5


# ══════════════════════════════════════════════════════════════════════════════
# Full builder tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTopologicalSequenceBuilder:
    def setup_method(self) -> None:
        self.builder = TopologicalSequenceBuilder(milestone_size=3)

    def test_empty_graph(self) -> None:
        plan = self.builder.build(KnowledgeGraph())
        assert plan.lessons == []
        assert plan.milestones == []
        assert plan.checkpoints == []
        assert plan.total_lessons == 0
        assert plan.total_estimated_minutes == 0

    def test_single_unit(self) -> None:
        node, uid = _unit_node("Intro", difficulty="basic", estimated_minutes=5)
        plan = self.builder.build(_graph([node], []))
        assert len(plan.lessons) == 1
        assert plan.lessons[0].title == "Intro"
        assert plan.lessons[0].difficulty == "basic"
        assert plan.lessons[0].estimated_minutes == 5

    def test_two_independent_units(self) -> None:
        n1, u1 = _unit_node("A", difficulty="basic")
        n2, u2 = _unit_node("B", difficulty="advanced")
        plan = self.builder.build(_graph([n1, n2], []))
        assert len(plan.lessons) == 2
        assert plan.total_lessons == 2

    def test_prerequisite_chain(self) -> None:
        n1, u1 = _unit_node("Basics")
        n2, u2 = _unit_node("Intermediate")
        n3, u3 = _unit_node("Advanced")
        edges = [_prereq_edge(u1, u2), _prereq_edge(u2, u3)]
        plan = self.builder.build(_graph([n1, n2, n3], edges))
        assert len(plan.lessons) == 3
        # Basics must come first
        assert plan.lessons[0].title == "Basics"
        assert plan.lessons[1].title == "Intermediate"
        assert plan.lessons[2].title == "Advanced"

    def test_prerequisite_ids_on_lesson(self) -> None:
        n1, u1 = _unit_node("A")
        n2, u2 = _unit_node("B")
        edges = [_prereq_edge(u1, u2)]
        plan = self.builder.build(_graph([n1, n2], edges))
        lesson_b = next(lesson for lesson in plan.lessons if lesson.title == "B")
        assert u1 in lesson_b.prerequisites

    def test_milestones_created(self) -> None:
        nodes = [_unit_node(f"U{i}")[0] for i in range(6)]
        plan = self.builder.build(_graph(nodes, []))
        assert len(plan.milestones) >= 2
        # All lessons belong to a milestone
        for lesson in plan.lessons:
            assert lesson.milestone_id is not None

    def test_checkpoints_after_milestones(self) -> None:
        nodes = [_unit_node(f"U{i}")[0] for i in range(6)]
        plan = self.builder.build(_graph(nodes, []))
        assert len(plan.checkpoints) == len(plan.milestones)
        for cp in plan.checkpoints:
            assert cp.milestone_id is not None

    def test_total_estimated_minutes(self) -> None:
        n1, _ = _unit_node("A", estimated_minutes=10)
        n2, _ = _unit_node("B", estimated_minutes=20)
        plan = self.builder.build(_graph([n1, n2], []))
        assert plan.total_estimated_minutes == 30

    def test_learning_objectives_captured(self) -> None:
        node, uid = _unit_node(
            "Obj",
            learning_objectives=["Understand X", "Apply Y"],
        )
        plan = self.builder.build(_graph([node], []))
        assert plan.lessons[0].learning_objectives == ["Understand X", "Apply Y"]

    def test_lesson_type_introduction(self) -> None:
        node, _ = _unit_node("First")
        plan = self.builder.build(_graph([node], []))
        assert plan.lessons[0].lesson_type == LessonType.INTRODUCTION

    def test_lesson_type_review(self) -> None:
        nodes = [_unit_node(f"U{i}")[0] for i in range(3)]
        plan = self.builder.build(_graph(nodes, []))
        assert plan.lessons[-1].lesson_type == LessonType.REVIEW

    def test_lesson_type_advanced(self) -> None:
        n1, u1 = _unit_node("A", difficulty="basic")
        n2, u2 = _unit_node("B", difficulty="advanced")
        n3, u3 = _unit_node("C", difficulty="basic")
        plan = self.builder.build(_graph([n1, n2, n3], []))
        advanced = [lesson for lesson in plan.lessons if lesson.lesson_type == LessonType.ADVANCED]
        assert len(advanced) >= 1

    def test_contains_edges_ignored_for_prereqs(self) -> None:
        """CONTAINS edges should not create prerequisite relationships."""
        n1, u1 = _unit_node("Parent")
        n2, u2 = _unit_node("Child")
        plan = self.builder.build(_graph([n1, n2], [_contains_edge(u1, u2)]))
        # Child should not have Parent as a prerequisite
        child_lesson = next(lesson for lesson in plan.lessons if lesson.title == "Child")
        assert u1 not in child_lesson.prerequisites

    def test_concept_nodes_ignored(self) -> None:
        """Concept nodes should not appear in the study plan."""
        n1, u1 = _unit_node("Unit")
        concept = GraphNode(id=uuid4(), node_type=NodeType.CONCEPT, label="Concept")
        plan = self.builder.build(_graph([n1, concept], []))
        assert plan.total_lessons == 1
        assert plan.lessons[0].title == "Unit"

    def test_milestone_title_and_description(self) -> None:
        nodes = [_unit_node(f"U{i}")[0] for i in range(4)]
        plan = self.builder.build(_graph(nodes, []))
        for ms in plan.milestones:
            assert ms.title.startswith("Milestone")
            assert ms.description != ""

    def test_full_integration(self) -> None:
        """Complex graph: 6 units, mixed difficulties, prerequisites."""
        n1, u1 = _unit_node("Introduction", difficulty="basic", estimated_minutes=5)
        n2, u2 = _unit_node("Basics", difficulty="basic", estimated_minutes=10)
        n3, u3 = _unit_node("Core Concepts", difficulty="intermediate", estimated_minutes=15)
        n4, u4 = _unit_node("Applications", difficulty="intermediate", estimated_minutes=20)
        n5, u5 = _unit_node("Advanced Topics", difficulty="advanced", estimated_minutes=25)
        n6, u6 = _unit_node("Review & Summary", difficulty="basic", estimated_minutes=10)

        edges = [
            _prereq_edge(u1, u2),
            _prereq_edge(u2, u3),
            _prereq_edge(u3, u4),
            _prereq_edge(u4, u5),
            _prereq_edge(u5, u6),
        ]

        plan = self.builder.build(_graph([n1, n2, n3, n4, n5, n6], edges))

        assert plan.total_lessons == 6
        assert plan.total_estimated_minutes == 85
        assert len(plan.milestones) >= 2
        assert len(plan.checkpoints) == len(plan.milestones)

        # Prerequisites respected
        titles = [lesson.title for lesson in plan.lessons]
        assert titles.index("Introduction") < titles.index("Basics")
        assert titles.index("Basics") < titles.index("Core Concepts")
        assert titles.index("Advanced Topics") < titles.index("Review & Summary")

        # All lessons have milestone IDs
        for lesson in plan.lessons:
            assert lesson.milestone_id is not None

    def test_custom_milestone_size(self) -> None:
        builder = TopologicalSequenceBuilder(milestone_size=2)
        nodes = [_unit_node(f"U{i}")[0] for i in range(6)]
        plan = builder.build(_graph(nodes, []))
        # With size 2, 6 lessons → 3 milestones
        assert len(plan.milestones) == 3


# ══════════════════════════════════════════════════════════════════════════════
# Helper function tests
# ══════════════════════════════════════════════════════════════════════════════


class TestHelpers:
    def test_count_streak_empty(self) -> None:
        assert _count_streak([]) == 0

    def test_count_streak_single(self) -> None:
        assert _count_streak(["basic"]) == 1

    def test_count_streak_all_same(self) -> None:
        assert _count_streak(["basic", "basic", "basic"]) == 3

    def test_count_streak_mixed(self) -> None:
        assert _count_streak(["basic", "advanced", "basic"]) == 1

    def test_count_streak_trailing(self) -> None:
        assert _count_streak(["basic", "advanced", "advanced"]) == 2
