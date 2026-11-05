"""Run a change under the health guard: check the site before and after, undo if it broke.

Each guarded operation is a pair: `change()` does the work and returns the tool result,
`undo(result)` reverses it and returns a short description. The guard adds a `health`
block to the result, and `rolled_back: true` when it had to undo the change.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from . import files, health, wpcli
from .config import Config, Site
from .sandbox import SandboxError, resolve

# A healthy result from the previous change is reused as the "before" state for this long,
# so a series of quick edits doesn't load every page twice.
REUSE_SECONDS = 90

_cache: dict[str, tuple[float, health.Snapshot]] = {}
_lock = threading.Lock()


def _before(cfg: Config, site: Site) -> health.Snapshot | None:
    with _lock:
        hit = _cache.get(site.name)
    if hit and time.monotonic() - hit[0] < REUSE_SECONDS and hit[1].ok:
        return hit[1]
    return health.snapshot(cfg, site)


def _remember(site: Site, snap: health.Snapshot | None) -> None:
    with _lock:
        if snap is not None and snap.ok:
            _cache[site.name] = (time.monotonic(), snap)
        else:
            _cache.pop(site.name, None)


def forget(site_name: str | None = None) -> None:
    with _lock:
        if site_name is None:
            _cache.clear()
        else:
            _cache.pop(site_name, None)


def run(cfg: Config, site: Site, change: Callable[[], dict],
        undo: Callable[[dict], str] | None) -> dict:
    if not site.health.enabled:
        return change()

    before = _before(cfg, site)
    result = change()
    after = health.snapshot(cfg, site, skip=health.unreachable(before))
    if after is None:  # nothing configured to check
        return result

    broken = health.newly_broken(before, after)
    block: dict = {"ok": after.ok, "checks": after.to_list()}
    if after.skipped:
        block["not_checked"] = sorted(after.skipped)
        block["not_checked_reason"] = ("couldn't be reached before the change either (check wp_url / "
                                       "health_check.base_url from the server)")
    if not broken:
        if not after.ok:
            block["note"] = "These checks were already failing before the change; nothing was undone."
        result["health"] = block
        _remember(site, after)
        return result

    block["broken_by_this_change"] = broken
    if undo is None:
        block["rolled_back"] = False
        block["action_needed"] = ("The site broke after this change and it can't be undone automatically. "
                                  "Tell the user now and fix it, or restore from a backup.")
        result["health"] = block
        result["rolled_back"] = False
        forget(site.name)
        return result
    if not site.health.auto_rollback:
        block["rolled_back"] = False
        block["action_needed"] = ("The site broke after this change. Automatic rollback is off for this "
                                  "site; undo it now with the backup_id or fix the error.")
        result["health"] = block
        result["rolled_back"] = False
        forget(site.name)
        return result

    try:
        how = undo(result)
    except Exception as e:  # noqa: BLE001 - report, never mask the original problem
        block["rolled_back"] = False
        block["rollback_error"] = str(e)
        block["action_needed"] = "Automatic rollback failed. Tell the user now and restore from a backup."
        result["health"] = block
        result["rolled_back"] = False
        forget(site.name)
        return result

    recheck = health.snapshot(cfg, site, skip=health.unreachable(before))
    block["rolled_back"] = True
    block["rollback"] = how
    block["after_rollback"] = {"ok": recheck.ok if recheck else None,
                               "checks": recheck.to_list() if recheck else []}
    block["message"] = ("This change broke the site, so PressBridge undid it automatically. "
                        "Tell the user what failed and find another way.")
    result["health"] = block
    result["rolled_back"] = True
    _remember(site, recheck)
    return result


# ---------- undo for file operations ----------

def undo_write(cfg: Config, site: Site, path: str) -> Callable[[dict], str]:
    def undo(result: dict) -> str:
        if result.get("backup_id"):
            files.restore_backup(cfg, site, result["backup_id"], path)
            return f"restored {result['path']} from backup {result['backup_id']}"
        t = files.trash(cfg, site, path)
        return f"moved the new file {t['path']} to the trash ({t['trash_id']})"
    return undo


def undo_move(cfg: Config, site: Site) -> Callable[[dict], str]:
    def undo(result: dict) -> str:
        files.move(cfg, site, result["to"], result["from"])
        return f"moved {result['to']} back to {result['from']}"
    return undo


def undo_trash(cfg: Config, site: Site) -> Callable[[dict], str]:
    def undo(result: dict) -> str:
        files.restore_backup(cfg, site, result["trash_id"], result["path"])
        return f"put {result['path']} back from the trash"
    return undo


def undo_restore(cfg: Config, site: Site) -> Callable[[dict], str]:
    def undo(result: dict) -> str:
        prev = result.get("previous_version_backup_id")
        if prev:
            files.restore_backup(cfg, site, prev, result["restored"])
            return f"put back the version of {result['restored']} that was there before ({prev})"
        t = files.trash(cfg, site, result["restored"])
        return f"moved {result['restored']} to the trash ({t['trash_id']})"
    return undo


# ---------- WP-CLI ----------

# Commands that are checked afterwards. Read-only commands, cache flushes, posts and
# maintenance mode are not (maintenance mode is supposed to make the site answer 503).
CHECKED = {
    ("plugin", "activate"), ("plugin", "deactivate"), ("plugin", "update"), ("plugin", "install"),
    ("theme", "activate"), ("theme", "update"), ("theme", "install"),
    ("core", "update"), ("core", "update-db"), ("option", "update"),
    ("cron", "event", "run"), ("rewrite", "flush"),
    ("language", "core", "install"), ("language", "core", "update"),
}


def _slugs(args: list[str], cmd: tuple[str, ...]) -> list[str]:
    pos = [a for a in args if not a.startswith("-")]
    return pos[len(cmd):]


# Rollbacks run WP-CLI without loading plugins and themes: the code that broke the site
# would otherwise crash WP-CLI too and the undo itself would fail.
SAFE = ["--skip-plugins", "--skip-themes"]


def _wp_ok(cfg: Config, site: Site, args: list[str]) -> dict:
    r = wpcli.run(cfg, site, [*args, *SAFE])
    if r["exit_code"] != 0:
        raise RuntimeError(f"`{r['command']}` failed: {(r['stderr'] or r['stdout']).strip()[:300]}")
    return r


def _content_dir(site: Site, kind: str) -> Path | None:
    if not site.wp_path:
        return None
    d = site.wp_path / "wp-content" / kind
    return d if d.is_dir() else None


def _rel_in_site(site: Site, p: Path) -> str | None:
    """Path relative to the site root if PressBridge may touch it, else None."""
    try:
        rel = p.resolve().relative_to(site.root).as_posix()
        resolve(site, rel)
        return rel
    except (ValueError, SandboxError):
        return None


def _backup_dirs(cfg: Config, site: Site, kind: str, slugs: list[str]) -> list[tuple[str, str]]:
    base = _content_dir(site, kind)
    saved: list[tuple[str, str]] = []
    if not base:
        return saved
    for slug in slugs:
        d = base / slug
        rel = _rel_in_site(site, d) if d.is_dir() else None
        if rel is None:
            continue
        backup_id = files._backup(cfg, site, d)  # noqa: SLF001 - same package
        if backup_id:
            saved.append((backup_id, rel))
    return saved


def prepare_wp(cfg: Config, site: Site, args: list[str]) -> tuple[bool, Callable[[dict], str] | None]:
    """Decide whether this WP-CLI call is checked, and how to undo it. Runs before the command."""
    try:
        return _prepare_wp(cfg, site, args)
    except (RuntimeError, SandboxError, ValueError, OSError):
        # Preparing the undo failed (e.g. WP-CLI timed out). Still check, just don't undo.
        return True, None


def _prepare_wp(cfg: Config, site: Site, args: list[str]) -> tuple[bool, Callable[[dict], str] | None]:
    args = list(args[1:]) if args[:1] == ["wp"] else list(args)
    try:
        cmd = wpcli.validate(site, list(args))
    except (SandboxError, ValueError):
        return False, None  # the real call will raise the proper error
    if cmd not in CHECKED:
        return False, None
    slugs = _slugs(args, cmd)

    if cmd in (("plugin", "update"), ("theme", "update")):
        kind = "plugins" if cmd[0] == "plugin" else "themes"
        if "--all" in args:
            r = wpcli.run(cfg, site, [cmd[0], "list", "--update=available", "--field=name"])
            slugs = r["stdout"].split() if r["exit_code"] == 0 else []
        saved = _backup_dirs(cfg, site, kind, slugs)
        if not saved:
            return True, None

        def undo(result: dict) -> str:
            for backup_id, rel in saved:
                files.restore_backup(cfg, site, backup_id, rel)
            names = ", ".join(rel.rsplit("/", 1)[-1] for _, rel in saved)
            return (f"put back the previous files of {names}. Database changes made by the update "
                    "(if any) are not reversed.")
        return True, undo

    if cmd == ("plugin", "activate") and slugs and "--all" not in args:
        return True, lambda r: (_wp_ok(cfg, site, ["plugin", "deactivate", *slugs]),
                                f"deactivated {', '.join(slugs)} again")[1]
    if cmd == ("plugin", "deactivate") and slugs and "--all" not in args:
        return True, lambda r: (_wp_ok(cfg, site, ["plugin", "activate", *slugs]),
                                f"activated {', '.join(slugs)} again")[1]

    if cmd in (("theme", "activate"), ("theme", "install")):
        prev = wpcli.run(cfg, site, ["option", "get", "stylesheet"])
        previous = prev["stdout"].strip() if prev["exit_code"] == 0 else ""
        new_dirs = [s for s in slugs if not ((_content_dir(site, "themes") or Path("/nonexistent")) / s).exists()]

        def undo_theme(result: dict) -> str:
            done = []
            if previous and (cmd == ("theme", "activate") or "--activate" in args):
                _wp_ok(cfg, site, ["theme", "activate", previous])
                done.append(f"switched back to the theme {previous}")
            if cmd == ("theme", "install"):
                done += _trash_new(cfg, site, "themes", new_dirs)
            return "; ".join(done) or "nothing to undo"
        return True, undo_theme

    if cmd == ("plugin", "install"):
        new_dirs = [s for s in slugs if not ((_content_dir(site, "plugins") or Path("/nonexistent")) / s).exists()]

        def undo_install(result: dict) -> str:
            done = []
            if "--activate" in args and new_dirs:
                wpcli.run(cfg, site, ["plugin", "deactivate", *new_dirs, *SAFE])
                done.append(f"deactivated {', '.join(new_dirs)}")
            done += _trash_new(cfg, site, "plugins", new_dirs)
            return "; ".join(done) or "nothing to undo"
        return True, undo_install

    if cmd == ("option", "update") and slugs:
        name = slugs[0]
        old = wpcli.run(cfg, site, ["option", "get", name])
        if old["exit_code"] != 0:
            return True, None
        old_value = old["stdout"].rstrip("\n")
        return True, lambda r: (_wp_ok(cfg, site, ["option", "update", name, old_value]),
                                f"set the option {name} back to its previous value")[1]

    return True, None  # core update, cron run, rewrite flush, languages: checked, not undoable


def _trash_new(cfg: Config, site: Site, kind: str, slugs: list[str]) -> list[str]:
    base = _content_dir(site, kind)
    out = []
    for slug in slugs:
        d = base / slug if base else None
        rel = _rel_in_site(site, d) if d and d.exists() else None
        if rel:
            t = files.trash(cfg, site, rel)
            out.append(f"moved {rel} to the trash ({t['trash_id']})")
    return out

