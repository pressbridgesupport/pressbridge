"""File operations, all confined to a site root by sandbox.resolve().

Every change (write, edit, move, trash) first copies the original into the
backup area outside the webroot, so any change Claude makes can be undone
with restore_backup.
"""
from __future__ import annotations

import os
import re
import shutil
import stat as statmod
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, Site
from .sandbox import SandboxError, is_denied, relpath, require_writable, resolve

SKIP_DIRS = {"node_modules", ".git", "vendor"}
MAX_LIST_ENTRIES = 1000
MAX_SEARCH_FILE_BYTES = 1_000_000


def _is_binary(path: Path) -> bool:
    with path.open("rb") as f:
        return b"\x00" in f.read(8192)


def _lint_php(target: Path, candidate: Path) -> None:
    """Refuse to save PHP that does not parse. A syntax error in functions.php takes a site down."""
    if target.suffix.lower() not in (".php", ".phtml", ".inc"):
        return
    php = shutil.which("php")
    if not php:
        return
    try:
        proc = subprocess.run([php, "-l", "-d", "display_errors=1", "-d", "log_errors=0", str(candidate)],
                              capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return
    if proc.returncode != 0:
        msg = (proc.stdout + proc.stderr).replace(str(candidate), target.name).strip()
        msg = "\n".join(l for l in msg.splitlines() if "Errors parsing" not in l)
        raise ValueError(f"PHP syntax check failed, nothing was saved:\n{msg}")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _backup(cfg: Config, site: Site, target: Path) -> str | None:
    """Copy target into the backup area. Returns the backup id, or None if nothing to back up."""
    if not target.exists():
        return None
    backup_id = _stamp()
    dest = cfg.backup_root(site) / backup_id / relpath(site, target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(target, dest, symlinks=True)
    else:
        shutil.copy2(target, dest)
    return backup_id


def list_dir(cfg: Config, site: Site, path: str = ".", depth: int = 1) -> dict:
    base = resolve(site, path, must_exist=True)
    if not base.is_dir():
        raise NotADirectoryError(f"'{relpath(site, base)}' is not a directory")
    depth = max(1, min(int(depth), 4))
    entries: list[dict] = []
    truncated = False

    def walk(d: Path, level: int):
        nonlocal truncated
        try:
            children = sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        for child in children:
            rel = relpath(site, child)
            if is_denied(site, rel):
                continue
            if len(entries) >= MAX_LIST_ENTRIES:
                truncated = True
                return
            is_dir = child.is_dir() and not child.is_symlink()
            item = {"path": rel, "type": "dir" if is_dir else "file"}
            if not is_dir:
                try:
                    item["size"] = child.stat().st_size
                except OSError:
                    pass
            entries.append(item)
            if is_dir and level < depth and child.name not in SKIP_DIRS:
                walk(child, level + 1)

    walk(base, 1)
    return {"site": site.name, "path": relpath(site, base), "entries": entries, "truncated": truncated}


def read_file(cfg: Config, site: Site, path: str, offset: int = 1, limit: int = 2000) -> dict:
    target = resolve(site, path, must_exist=True)
    if target.is_dir():
        raise IsADirectoryError(f"'{relpath(site, target)}' is a directory; use list_dir")
    size = target.stat().st_size
    if _is_binary(target):
        return {"path": relpath(site, target), "binary": True, "size": size}
    if size > site.max_read_bytes and offset == 1 and limit >= 2000:
        limit = min(limit, 500)
    offset = max(1, int(offset))
    limit = max(1, min(int(limit), 5000))
    lines: list[str] = []
    total = 0
    read_bytes = 0
    with target.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, start=1):
            total = i
            if i < offset or len(lines) >= limit:
                continue
            read_bytes += len(line)
            if read_bytes > site.max_read_bytes:
                break
            lines.append(line)
    return {
        "path": relpath(site, target),
        "size": size,
        "start_line": offset,
        "end_line": offset + len(lines) - 1,
        "total_lines": total,
        "content": "".join(lines),
    }


def stat(cfg: Config, site: Site, path: str) -> dict:
    target = resolve(site, path, must_exist=True)
    st = target.stat()
    return {
        "path": relpath(site, target),
        "type": "dir" if target.is_dir() else "file",
        "size": st.st_size,
        "mode": statmod.filemode(st.st_mode),
        "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
    }


def search(
    cfg: Config,
    site: Site,
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    max_results: int = 100,
    ignore_case: bool = False,
) -> dict:
    base = resolve(site, path, must_exist=True)
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}") from e
    max_results = max(1, min(int(max_results), 500))
    results: list[dict] = []
    files_scanned = 0

    for dirpath, dirnames, filenames in os.walk(base):
        d = Path(dirpath)
        dirnames[:] = [
            n for n in dirnames if n not in SKIP_DIRS and not is_denied(site, relpath(site, d / n))
        ]
        for name in filenames:
            fp = d / name
            rel = relpath(site, fp)
            if is_denied(site, rel):
                continue
            if glob and not fp.match(glob):
                continue
            try:
                if fp.is_symlink() or fp.stat().st_size > MAX_SEARCH_FILE_BYTES or _is_binary(fp):
                    continue
                files_scanned += 1
                with fp.open("r", encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, start=1):
                        if rx.search(line):
                            results.append({"path": rel, "line": lineno, "text": line.rstrip()[:300]})
                            if len(results) >= max_results:
                                return {"matches": results, "truncated": True, "files_scanned": files_scanned}
            except (OSError, UnicodeError):
                continue
    return {"matches": results, "truncated": False, "files_scanned": files_scanned}


def write_file(cfg: Config, site: Site, path: str, content: str, create_dirs: bool = False) -> dict:
    require_writable(site)
    data = content.encode("utf-8")
    if len(data) > site.max_write_bytes:
        raise ValueError(f"Content is {len(data)} bytes; the limit for this site is {site.max_write_bytes}")
    target = resolve(site, path)
    if target.is_dir():
        raise IsADirectoryError(f"'{relpath(site, target)}' is a directory")
    if not target.parent.exists():
        if not create_dirs:
            raise FileNotFoundError(
                f"Folder '{relpath(site, target.parent)}' does not exist; pass create_dirs=true"
            )
        target.parent.mkdir(parents=True)
    tmp = target.with_name(f".{target.name}.pressbridge-tmp")
    tmp.write_bytes(data)
    try:
        _lint_php(target, tmp)
    except ValueError:
        tmp.unlink(missing_ok=True)
        raise
    backup_id = _backup(cfg, site, target)
    if target.exists():
        shutil.copymode(target, tmp)
    os.replace(tmp, target)
    return {
        "path": relpath(site, target),
        "bytes": len(data),
        "created": backup_id is None,
        "backup_id": backup_id,
    }


def edit_file(
    cfg: Config, site: Site, path: str, old_text: str, new_text: str, replace_all: bool = False
) -> dict:
    require_writable(site)
    target = resolve(site, path, must_exist=True)
    if _is_binary(target):
        raise ValueError("Cannot edit a binary file")
    original = target.read_text(encoding="utf-8")
    if not old_text:
        raise ValueError("old_text must not be empty")
    count = original.count(old_text)
    if count == 0:
        raise ValueError("old_text was not found in the file. Read the file again and copy the text exactly.")
    if count > 1 and not replace_all:
        raise ValueError(
            f"old_text appears {count} times. Include more surrounding text to make it unique, "
            "or pass replace_all=true."
        )
    updated = original.replace(old_text, new_text) if replace_all else original.replace(old_text, new_text, 1)
    result = write_file(cfg, site, path, updated)
    result["replacements"] = count if replace_all else 1
    return result


def move(cfg: Config, site: Site, source: str, destination: str) -> dict:
    require_writable(site)
    src = resolve(site, source, must_exist=True)
    dst = resolve(site, destination)
    if dst.exists():
        raise FileExistsError(f"'{relpath(site, dst)}' already exists")
    if src == site.root:
        raise SandboxError("Cannot move the site root")
    backup_id = _backup(cfg, site, src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"from": relpath(site, src), "to": relpath(site, dst), "backup_id": backup_id}


def trash(cfg: Config, site: Site, path: str) -> dict:
    """Move a file or folder out of the webroot into the trash. Nothing is ever deleted outright."""
    require_writable(site)
    target = resolve(site, path, must_exist=True)
    if target == site.root:
        raise SandboxError("Cannot trash the site root")
    rel = relpath(site, target)
    trash_id = _stamp()
    dest = cfg.trash_root(site) / trash_id / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(dest))
    return {"path": rel, "trash_id": trash_id, "note": "Moved to trash outside the webroot; restore with restore_backup."}


def list_backups(cfg: Config, site: Site, path: str | None = None, limit: int = 50) -> dict:
    items: list[dict] = []
    for kind, root in (("backup", cfg.backup_root(site)), ("trash", cfg.trash_root(site))):
        if not root.is_dir():
            continue
        for snap in root.iterdir():
            for dirpath, _, filenames in os.walk(snap):
                for name in filenames:
                    rel = Path(dirpath, name).relative_to(snap).as_posix()
                    if path and not rel.startswith(path.lstrip("/")):
                        continue
                    items.append({"id": snap.name, "kind": kind, "path": rel})
    items.sort(key=lambda x: x["id"], reverse=True)
    return {"site": site.name, "backups": items[: max(1, min(limit, 500))]}


def restore_backup(cfg: Config, site: Site, backup_id: str, path: str) -> dict:
    require_writable(site)
    if not re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z", backup_id):
        raise ValueError("backup_id looks wrong; get it from list_backups")
    target = resolve(site, path)
    rel = relpath(site, target)
    for root in (cfg.backup_root(site), cfg.trash_root(site)):
        src = root / backup_id / rel
        if src.exists():
            break
    else:
        raise FileNotFoundError(f"No backup '{backup_id}' for '{rel}'")
    current_backup = _backup(cfg, site, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target, symlinks=True)
    else:
        shutil.copy2(src, target)
    return {"restored": rel, "from_backup": backup_id, "previous_version_backup_id": current_backup}
