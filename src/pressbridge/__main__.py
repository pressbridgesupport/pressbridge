"""Command line entry point.

    pressbridge serve --config config.yaml              # stdio (Claude Desktop / Claude Code, local)
    pressbridge serve --config config.yaml --http       # HTTPS-ready HTTP server (Pro)
    pressbridge check --config config.yaml              # validate config and WP-CLI access
    pressbridge token                                   # print a new random token
    pressbridge watch run|daemon|status|report|test-alert   # security watch (Agent)
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys

from . import __version__
from .config import ConfigError, load_config
from .edition import EDITION


def _cmd_check(cfg) -> int:
    from . import wpcli

    ok = True
    print(f"PressBridge {__version__} ({EDITION})")
    print(f"Data dir: {cfg.data_dir}")
    if not shutil.which(cfg.wp_bin):
        print(f"  ! WP-CLI '{cfg.wp_bin}' not found on PATH")
        ok = False
    for s in cfg.sites.values():
        print(f"- {s.name}: root={s.root} mode={s.mode} wp={s.wp_path or 'none'} profile={s.wp_profile}")
        if s.wp_path and shutil.which(cfg.wp_bin):
            r = wpcli.run(cfg, s, ["core", "version"])
            if r["exit_code"] == 0:
                print(f"    WordPress {r['stdout'].strip()}")
            else:
                ok = False
                print(f"    ! WP-CLI failed: {r['stderr'].strip()[:300]}")
    print("OK" if ok else "Problems found")
    return 0 if ok else 1


def _cmd_watch(cfg, a) -> int:
    if EDITION != "agent":
        print("PressBridge Watch is part of PressBridge Agent (https://pressbridgesupport.github.io/pressbridge).", file=sys.stderr)
        return 2
    from .watch import parse_settings
    from .watch import runner

    try:
        settings = parse_settings(cfg.watch)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    if a.watch_cmd == "status":
        print(runner.status(cfg, settings))
        return 0
    if a.watch_cmd == "report":
        p = runner.watch_dir(cfg) / "reports" / "latest.txt"
        print(p.read_text() if p.exists() else "No report yet. Run: pressbridge watch run")
        return 0
    if a.watch_cmd == "test-alert":
        errors = runner.test_alert(settings)
        for e in errors:
            print(f"! {e}", file=sys.stderr)
        if not errors:
            print("Test alert sent.")
        return 1 if errors else 0
    if a.watch_cmd == "daemon":
        try:
            runner.daemon(cfg, settings, run_now=a.now, log=lambda m: print(m, flush=True))
        except KeyboardInterrupt:
            pass
        return 0

    try:
        result = runner.run_once(cfg, settings, sites=a.site, notify=not a.no_notify,
                                 use_claude=not a.no_claude, force_notify=a.notify_always,
                                 save=not a.dry_run)
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    print(result.report_path.read_text() if result.report_path else "")
    if result.notified:
        print("Alert sent.")
    for e in result.delivery_errors:
        print(f"! Alert delivery failed: {e}", file=sys.stderr)
    return result.exit_code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pressbridge", description="Safe WordPress access for Claude")
    p.add_argument("--version", action="version", version=f"pressbridge {__version__} ({EDITION})")
    sub = p.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run the MCP server")
    serve.add_argument("--config", default=os.environ.get("PRESSBRIDGE_CONFIG", "/config/config.yaml"))
    serve.add_argument("--http", action="store_true", help="Serve over HTTP instead of stdio (Pro)")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PRESSBRIDGE_PORT", "8765")))
    serve.add_argument("--host", default=os.environ.get("PRESSBRIDGE_HOST", "0.0.0.0"),
                       help="Interface to bind in HTTP mode (use 127.0.0.1 behind a proxy on the host network)")

    check = sub.add_parser("check", help="Validate the config and WP-CLI access")
    check.add_argument("--config", default=os.environ.get("PRESSBRIDGE_CONFIG", "/config/config.yaml"))

    sub.add_parser("token", help="Generate a random bearer token")

    watch = sub.add_parser("watch", help="Security watch: nightly checks and alerts (Agent edition)")
    watch.add_argument("--config", default=os.environ.get("PRESSBRIDGE_CONFIG", "/config/config.yaml"))
    wsub = watch.add_subparsers(dest="watch_cmd", required=True)
    w_run = wsub.add_parser("run", help="Check all sites once now")
    w_run.add_argument("--site", action="append", help="Only this site (repeatable)")
    w_run.add_argument("--no-notify", action="store_true", help="Don't send alerts")
    w_run.add_argument("--no-claude", action="store_true", help="Skip Claude's review")
    w_run.add_argument("--notify-always", action="store_true", help="Send the report even if all is clear")
    w_run.add_argument("--dry-run", action="store_true", help="Don't save the new baseline (compare only)")
    w_daemon = wsub.add_parser("daemon", help="Run on the schedule, forever (for Docker or systemd)")
    w_daemon.add_argument("--now", action="store_true", help="Also run once at start")
    wsub.add_parser("status", help="Show the last run, the next run and each site's baseline")
    wsub.add_parser("test-alert", help="Send a test alert to every configured channel")
    wsub.add_parser("report", help="Print the latest report")

    a = p.parse_args(argv)
    if a.cmd == "token":
        print(secrets.token_hex(32))
        return 0

    try:
        cfg = load_config(a.config)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    if a.cmd == "check":
        return _cmd_check(cfg)

    if a.cmd == "watch":
        return _cmd_watch(cfg, a)

    if a.http:
        if EDITION == "free":
            print("HTTP mode is a PressBridge Pro feature. Free runs over stdio.", file=sys.stderr)
            return 2
        import uvicorn

        from .server import build_http_app

        try:
            app = build_http_app(cfg)
        except ConfigError as e:
            print(f"Config error: {e}", file=sys.stderr)
            return 2
        uvicorn.run(app, host=a.host, port=a.port, log_level="info", proxy_headers=True,
                    forwarded_allow_ips="*")
        return 0

    from .server import build_server

    build_server(cfg).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
