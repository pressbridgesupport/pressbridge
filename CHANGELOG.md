# Changelog

## 1.1.0 — 2026-10

New: **PressBridge Watch** (Agent edition), a nightly security agent.

- Checks every site on a schedule: new administrators, PHP in uploads, backdoor-like
  code, core and plugin checksum failures, changed core/must-use/plugin/theme files,
  wp-config.php/.htaccess/.user.ini changes, risky settings (open admin registration,
  site URL), user sign-up surges, new cron tasks, and whether WordPress loads at all.
- Compares with the previous night; plugin/theme/core updates and changes made through
  PressBridge are recognised and not treated as alarms.
- Optional Claude review with read-only tools; it can't hide or downgrade findings.
- Alerts by email, Slack, Discord, ntfy (phone push) or any webhook; weekly all-clear.
- `pressbridge watch run|daemon|status|report|test-alert`, a read-only
  `pressbridge-watch` Docker service, and `security_scan` / `watch_report` chat tools.

## 1.0.1 — 2026-10

Fixes from testing on a real server with WordPress in Docker.

- WP-CLI now receives `WORDPRESS_*`, `WP_*`, `DB_*`, `MYSQL_*` and `MARIADB_*`
  environment variables, so sites whose `wp-config.php` reads its database settings
  from the environment (the official WordPress image) connect correctly. PressBridge's
  own `PB_*` / `PRESSBRIDGE_*` variables are never passed on.
- New `wp_env` config option to pass extra variable names to WP-CLI.
- The audit log records the site name when Claude doesn't pass one.
- PHP syntax errors are reported once instead of twice.

## 1.0.0 — 2026-10

First release.

- File tools: list, read, search, stat, write, edit, move, trash
- Per-site read/write modes and deny rules; secrets hidden by default
- Backups outside the webroot and one-call restore
- PHP syntax check before saving
- Whitelisted WP-CLI with readonly and maintenance profiles
- `site_overview` health snapshot
- Audit log (JSON Lines) and `audit_log` tool
- HTTP transport with bearer tokens and DNS-rebinding protection; stdio and SSH modes
- Docker image with WP-CLI, compose files for host and Docker WordPress, Caddy HTTPS
- Claude skills: wp-safe-edit, wp-safe-updates, wp-care-report
