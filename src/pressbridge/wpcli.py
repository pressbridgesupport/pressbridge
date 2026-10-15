"""Whitelisted WP-CLI execution.

Claude never gets a shell. It sends a list of WP-CLI arguments; the command
is matched against an allow-list for the site's profile, risky flags are
refused, and the command is run without a shell, with --path pinned to the
site's install.
"""
from __future__ import annotations

import os
import subprocess

from .config import Config, Site
from .edition import EDITION
from .sandbox import SandboxError

# Commands available on every site (they only read).
READONLY: dict[tuple[str, ...], str] = {
    ("cli", "version"): "WP-CLI version",
    ("core", "version"): "WordPress version",
    ("core", "check-update"): "Available core updates",
    ("core", "verify-checksums"): "Check core files against wordpress.org checksums",
    ("plugin", "list"): "List plugins (try --update=available)",
    ("plugin", "get"): "Plugin details",
    ("plugin", "status"): "Plugin status",
    ("plugin", "verify-checksums"): "Check plugin files against wordpress.org checksums",
    ("theme", "list"): "List themes",
    ("theme", "get"): "Theme details",
    ("theme", "status"): "Theme status",
    ("option", "get"): "Read one option (secret-looking options are blocked)",
    ("post", "list"): "List posts/pages (use --post_type=page)",
    ("post", "get"): "Read one post",
    ("post-type", "list"): "List post types",
    ("term", "list"): "List terms of a taxonomy",
    ("menu", "list"): "List menus",
    ("user", "list"): "List users",
    ("role", "list"): "List roles",
    ("cron", "event", "list"): "List scheduled cron events",
    ("cache", "type"): "Object cache type",
    ("rewrite", "list"): "List rewrite rules",
    ("db", "size"): "Database size",
    ("db", "check"): "Check database tables",
    ("site", "list"): "List sites (multisite)",
    ("maintenance-mode", "status"): "Is maintenance mode on",
    ("language", "core", "list"): "Installed core languages",
    ("search-replace",): "Search/replace in the database (--dry-run required on this profile)",
}

# Extra commands for sites with wp_profile: maintenance.
MAINTENANCE: dict[tuple[str, ...], str] = {
    ("plugin", "activate"): "Activate a plugin",
    ("plugin", "deactivate"): "Deactivate a plugin",
    ("plugin", "update"): "Update plugins",
    ("plugin", "install"): "Install a plugin from wordpress.org",
    ("plugin", "auto-updates", "enable"): "Turn on plugin auto-updates",
    ("plugin", "auto-updates", "disable"): "Turn off plugin auto-updates",
    ("theme", "activate"): "Activate a theme",
    ("theme", "update"): "Update themes",
    ("theme", "install"): "Install a theme from wordpress.org",
    ("core", "update"): "Update WordPress core",
    ("core", "update-db"): "Run the database upgrade after a core update",
    ("cache", "flush"): "Flush the object cache",
    ("transient", "delete"): "Delete transients",
    ("rewrite", "flush"): "Flush rewrite rules",
    ("cron", "event", "run"): "Run a cron event now",
    ("post", "create"): "Create a post or page",
    ("post", "update"): "Update a post or page",
    ("option", "update"): "Update one option (protected options are blocked)",
    ("maintenance-mode", "activate"): "Turn on maintenance mode",
    ("maintenance-mode", "deactivate"): "Turn off maintenance mode",
    ("language", "core", "install"): "Install a core language",
    ("language", "core", "update"): "Update core languages",
}

# Flags that could run arbitrary code, reach other hosts, or change the target.
FORBIDDEN_FLAGS = {"--exec", "--require", "--path", "--ssh", "--http", "--context", "--prompt"}

SECRET_HINTS = ("pass", "secret", "token", "key", "salt", "auth", "license", "smtp", "api")
PROTECTED_OPTIONS = {
    "siteurl", "home", "admin_email", "users_can_register", "default_role",
    "active_plugins", "template", "stylesheet", "wp_user_roles", "new_admin_email",
}

MAX_OUTPUT = 100_000


def allowed_commands(site: Site) -> dict[tuple[str, ...], str]:
    cmds = dict(READONLY)
    if site.wp_profile == "maintenance":
        cmds.update(MAINTENANCE)
    return cmds


def _positionals(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def match_command(site: Site, args: list[str]) -> tuple[str, ...]:
    pos = _positionals(args)
    cmds = allowed_commands(site)
    for n in (3, 2, 1):
        key = tuple(pos[:n])
        if len(key) == n and key in cmds:
            return key
    shown = " ".join(pos[:3]) or "(empty)"
    hint = ""
    if site.wp_profile == "readonly" and any(
        tuple(pos[:n]) in MAINTENANCE for n in (2, 3)
    ):
        hint = (" Changes like this need PressBridge Pro (https://pressbridge.dev)." if EDITION == "free"
                else " It needs `wp_profile: maintenance` on this site.")
    raise SandboxError(f"`wp {shown}` is not on the allow-list.{hint} Call wp_commands to see what is allowed.")


def validate(site: Site, args: list[str]) -> tuple[str, ...]:
    if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
        raise ValueError("args must be a non-empty list of strings, e.g. [\"plugin\", \"list\"]")
    if len(args) > 40 or any(len(a) > 20_000 for a in args):
        raise ValueError("Too many or too long arguments")
    for a in args:
        if "\x00" in a:
            raise ValueError("Null byte in arguments")
        if a.startswith("-"):
            flag = a.split("=", 1)[0]
            if flag in FORBIDDEN_FLAGS:
                raise SandboxError(f"Flag {flag} is not allowed")
    cmd = match_command(site, args)
    pos = _positionals(args)

    if cmd == ("search-replace",) and site.wp_profile != "maintenance" and "--dry-run" not in args:
        raise SandboxError("search-replace needs --dry-run on a readonly site")
    if cmd in (("search-replace",),) and any(a.startswith("--export") for a in args):
        raise SandboxError("--export is not allowed")
    if cmd in (("option", "get"), ("option", "update")):
        name = pos[2].lower() if len(pos) > 2 else ""
        if not name:
            raise ValueError("Give the option name, e.g. [\"option\", \"get\", \"blogname\"]")
        if cmd == ("option", "get") and any(h in name for h in SECRET_HINTS):
            raise SandboxError(f"Option '{name}' looks like it holds a secret, so it is blocked")
        if cmd == ("option", "update") and (name in PROTECTED_OPTIONS or any(h in name for h in SECRET_HINTS)):
            raise SandboxError(f"Option '{name}' is protected and cannot be changed through PressBridge")
    if cmd in (("plugin", "install"), ("theme", "install")):
        targets = pos[2:]
        if any("://" in t or t.endswith(".zip") for t in targets):
            raise SandboxError("Only wordpress.org slugs can be installed, not URLs or zip files")
    if cmd == ("user", "list") and not any(a.startswith("--fields") for a in args):
        args.append("--fields=ID,user_login,display_name,roles")
    return cmd


# Environment variables WordPress itself may read in wp-config.php (the official Docker
# image reads WORDPRESS_DB_* through getenv). Everything else, including PressBridge's
# own tokens, is kept away from WP-CLI.
ENV_PREFIXES = ("WORDPRESS_", "WP_", "DB_", "MYSQL_", "MARIADB_")
ENV_BLOCK = ("PB_", "PRESSBRIDGE_")


def wp_environment(cfg: Config) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items()
        if k.startswith(ENV_PREFIXES) or k in cfg.wp_env
    }
    env = {k: v for k, v in env.items() if not k.startswith(ENV_BLOCK)}
    env.update({
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "WP_CLI_CACHE_DIR": str(cfg.data_dir / "wp-cli-cache"),
        "WP_CLI_DISABLE_AUTO_CHECK_UPDATE": "1",
        "PAGER": "cat",
    })
    return env


def run(cfg: Config, site: Site, args: list[str]) -> dict:
    if site.wp_path is None:
        raise SandboxError(
            f"Site '{site.name}' has no WordPress install configured (set `wp_path`)."
        )
    args = list(args)
    if args and args[0] == "wp":
        args = args[1:]
    cmd = validate(site, args)

    full = [cfg.wp_bin, *args, f"--path={site.wp_path}", "--no-color"]
    if site.wp_url and not any(a.startswith("--url") for a in args):
        full.append(f"--url={site.wp_url}")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        full.append("--allow-root")

    env = wp_environment(cfg)
    try:
        proc = subprocess.run(
            full,
            capture_output=True,
            text=True,
            timeout=cfg.wp_timeout,
            env=env,
            cwd=str(site.wp_path),
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise RuntimeError(f"WP-CLI binary '{cfg.wp_bin}' was not found") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"WP-CLI timed out after {cfg.wp_timeout}s") from None

    out, err = proc.stdout, proc.stderr
    truncated = len(out) > MAX_OUTPUT
    return {
        "command": "wp " + " ".join(cmd),
        "exit_code": proc.returncode,
        "stdout": out[:MAX_OUTPUT],
        "stderr": err[:10_000],
        "truncated": truncated,
    }
