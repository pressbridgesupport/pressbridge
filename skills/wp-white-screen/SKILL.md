---
name: wp-white-screen
description: Use when a WordPress site managed through PressBridge shows "There has been a critical error on this website", a white screen, an HTTP 500, or stopped working after an update. Finds the cause without changing anything and gives the exact fix.
---

# Diagnose a WordPress white screen with PressBridge

Read-only. Find the cause, then give the user the exact fix.

## Find the cause

1. `check_site_health` for the site. The `wp-cli` check usually carries the PHP fatal
   error with file and line. A page check with HTTP 500 and a WordPress-loads `wp-cli`
   check points at the theme front end or a `template_redirect` hook.
2. If the error names a file under `wp-content/plugins/<slug>/` or `wp-content/themes/<slug>/`,
   that plugin or theme is the suspect. `read_file` around the line it names.
3. `wp` with `["plugin", "list", "--format=json", "--skip-plugins", "--skip-themes"]`:
   versions and status. A recently updated plugin is the usual culprit.
4. No error text? Compare against WordPress core with `["core", "verify-checksums"]`,
   and `search` the suspect folder for the function or class named in the error.
5. Out-of-memory or "Allowed memory size" errors point at a heavy plugin, not a code bug.

`--skip-plugins --skip-themes` lets WP-CLI run even while a plugin breaks WordPress.

## Give the fix

Tell the user, in this order:

1. What broke: the plugin or theme, its version, the file and line, the error in one line.
2. The quickest way back up, as an exact command, e.g.
   `wp plugin deactivate <slug> --skip-plugins --skip-themes`, or the exact edit (file,
   old text, new text).
3. The proper fix: roll back to the previous version, wait for a patch, or the code change.

On the Free edition you can't apply changes: give the commands and edits so the user can
run them. On Pro, apply the quick fix with `wp` or `edit_file`; PressBridge backs it up and
rolls it back automatically if the site still fails.

Never ask for or try to read `wp-config.php`, `.env` or `debug.log`: PressBridge blocks them
on purpose.
