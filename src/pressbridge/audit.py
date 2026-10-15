"""Append-only JSON Lines audit log of every tool call."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()
_MAX_FIELD = 500


def _shorten(value):
    if isinstance(value, str) and len(value) > _MAX_FIELD:
        return value[:_MAX_FIELD] + f"... [{len(value)} chars]"
    if isinstance(value, list):
        return [_shorten(v) for v in value]
    if isinstance(value, dict):
        return {k: _shorten(v) for k, v in value.items()}
    return value


def record(log_path: Path, *, tool: str, site: str | None, args: dict, ok: bool, error: str | None = None,
           result_summary: dict | None = None) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "site": site,
        "args": _shorten(args),
        "ok": ok,
    }
    if error:
        entry["error"] = error[:_MAX_FIELD]
    if result_summary:
        entry["result"] = result_summary
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def tail(log_path: Path, limit: int = 50, site: str | None = None) -> list[dict]:
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if site and item.get("site") != site:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out
