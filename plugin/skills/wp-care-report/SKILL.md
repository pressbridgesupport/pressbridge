---
name: wp-care-report
description: Use when the user asks for a site health check, security check, maintenance or care-plan report, or a monthly client report for one or more WordPress sites managed through PressBridge. Produces a client-ready report without changing anything.
---

# WordPress care-plan report with PressBridge

Read-only. Never change anything while building a report, even on maintenance sites.

## Gather, for each site the user names (or every site from `list_sites`)

1. `site_overview`: WordPress version, pending core/plugin/theme updates.
2. Integrity: `["core", "verify-checksums"]` and
   `["plugin", "verify-checksums", "--all", "--format=json"]`. Modified core files are a
   red flag (possible hack). Premium plugins without checksums are normal; say so.
   "File should not exist: wp-config-docker.php" is normal on the official WordPress
   Docker image and is not a sign of compromise. Other unexpected files in the
   WordPress root are worth flagging.
3. Inactive plugins and themes (`status` in the overview). Unused code is attack surface.
4. Admin accounts: `["user", "list", "--role=administrator", "--format=json"]`. Flag
   generic logins like `admin`, `test`, or more than 3 admins.
5. `["cron", "event", "list", "--format=json", "--fields=hook,next_run_relative"]`:
   overdue events mean WP-Cron isn't running.
6. `["db", "size", "--format=json"]` and `["option", "get", "blog_public"]`
   (0 on a live site means it is hidden from search engines; usually a mistake).
7. Suspicious files: `search` for `eval\(base64_decode|gzinflate\(base64|\$_(POST|REQUEST)\[.{0,40}\]\(`
   in `wp-content`, `glob="*.php"`. And `list_dir` of `wp-content/uploads` with depth 2:
   `.php` files inside uploads are a strong sign of compromise.

## Write the report

For a client (plain language, no jargon), one section per site:

- **Status:** Good / Needs attention / Urgent, with one sentence why.
- **Updates waiting:** count and the important ones.
- **Security:** integrity result, admin accounts, anything suspicious.
- **Housekeeping:** inactive plugins/themes to remove, cron, search visibility.
- **What we recommend this month:** at most 5 actions, most important first.

Then, separately for the agency: the exact WP-CLI commands to carry out the
recommendations, so they can be run with the `wp-safe-updates` skill.

If anything looks like a hack (modified core files, PHP in uploads, obfuscated code),
put it at the top, say "possible compromise", and recommend not editing the site
further until it has been investigated.
