"""Tests for filesystem security helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from learning_platform.security import InvalidPathError, resolve_safe_path, sanitize_filename


class TestSanitizeFilename:
    def test_allows_simple_filename(self) -> None:
        assert sanitize_filename("notes.pdf") == "notes.pdf"

    def test_rejects_empty_filename(self) -> None:
        with pytest.raises(InvalidPathError):
            sanitize_filename("  ")

    def test_rejects_path_components(self) -> None:
        with pytest.raises(InvalidPathError):
            sanitize_filename("../../etc/passwd")


class TestResolveSafePath:
    def test_resolves_inside_base(self, tmp_path: Path) -> None:
        base = tmp_path / "uploads"
        base.mkdir(parents=True)
        resolved = resolve_safe_path(base, "course/file.pdf")
        assert str(resolved).startswith(str(base.resolve()))

    def test_rejects_absolute_path(self, tmp_path: Path) -> None:
        base = tmp_path / "uploads"
        base.mkdir(parents=True)
        with pytest.raises(InvalidPathError):
            resolve_safe_path(base, "/etc/passwd")

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        base = tmp_path / "uploads"
        base.mkdir(parents=True)
        with pytest.raises(InvalidPathError):
            resolve_safe_path(base, "../outside.txt")
