"""Guard rails for backward-compatible migrations.

Policy: schema changes in ``upgrade()`` must be additive and never destroy
data.  Drops are not the default strategy — renames must create the new
column, backfill data, and only then drop the old one.

Enforced:
- ``drop_table`` (or ``batch_op.drop_table``) in ``upgrade()`` is rejected.
- ``op.execute``/``batch_op.execute`` in ``upgrade()`` containing DROP,
  TRUNCATE or ``ALTER ... DROP`` is rejected.
- ``drop_column`` (or ``batch_op.drop_column``) in ``upgrade()`` is only
  allowed when the same ``upgrade()`` also creates a replacement column
  (``add_column``) or runs a data copy step (``execute``), i.e. the
  create-then-copy-then-drop rename pattern.

``drop_index`` and ``drop_constraint`` are non-data-destructive and allowed.
Drops inside ``downgrade()`` are always allowed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT: Path = Path(__file__).resolve().parent.parent.parent
VERSIONS_DIR: Path = ROOT / "alembic" / "versions"

_DROP_EXECUTE_RE: re.Pattern[str] = re.compile(r"\b(DROP|TRUNCATE)\b", re.IGNORECASE)


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _string_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _walk_batch_nodes(body: list[ast.AST]) -> list[ast.Call]:
    """Collect both op.* calls and calls nested inside batch_alter_table."""
    calls: list[ast.Call] = []

    def _collect(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call):
                calls.append(child)
                _collect(child)
            else:
                _collect(child)

    for statement in body:
        _collect(statement)
    return calls


@pytest.mark.parametrize(
    "path", sorted(VERSIONS_DIR.glob("*.py")), ids=lambda p: p.name
)
def test_upgrade_is_additive(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    upgrade = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        ),
        None,
    )
    assert upgrade is not None, f"{path.name}: missing upgrade()"

    calls = _walk_batch_nodes(upgrade.body)

    for call in calls:
        name = _call_name(call)
        if name in {"drop_table"}:
            pytest.fail(
                f"{path.name}: upgrade() calls op.drop_table — dropping a table "
                "is never backward compatible. Add a new table instead."
            )
        if name == "execute":
            sql = _string_literal(call.args[0]) if call.args else None
            if sql is not None and _DROP_EXECUTE_RE.search(sql):
                pytest.fail(
                    f"{path.name}: upgrade() runs destructive SQL: {sql!r} "
                    "— avoid DROP/TRUNCATE in forward migrations."
                )

    drop_columns = [call for call in calls if _call_name(call) in {"drop_column"}]
    if drop_columns:
        has_replacement = any(
            _call_name(call) in {"add_column", "execute"} for call in calls
        )
        if not has_replacement:
            pytest.fail(
                f"{path.name}: upgrade() drops a column without creating a "
                "replacement or copying data. For renames, add the new column, "
                "backfill data, then drop the old column."
            )
