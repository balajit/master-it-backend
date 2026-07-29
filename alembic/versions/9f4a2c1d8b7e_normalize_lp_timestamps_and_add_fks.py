"""normalize LP timestamps and add missing foreign keys

Revision ID: 9f4a2c1d8b7e
Revises: 31577d0ac6bd
Create Date: 2026-07-28 18:40:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision: str = "9f4a2c1d8b7e"
down_revision: Union[str, Sequence[str], None] = "31577d0ac6bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind: Connection, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _has_column(bind: Connection, table_name: str, column_name: str) -> bool:
    if not _has_table(bind, table_name):
        return False
    columns = sa.inspect(bind).get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def _get_column_type(
    bind: Connection, table_name: str, column_name: str
) -> sa.TypeEngine | None:
    if not _has_column(bind, table_name, column_name):
        return None
    columns = sa.inspect(bind).get_columns(table_name)
    for column in columns:
        if column.get("name") == column_name:
            return column.get("type")
    return None


def _has_fk(
    bind: Connection,
    table_name: str,
    constrained_columns: list[str],
    referred_table: str,
) -> bool:
    if not _has_table(bind, table_name):
        return False

    target_columns = tuple(constrained_columns)
    for fk in sa.inspect(bind).get_foreign_keys(table_name):
        existing_columns = tuple(fk.get("constrained_columns") or [])
        existing_referred_table = fk.get("referred_table")
        if (
            existing_columns == target_columns
            and existing_referred_table == referred_table
        ):
            return True
    return False


def _has_fk_name(bind: Connection, table_name: str, fk_name: str) -> bool:
    if not _has_table(bind, table_name):
        return False

    for fk in sa.inspect(bind).get_foreign_keys(table_name):
        if fk.get("name") == fk_name:
            return True
    return False


def _coerce_created_at_values(table_name: str) -> None:
    op.execute(
        sa.text(
            f"UPDATE {table_name} "
            "SET created_at = CURRENT_TIMESTAMP "
            "WHERE created_at IS NULL OR created_at = ''"
        )
    )


def _normalize_created_at_column(bind: Connection, table_name: str) -> None:
    if not _has_column(bind, table_name, "created_at"):
        return

    current_type = _get_column_type(bind, table_name, "created_at")
    if isinstance(current_type, sa.DateTime):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "created_at",
                existing_type=current_type,
                type_=sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        return

    _coerce_created_at_values(table_name)
    if bind.dialect.name == "postgresql":
        op.alter_column(
            table_name,
            "created_at",
            existing_type=current_type,
            server_default=None,
        )
        op.alter_column(
            table_name,
            "created_at",
            existing_type=current_type,
            type_=sa.DateTime(timezone=True),
            postgresql_using=(
                "CASE "
                "WHEN created_at IS NULL OR btrim(created_at) = '' "
                "THEN CURRENT_TIMESTAMP "
                "ELSE created_at::timestamptz "
                "END"
            ),
        )
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        return

    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=current_type,
            type_=sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )


def _downgrade_created_at_column(bind: Connection, table_name: str) -> None:
    if not _has_column(bind, table_name, "created_at"):
        return

    current_type = _get_column_type(bind, table_name, "created_at")
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=current_type,
            type_=sa.String(length=64),
            server_default=sa.text("''"),
        )


def upgrade() -> None:
    bind = op.get_bind()

    _normalize_created_at_column(bind, "lp_documents")
    _normalize_created_at_column(bind, "lp_knowledge_graphs")
    _normalize_created_at_column(bind, "lp_study_plans")

    if _has_table(bind, "lp_concept_relationships") and _has_table(bind, "lp_concepts"):
        op.execute(
            sa.text(
                "DELETE FROM lp_concept_relationships "
                "WHERE source_concept_id NOT IN (SELECT id FROM lp_concepts) "
                "OR target_concept_id NOT IN (SELECT id FROM lp_concepts)"
            )
        )

    if _has_table(bind, "lp_graph_nodes") and _has_table(bind, "lp_learning_units"):
        op.execute(
            sa.text(
                "DELETE FROM lp_graph_nodes "
                "WHERE unit_id IS NOT NULL "
                "AND unit_id NOT IN (SELECT id FROM lp_learning_units)"
            )
        )

    if _has_table(bind, "lp_graph_nodes") and _has_table(bind, "lp_concepts"):
        op.execute(
            sa.text(
                "DELETE FROM lp_graph_nodes "
                "WHERE concept_id IS NOT NULL "
                "AND concept_id NOT IN (SELECT id FROM lp_concepts)"
            )
        )

    if _has_table(bind, "lp_graph_edges") and _has_table(bind, "lp_graph_nodes"):
        op.execute(
            sa.text(
                "DELETE FROM lp_graph_edges "
                "WHERE source_node_id NOT IN (SELECT id FROM lp_graph_nodes) "
                "OR target_node_id NOT IN (SELECT id FROM lp_graph_nodes)"
            )
        )

    if _has_table(bind, "lp_lessons") and _has_table(bind, "lp_learning_units"):
        op.execute(
            sa.text(
                "DELETE FROM lp_lessons WHERE unit_id NOT IN (SELECT id FROM lp_learning_units)"
            )
        )

    if _has_table(bind, "lp_checkpoints") and _has_table(bind, "lp_milestones"):
        op.execute(
            sa.text(
                "DELETE FROM lp_checkpoints WHERE milestone_id NOT IN (SELECT id FROM lp_milestones)"
            )
        )

    if _has_table(bind, "lp_concept_relationships"):
        source_fk_exists = _has_fk(
            bind,
            "lp_concept_relationships",
            ["source_concept_id"],
            "lp_concepts",
        )
        target_fk_exists = _has_fk(
            bind,
            "lp_concept_relationships",
            ["target_concept_id"],
            "lp_concepts",
        )
        with op.batch_alter_table("lp_concept_relationships") as batch_op:
            if not source_fk_exists:
                batch_op.create_foreign_key(
                    "fk_lp_concept_relationships_source_concept_id_lp_concepts",
                    "lp_concepts",
                    ["source_concept_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            if not target_fk_exists:
                batch_op.create_foreign_key(
                    "fk_lp_concept_relationships_target_concept_id_lp_concepts",
                    "lp_concepts",
                    ["target_concept_id"],
                    ["id"],
                    ondelete="CASCADE",
                )

    if _has_table(bind, "lp_graph_nodes") and _has_table(bind, "lp_learning_units"):
        unit_fk_exists = _has_fk(
            bind, "lp_graph_nodes", ["unit_id"], "lp_learning_units"
        )
        with op.batch_alter_table("lp_graph_nodes") as batch_op:
            if not unit_fk_exists:
                batch_op.create_foreign_key(
                    "fk_lp_graph_nodes_unit_id_lp_learning_units",
                    "lp_learning_units",
                    ["unit_id"],
                    ["id"],
                    ondelete="SET NULL",
                )

    if _has_table(bind, "lp_graph_nodes") and _has_table(bind, "lp_concepts"):
        concept_fk_exists = _has_fk(
            bind, "lp_graph_nodes", ["concept_id"], "lp_concepts"
        )
        with op.batch_alter_table("lp_graph_nodes") as batch_op:
            if not concept_fk_exists:
                batch_op.create_foreign_key(
                    "fk_lp_graph_nodes_concept_id_lp_concepts",
                    "lp_concepts",
                    ["concept_id"],
                    ["id"],
                    ondelete="SET NULL",
                )

    if _has_table(bind, "lp_graph_edges"):
        source_edge_fk_exists = _has_fk(
            bind, "lp_graph_edges", ["source_node_id"], "lp_graph_nodes"
        )
        target_edge_fk_exists = _has_fk(
            bind, "lp_graph_edges", ["target_node_id"], "lp_graph_nodes"
        )
        with op.batch_alter_table("lp_graph_edges") as batch_op:
            if not source_edge_fk_exists:
                batch_op.create_foreign_key(
                    "fk_lp_graph_edges_source_node_id_lp_graph_nodes",
                    "lp_graph_nodes",
                    ["source_node_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            if not target_edge_fk_exists:
                batch_op.create_foreign_key(
                    "fk_lp_graph_edges_target_node_id_lp_graph_nodes",
                    "lp_graph_nodes",
                    ["target_node_id"],
                    ["id"],
                    ondelete="CASCADE",
                )

    if _has_table(bind, "lp_lessons") and _has_table(bind, "lp_learning_units"):
        lesson_unit_fk_exists = _has_fk(
            bind, "lp_lessons", ["unit_id"], "lp_learning_units"
        )
        with op.batch_alter_table("lp_lessons") as batch_op:
            if not lesson_unit_fk_exists:
                batch_op.create_foreign_key(
                    "fk_lp_lessons_unit_id_lp_learning_units",
                    "lp_learning_units",
                    ["unit_id"],
                    ["id"],
                    ondelete="CASCADE",
                )

    if _has_table(bind, "lp_checkpoints") and _has_table(bind, "lp_milestones"):
        checkpoint_milestone_fk_exists = _has_fk(
            bind,
            "lp_checkpoints",
            ["milestone_id"],
            "lp_milestones",
        )
        with op.batch_alter_table("lp_checkpoints") as batch_op:
            if not checkpoint_milestone_fk_exists:
                batch_op.create_foreign_key(
                    "fk_lp_checkpoints_milestone_id_lp_milestones",
                    "lp_milestones",
                    ["milestone_id"],
                    ["id"],
                    ondelete="CASCADE",
                )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_table(bind, "lp_checkpoints") and _has_fk_name(
        bind,
        "lp_checkpoints",
        "fk_lp_checkpoints_milestone_id_lp_milestones",
    ):
        with op.batch_alter_table("lp_checkpoints") as batch_op:
            batch_op.drop_constraint(
                "fk_lp_checkpoints_milestone_id_lp_milestones",
                type_="foreignkey",
            )

    if _has_table(bind, "lp_lessons") and _has_fk_name(
        bind,
        "lp_lessons",
        "fk_lp_lessons_unit_id_lp_learning_units",
    ):
        with op.batch_alter_table("lp_lessons") as batch_op:
            batch_op.drop_constraint(
                "fk_lp_lessons_unit_id_lp_learning_units",
                type_="foreignkey",
            )

    if _has_table(bind, "lp_graph_edges"):
        with op.batch_alter_table("lp_graph_edges") as batch_op:
            if _has_fk_name(
                bind,
                "lp_graph_edges",
                "fk_lp_graph_edges_source_node_id_lp_graph_nodes",
            ):
                batch_op.drop_constraint(
                    "fk_lp_graph_edges_source_node_id_lp_graph_nodes",
                    type_="foreignkey",
                )
            if _has_fk_name(
                bind,
                "lp_graph_edges",
                "fk_lp_graph_edges_target_node_id_lp_graph_nodes",
            ):
                batch_op.drop_constraint(
                    "fk_lp_graph_edges_target_node_id_lp_graph_nodes",
                    type_="foreignkey",
                )

    if _has_table(bind, "lp_graph_nodes"):
        with op.batch_alter_table("lp_graph_nodes") as batch_op:
            if _has_fk_name(
                bind, "lp_graph_nodes", "fk_lp_graph_nodes_unit_id_lp_learning_units"
            ):
                batch_op.drop_constraint(
                    "fk_lp_graph_nodes_unit_id_lp_learning_units",
                    type_="foreignkey",
                )
            if _has_fk_name(
                bind, "lp_graph_nodes", "fk_lp_graph_nodes_concept_id_lp_concepts"
            ):
                batch_op.drop_constraint(
                    "fk_lp_graph_nodes_concept_id_lp_concepts",
                    type_="foreignkey",
                )

    if _has_table(bind, "lp_concept_relationships"):
        with op.batch_alter_table("lp_concept_relationships") as batch_op:
            if _has_fk_name(
                bind,
                "lp_concept_relationships",
                "fk_lp_concept_relationships_source_concept_id_lp_concepts",
            ):
                batch_op.drop_constraint(
                    "fk_lp_concept_relationships_source_concept_id_lp_concepts",
                    type_="foreignkey",
                )
            if _has_fk_name(
                bind,
                "lp_concept_relationships",
                "fk_lp_concept_relationships_target_concept_id_lp_concepts",
            ):
                batch_op.drop_constraint(
                    "fk_lp_concept_relationships_target_concept_id_lp_concepts",
                    type_="foreignkey",
                )

    _downgrade_created_at_column(bind, "lp_study_plans")
    _downgrade_created_at_column(bind, "lp_knowledge_graphs")
    _downgrade_created_at_column(bind, "lp_documents")
