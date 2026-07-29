"""Security helpers for filesystem path validation."""

from __future__ import annotations

from pathlib import Path


class InvalidPathError(ValueError):
    """Raised when a path is unsafe or escapes the intended base directory."""


def sanitize_filename(filename: str) -> str:
    """Return a safe filename without path components.

    Rejects empty values and any value containing path separators.
    """
    raw = filename.strip()
    if not raw:
        raise InvalidPathError("Filename is empty")
    if "\x00" in raw:
        raise InvalidPathError("Filename contains null byte")

    candidate = Path(raw)
    if candidate.is_absolute() or len(candidate.parts) != 1:
        raise InvalidPathError("Filename must not include path components")

    name = candidate.name.strip()
    if not name or name in {".", ".."}:
        raise InvalidPathError("Filename is invalid")
    return name


def resolve_safe_path(base_dir: Path, relative_path: str) -> Path:
    """Resolve ``relative_path`` under ``base_dir`` and enforce containment."""
    rel = relative_path.strip()
    if not rel:
        raise InvalidPathError("Path is empty")
    if "\x00" in rel:
        raise InvalidPathError("Path contains null byte")

    rel_path = Path(rel)
    if rel_path.is_absolute():
        raise InvalidPathError("Absolute paths are not allowed")
    if any(part in {".", ".."} for part in rel_path.parts):
        raise InvalidPathError("Path traversal is not allowed")

    base_resolved = base_dir.resolve()
    candidate = (base_dir / rel_path).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise InvalidPathError("Path escapes base directory")
    return candidate
