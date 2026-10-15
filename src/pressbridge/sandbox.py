"""Path sandboxing: every path Claude sends is resolved inside a site's root.

Rules:
* Paths are relative to the site root. A leading "/" is treated as the root.
* The fully resolved path (symlinks followed) must stay inside the root.
* Paths matching the site's deny patterns are refused, at any depth.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path, PurePosixPath

from .config import Site


class SandboxError(PermissionError):
    """Raised when a path escapes the site root or is denied."""


def relpath(site: Site, path: Path) -> str:
    rel = path.relative_to(site.root).as_posix()
    return "." if rel == "" else rel


def is_denied(site: Site, rel: str) -> str | None:
    """Return the matching deny pattern, or None if the path is allowed."""
    if rel in ("", "."):
        return None
    parts = PurePosixPath(rel).parts
    for pattern in site.deny:
        if "/" in pattern:
            if fnmatch.fnmatch(rel, pattern) or any(
                fnmatch.fnmatch("/".join(parts[: i + 1]), pattern) for i in range(len(parts))
            ):
                return pattern
        else:
            if any(fnmatch.fnmatch(p, pattern) for p in parts):
                return pattern
    return None


def resolve(site: Site, path: str | None, *, must_exist: bool = False) -> Path:
    raw = (path or ".").strip()
    if "\x00" in raw:
        raise SandboxError("Path contains a null byte")
    raw = raw.lstrip("/") or "."
    candidate = site.root / raw

    # Resolve symlinks on the existing part of the path; a not-yet-existing
    # tail (for new files) is appended after normalisation.
    resolved = Path(os.path.realpath(candidate))
    try:
        resolved.relative_to(site.root)
    except ValueError:
        raise SandboxError(f"Path '{path}' is outside the site root") from None

    rel = relpath(site, resolved)
    pattern = is_denied(site, rel)
    if pattern:
        raise SandboxError(f"Path '{rel}' is blocked by deny rule '{pattern}'")
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"'{rel}' does not exist")
    return resolved


def require_writable(site: Site) -> None:
    if not site.writable:
        raise SandboxError(
            f"Site '{site.name}' is read-only. Set `mode: write` in the config to allow changes."
        )
