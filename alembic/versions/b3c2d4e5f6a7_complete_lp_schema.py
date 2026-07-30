"""Complete LP schema — tables that previously relied on create_all.

Creates lp_concepts, lp_concept_relationships, lp_learning_units,
lp_knowledge_graphs, lp_graph_nodes, lp_graph_edges, lp_study_plans,
lp_lessons, lp_milestones, lp_checkpoints, and lp_annotations.

Also adds FK constraints that migration 9f4a2c1d8b7e had to skip when these
tables did not exist yet on a fresh database.

Revision ID: b3c2d4e5f6a7
Revises: a2b1c3d4e5f6
Create Date: 2026-07-29

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c2d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a2b1c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    bind = op.get_bind()
    return any(
        c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name)
    )


def _fk_exists(table: str, columns: list[str], ref_table: str) -> bool:
    if not _table_exists(table):
        return False
    bind = op.get_bind()
    target = tuple(columns)
    for fk in sa.inspect(bind).get_foreign_keys(table):
        if (
            tuple(fk.get("constrained_columns") or []) == target
            and fk.get("referred_table") == ref_table
        ):
            return True
    return False


def _index_exists(table: str, index_name: str) -> bool:
    if not _table_exists(table):
        return False
    bind = op.get_bind()
    return any(i["name"] == index_name for i in sa.inspect(bind).get_indexes(table))


def _create_lp_concepts() -> None:
    if _table_exists("lp_concepts"):
        return
    op.create_table(
        "lp_concepts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("lp_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("source_node_ids", sa.JSON(), nullable=True),
        sa.Column("source_unit_ids", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_concepts_document_id", "lp_concepts", ["document_id"])
    op.create_index("ix_lp_concepts_name", "lp_concepts", ["name"])
    op.create_index("ix_lp_concepts_category", "lp_concepts", ["category"])


def _create_lp_concept_relationships() -> None:
    if _table_exists("lp_concept_relationships"):
        return
    op.create_table(
        "lp_concept_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("lp_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_concept_id",
            sa.Uuid(),
            sa.ForeignKey("lp_concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_concept_id",
            sa.Uuid(),
            sa.ForeignKey("lp_concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_concept_relationships_document_id",
        "lp_concept_relationships",
        ["document_id"],
    )
    op.create_index(
        "ix_lp_concept_relationships_source",
        "lp_concept_relationships",
        ["source_concept_id"],
    )
    op.create_index(
        "ix_lp_concept_relationships_target",
        "lp_concept_relationships",
        ["target_concept_id"],
    )
    op.create_index(
        "ix_lp_concept_relationships_relation_type",
        "lp_concept_relationships",
        ["relation_type"],
    )


def _create_lp_learning_units() -> None:
    if _table_exists("lp_learning_units"):
        return
    op.create_table(
        "lp_learning_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("lp_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("unit_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("difficulty", sa.String(32), nullable=False, server_default="basic"),
        sa.Column(
            "estimated_study_time_minutes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("lp_learning_units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("learning_objectives", sa.JSON(), nullable=True),
        sa.Column("content_references", sa.JSON(), nullable=True),
        sa.Column("definitions", sa.JSON(), nullable=True),
        sa.Column("examples", sa.JSON(), nullable=True),
        sa.Column("figures", sa.JSON(), nullable=True),
        sa.Column("tables", sa.JSON(), nullable=True),
        sa.Column("equations", sa.JSON(), nullable=True),
        sa.Column("exercises", sa.JSON(), nullable=True),
        sa.Column("source_node_ids", sa.JSON(), nullable=True),
        sa.Column("children_ids", sa.JSON(), nullable=True),
        sa.Column("prerequisite_ids", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_learning_units_document_id", "lp_learning_units", ["document_id"]
    )
    if _column_exists("lp_learning_units", "parent_id"):
        op.create_index(
            "ix_lp_learning_units_parent_id", "lp_learning_units", ["parent_id"]
        )


def _create_lp_knowledge_graphs() -> None:
    if _table_exists("lp_knowledge_graphs"):
        return
    op.create_table(
        "lp_knowledge_graphs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("lp_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_knowledge_graphs_document_id", "lp_knowledge_graphs", ["document_id"]
    )


def _create_lp_graph_nodes() -> None:
    if _table_exists("lp_graph_nodes"):
        return
    op.create_table(
        "lp_graph_nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "graph_id",
            sa.Uuid(),
            sa.ForeignKey("lp_knowledge_graphs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(512), nullable=False, server_default=""),
        sa.Column(
            "unit_id",
            sa.Uuid(),
            sa.ForeignKey("lp_learning_units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "concept_id",
            sa.Uuid(),
            sa.ForeignKey("lp_concepts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_graph_nodes_graph_id", "lp_graph_nodes", ["graph_id"])
    op.create_index("ix_lp_graph_nodes_node_type", "lp_graph_nodes", ["node_type"])
    op.create_index("ix_lp_graph_nodes_unit_id", "lp_graph_nodes", ["unit_id"])
    op.create_index("ix_lp_graph_nodes_concept_id", "lp_graph_nodes", ["concept_id"])


def _create_lp_graph_edges() -> None:
    if _table_exists("lp_graph_edges"):
        return
    op.create_table(
        "lp_graph_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "graph_id",
            sa.Uuid(),
            sa.ForeignKey("lp_knowledge_graphs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_node_id",
            sa.Uuid(),
            sa.ForeignKey("lp_graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_node_id",
            sa.Uuid(),
            sa.ForeignKey("lp_graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("edge_type", sa.String(64), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_graph_edges_graph_id", "lp_graph_edges", ["graph_id"])
    op.create_index("ix_lp_graph_edges_source", "lp_graph_edges", ["source_node_id"])
    op.create_index("ix_lp_graph_edges_target", "lp_graph_edges", ["target_node_id"])
    op.create_index("ix_lp_graph_edges_edge_type", "lp_graph_edges", ["edge_type"])


def _create_lp_study_plans() -> None:
    if _table_exists("lp_study_plans"):
        return
    op.create_table(
        "lp_study_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("lp_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("description", sa.String(2048), nullable=False, server_default=""),
        sa.Column(
            "total_estimated_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("total_lessons", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_study_plans_document_id", "lp_study_plans", ["document_id"])


def _create_lp_milestones() -> None:
    if _table_exists("lp_milestones"):
        return
    op.create_table(
        "lp_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "study_plan_id",
            sa.Uuid(),
            sa.ForeignKey("lp_study_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("description", sa.String(2048), nullable=False, server_default=""),
        sa.Column(
            "estimated_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("lesson_ids", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_milestones_study_plan_id", "lp_milestones", ["study_plan_id"]
    )


def _create_lp_lessons() -> None:
    if _table_exists("lp_lessons"):
        return
    op.create_table(
        "lp_lessons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "study_plan_id",
            sa.Uuid(),
            sa.ForeignKey("lp_study_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "milestone_id",
            sa.Uuid(),
            sa.ForeignKey("lp_milestones.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "unit_id",
            sa.Uuid(),
            sa.ForeignKey("lp_learning_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("description", sa.String(2048), nullable=False, server_default=""),
        sa.Column("lesson_type", sa.String(32), nullable=False, server_default="core"),
        sa.Column("difficulty", sa.String(32), nullable=False, server_default="basic"),
        sa.Column(
            "estimated_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("learning_objectives", sa.JSON(), nullable=True),
        sa.Column("prerequisites", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_lessons_study_plan_id", "lp_lessons", ["study_plan_id"])
    op.create_index("ix_lp_lessons_milestone_id", "lp_lessons", ["milestone_id"])
    op.create_index("ix_lp_lessons_unit_id", "lp_lessons", ["unit_id"])


def _create_lp_checkpoints() -> None:
    if _table_exists("lp_checkpoints"):
        return
    op.create_table(
        "lp_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "study_plan_id",
            sa.Uuid(),
            sa.ForeignKey("lp_study_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "milestone_id",
            sa.Uuid(),
            sa.ForeignKey("lp_milestones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column(
            "checkpoint_type", sa.String(32), nullable=False, server_default="self_test"
        ),
        sa.Column(
            "estimated_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("lesson_ids", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_checkpoints_study_plan_id", "lp_checkpoints", ["study_plan_id"]
    )
    op.create_index(
        "ix_lp_checkpoints_milestone_id", "lp_checkpoints", ["milestone_id"]
    )


def _create_lp_annotations() -> None:
    if _table_exists("lp_annotations"):
        return
    op.create_table(
        "lp_annotations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("lp_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("detector", sa.String(128), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_annotations_document_id", "lp_annotations", ["document_id"])
    op.create_index("ix_lp_annotations_type", "lp_annotations", ["type"])
    op.create_index("ix_lp_annotations_node_id", "lp_annotations", ["node_id"])


def _add_missing_lp_fks_from_9f4a2c1d8b7e() -> None:
    """Re-apply FK constraints that migration 9f4a2c1d8b7e skipped because
    the target tables did not exist yet on a fresh database."""

    _lp_fks: list[tuple[str, list[str], str, str, str | None]] = [
        (
            "lp_concept_relationships",
            ["source_concept_id"],
            "lp_concepts",
            "fk_lp_concept_relationships_source",
            "CASCADE",
        ),
        (
            "lp_concept_relationships",
            ["target_concept_id"],
            "lp_concepts",
            "fk_lp_concept_relationships_target",
            "CASCADE",
        ),
        (
            "lp_graph_nodes",
            ["unit_id"],
            "lp_learning_units",
            "fk_lp_graph_nodes_unit_id",
            "SET NULL",
        ),
        (
            "lp_graph_nodes",
            ["concept_id"],
            "lp_concepts",
            "fk_lp_graph_nodes_concept_id",
            "SET NULL",
        ),
        (
            "lp_graph_edges",
            ["source_node_id"],
            "lp_graph_nodes",
            "fk_lp_graph_edges_source",
            "CASCADE",
        ),
        (
            "lp_graph_edges",
            ["target_node_id"],
            "lp_graph_nodes",
            "fk_lp_graph_edges_target",
            "CASCADE",
        ),
        (
            "lp_lessons",
            ["unit_id"],
            "lp_learning_units",
            "fk_lp_lessons_unit_id",
            "CASCADE",
        ),
        (
            "lp_checkpoints",
            ["milestone_id"],
            "lp_milestones",
            "fk_lp_checkpoints_milestone_id",
            "CASCADE",
        ),
    ]
    for table, columns, ref_table, fk_name, ondelete in _lp_fks:
        if (
            not _fk_exists(table, columns, ref_table)
            and _table_exists(table)
            and _table_exists(ref_table)
        ):
            op.create_foreign_key(
                fk_name, table, ref_table, columns, ["id"], ondelete=ondelete
            )


def upgrade() -> None:
    _create_lp_concepts()
    _create_lp_concept_relationships()
    _create_lp_learning_units()
    _create_lp_knowledge_graphs()
    _create_lp_graph_nodes()
    _create_lp_graph_edges()
    _create_lp_study_plans()
    _create_lp_milestones()
    _create_lp_lessons()
    _create_lp_checkpoints()
    _create_lp_annotations()
    _add_missing_lp_fks_from_9f4a2c1d8b7e()


def downgrade() -> None:
    pass
