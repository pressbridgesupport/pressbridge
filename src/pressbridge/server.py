"""MCP server: exposes PressBridge operations as tools for Claude."""
from __future__ import annotations

import functools
import hmac
import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__, audit, files, wpcli
from .config import Config, ConfigError
from .edition import EDITION
from .sandbox import SandboxError

INSTRUCTIONS = """\
PressBridge gives you sandboxed access to the WordPress sites listed by list_sites.
Paths are relative to each site's root. Secrets (wp-config.php, .env, keys, SQL dumps)
are blocked on purpose; do not try to work around the blocks.
Before changing a file, read it. Prefer edit_file over write_file for small changes.
Every change is backed up; tell the user the backup_id so they can undo it.
For WP-CLI, call wp_commands first to see what this site allows, then call wp
with a list of arguments, without the leading "wp".
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


def _summary(result: Any) -> dict | None:
    if not isinstance(result, dict):
        return None
    keep = ("path", "bytes", "backup_id", "trash_id", "exit_code", "command", "replacements", "restored")
    return {k: result[k] for k in keep if k in result} or None


def build_server(cfg: Config) -> MCPServer:
    server = MCPServer(
        name="pressbridge",
        title="PressBridge for WordPress",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://pressbridge.dev",
    )

    def audited(tool_name: str):
        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                site_name = kwargs.get("site")
                if site_name is None and len(cfg.sites) == 1 and tool_name != "list_sites":
                    site_name = next(iter(cfg.sites))
                try:
                    result = fn(*args, **kwargs)
                except (SandboxError, ConfigError, FileNotFoundError, FileExistsError,
                        IsADirectoryError, NotADirectoryError, ValueError, RuntimeError,
                        UnicodeDecodeError) as e:
                    audit.record(cfg.audit_log, tool=tool_name, site=site_name, args=kwargs, ok=False, error=str(e))
                    raise ToolError(str(e)) from e
                audit.record(cfg.audit_log, tool=tool_name, site=site_name, args=kwargs, ok=True,
                             result_summary=_summary(result))
                return result
            return wrapper
        return deco

    # ---------- read tools (all editions) ----------

    @server.tool(annotations=READ_ONLY)
    @audited("list_sites")
    def list_sites() -> dict:
        """List the WordPress sites you can work on, with what each one allows."""
        return {
            "edition": EDITION,
            "sites": [
                {
                    "site": s.name,
                    "mode": s.mode,
                    "wordpress": bool(s.wp_path),
                    "wp_profile": s.wp_profile if s.wp_path else None,
                    "url": s.wp_url,
                }
                for s in cfg.sites.values()
            ],
        }

    @server.tool(annotations=READ_ONLY)
    @audited("list_dir")
    def list_dir(path: str = ".", depth: int = 1, site: str | None = None) -> dict:
        """List a folder inside a site. depth 1-4. Blocked files are hidden."""
        return files.list_dir(cfg, cfg.site(site), path, depth)

    @server.tool(annotations=READ_ONLY)
    @audited("read_file")
    def read_file(path: str, offset: int = 1, limit: int = 2000, site: str | None = None) -> dict:
        """Read a text file. offset is the first line (1-based), limit the number of lines."""
        return files.read_file(cfg, cfg.site(site), path, offset, limit)

    @server.tool(annotations=READ_ONLY)
    @audited("search")
    def search(pattern: str, path: str = ".", glob: str | None = None, max_results: int = 100,
               ignore_case: bool = False, site: str | None = None) -> dict:
        """Regex search across files (like grep). glob filters file names, e.g. '*.php'."""
        return files.search(cfg, cfg.site(site), pattern, path, glob, max_results, ignore_case)

    @server.tool(annotations=READ_ONLY)
    @audited("stat")
    def stat(path: str, site: str | None = None) -> dict:
        """Size, permissions and modified time of a file or folder."""
        return files.stat(cfg, cfg.site(site), path)

    @server.tool(annotations=READ_ONLY)
    @audited("wp_commands")
    def wp_commands(site: str | None = None) -> dict:
        """Show which WP-CLI commands this site allows."""
        s = cfg.site(site)
        if not s.wp_path:
            return {"site": s.name, "wordpress": False, "commands": []}
        return {
            "site": s.name,
            "profile": s.wp_profile,
            "commands": [{"command": "wp " + " ".join(k), "what": v} for k, v in wpcli.allowed_commands(s).items()],
        }

    @server.tool(annotations=WRITES)
    @audited("wp")
    def wp(args: list[str], site: str | None = None) -> dict:
        """Run an allowed WP-CLI command. args without 'wp', e.g. ["plugin", "list", "--update=available"]."""
        return wpcli.run(cfg, cfg.site(site), args)

    @server.tool(annotations=READ_ONLY)
    @audited("site_overview")
    def site_overview(site: str | None = None) -> dict:
        """One-call health snapshot: WordPress version, pending updates, plugins and themes."""
        s = cfg.site(site)
        if not s.wp_path:
            raise ConfigError(f"Site '{s.name}' has no WordPress install configured")
        out: dict[str, Any] = {"site": s.name}
        checks = {
            "core_version": ["core", "version"],
            "core_updates": ["core", "check-update", "--format=json"],
            "plugins": ["plugin", "list", "--format=json", "--fields=name,status,version,update_version"],
            "themes": ["theme", "list", "--format=json", "--fields=name,status,version,update_version"],
        }
        for key, args in checks.items():
            r = wpcli.run(cfg, s, args)
            if r["exit_code"] != 0:
                out[key] = {"error": r["stderr"].strip()}
                continue
            text = r["stdout"].strip()
            try:
                out[key] = json.loads(text) if text[:1] in "[{" else text
            except json.JSONDecodeError:
                out[key] = text
        return out

    if EDITION == "free":
        return server

    # ---------- write tools (Pro) ----------

    @server.tool(annotations=WRITES)
    @audited("write_file")
    def write_file(path: str, content: str, create_dirs: bool = False, site: str | None = None) -> dict:
        """Create or overwrite a file. The old version is backed up first."""
        return files.write_file(cfg, cfg.site(site), path, content, create_dirs)

    @server.tool(annotations=WRITES)
    @audited("edit_file")
    def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False,
                  site: str | None = None) -> dict:
        """Replace exact text in a file. old_text must match once unless replace_all is true."""
        return files.edit_file(cfg, cfg.site(site), path, old_text, new_text, replace_all)

    @server.tool(annotations=WRITES)
    @audited("move")
    def move(source: str, destination: str, site: str | None = None) -> dict:
        """Move or rename a file or folder inside the same site."""
        return files.move(cfg, cfg.site(site), source, destination)

    @server.tool(annotations=DESTRUCTIVE)
    @audited("trash")
    def trash(path: str, site: str | None = None) -> dict:
        """Move a file or folder to the trash outside the webroot (restorable)."""
        return files.trash(cfg, cfg.site(site), path)

    @server.tool(annotations=READ_ONLY)
    @audited("list_backups")
    def list_backups(path: str | None = None, limit: int = 50, site: str | None = None) -> dict:
        """List backups and trashed items, newest first. Filter by path prefix."""
        return files.list_backups(cfg, cfg.site(site), path, limit)

    @server.tool(annotations=WRITES)
    @audited("restore_backup")
    def restore_backup(backup_id: str, path: str, site: str | None = None) -> dict:
        """Put a backed-up or trashed file back. The current version is backed up first."""
        return files.restore_backup(cfg, cfg.site(site), backup_id, path)

    @server.tool(annotations=READ_ONLY)
    @audited("audit_log")
    def audit_log(limit: int = 50, site: str | None = None) -> dict:
        """Recent PressBridge activity, newest first."""
        return {"entries": audit.tail(cfg.audit_log, max(1, min(limit, 500)), site)}

    if EDITION != "agent":
        return server

    # ---------- security watch (Agent) ----------
    from .watch import parse_settings
    from .watch import runner as watch_runner

    @server.tool(annotations=READ_ONLY)
    @audited("security_scan")
    def security_scan(site: str | None = None) -> dict:
        """Security check now: compares the site with the last nightly baseline (new admins, PHP in
        uploads, changed core files, backdoor-like code, ...). Doesn't save a baseline or send alerts."""
        s = cfg.site(site)
        settings = parse_settings(cfg.watch)
        r = watch_runner.scan_site(cfg, settings, s, save=False, use_claude=False)
        if r.error:
            raise RuntimeError(f"Scan failed: {r.error}")
        return {
            "site": s.name,
            "compared_with": "nothing (no baseline yet: this is a first scan)" if r.baseline else "last nightly baseline",
            "counts": r.counts(),
            "findings": [f.to_dict() for f in r.findings],
            "still_open": r.still_open,
            "files_watched": r.files_watched,
        }

    @server.tool(annotations=READ_ONLY)
    @audited("watch_report")
    def watch_report() -> dict:
        """The latest nightly security report, as sent to the alert channels."""
        p = watch_runner.watch_dir(cfg) / "reports" / "latest.txt"
        return {"report": p.read_text() if p.exists() else "No watch report yet."}

    return server


class BearerAuth:
    """ASGI middleware: requires `Authorization: Bearer <token>` except on /health."""

    def __init__(self, app, tokens: list[str]):
        self.app = app
        self.tokens = [t.encode() for t in tokens]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            return await self.app(scope, receive, send)
        header = dict(scope.get("headers") or []).get(b"authorization", b"")
        token = header[7:].strip() if header[:7].lower() == b"bearer " else b""
        if token and any(hmac.compare_digest(token, t) for t in self.tokens):
            return await self.app(scope, receive, send)
        body = b'{"error":"unauthorized"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
        })
        await send({"type": "http.response.body", "body": body})


def build_http_app(cfg: Config):
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.responses import JSONResponse

    if not cfg.tokens:
        raise ConfigError("HTTP mode needs at least one entry in `tokens` (refusing to run unauthenticated)")
    server = build_server(cfg)

    @server.custom_route("/health", methods=["GET"])
    async def health(request):  # noqa: ARG001
        return JSONResponse({"ok": True, "version": __version__})

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(cfg.allowed_hosts),
        allowed_hosts=cfg.allowed_hosts,
        allowed_origins=[f"https://{h}" for h in cfg.allowed_hosts],
    )
    app = server.streamable_http_app(transport_security=security, host="0.0.0.0")
    return BearerAuth(app, cfg.tokens)
