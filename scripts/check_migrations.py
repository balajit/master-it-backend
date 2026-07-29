#!/usr/bin/env python3
"""Validate Alembic migration state for CI/local checks.

Checks performed:
1. Exactly one migration head exists.
2. (Optional) The configured DB is at that head revision.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT: Path = Path(__file__).resolve().parent.parent


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def _parse_heads(output: str) -> list[str]:
    revs: list[str] = []
    for line in output.splitlines():
        m = re.match(r"^([0-9a-f]+)\s+\(head\)", line.strip())
        if m:
            revs.append(m.group(1))
    return revs


def _parse_current(output: str) -> str | None:
    for line in output.splitlines():
        m = re.search(r"\b([0-9a-f]{7,})\b", line)
        if m:
            return m.group(1)
    return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Alembic migration state")
    parser.add_argument(
        "--check-current",
        action="store_true",
        help="Also require current database revision to equal migration head",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    heads_proc = _run(["uv", "run", "alembic", "heads"])
    if heads_proc.returncode != 0:
        print(heads_proc.stdout)
        print(heads_proc.stderr)
        print("[migrations] Failed to inspect alembic heads")
        return 1

    heads = _parse_heads(heads_proc.stdout)
    if len(heads) != 1:
        print(heads_proc.stdout)
        print(f"[migrations] Expected exactly 1 head, found {len(heads)}")
        return 1

    head = heads[0]
    if not args.check_current:
        print(f"[migrations] OK: single head {head}")
        return 0

    current_proc = _run(["uv", "run", "alembic", "current"])
    if current_proc.returncode != 0:
        print(current_proc.stdout)
        print(current_proc.stderr)
        print("[migrations] Failed to inspect current migration revision")
        return 1

    current = _parse_current(current_proc.stdout)
    if current is None:
        print(current_proc.stdout)
        print("[migrations] Could not parse current migration revision")
        return 1

    if current != head:
        print(f"[migrations] Database not at head: current={current}, head={head}")
        return 1

    print(f"[migrations] OK: single head {head}, database at head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
