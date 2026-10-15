# Security model

PressBridge assumes the AI can make mistakes and that a prompt hidden in a web page,
a plugin readme or a comment could try to trick it. The server, not the AI, enforces
the limits below.

## What Claude can never do

- Run shell commands or arbitrary PHP (`wp eval`, `eval-file`, `shell`, `--exec`, `--require` are refused).
- Read or write outside a configured site folder. Paths are resolved with symlinks
  followed, then checked against the site root.
- See secrets. Hidden by default at any depth: `wp-config*`, `.env*`, `.htpasswd`,
  `.git`, `*.sql`, `*.sql.gz`, `*.sqlite*`, `*.key`, `*.pem`, `id_rsa*`, `*.wpress`,
  `backup*.zip`, `debug.log`. They do not appear in listings or search results either.
- Read options that look like secrets (`*pass*`, `*key*`, `*token*`, `*secret*`, `*smtp*` …).
- Change `siteurl`, `home`, `admin_email`, `default_role`, `users_can_register`,
  `active_plugins` and similar through `option update`.
- Create, promote or delete users, run SQL, export or import the database, read
  `wp config`.
- Install plugins or themes from URLs or zip files (wordpress.org slugs only).
- Point WP-CLI at another install (`--path`, `--ssh`, `--http` are refused).
- Delete anything. `trash` moves files outside the webroot.

## What protects changes

- Every write, edit, move or trash first copies the original to
  `data_dir/backups/<site>/<timestamp>/`, outside the webroot.
- PHP files are checked with `php -l` before they are saved. A file that does not
  parse is never written.
- Writes are atomic (temp file + rename): visitors never see a half-written file.
- Per-site `mode: read` makes a site fully read-only.

## Transport

- HTTP mode will not start without a token (minimum 24 characters, compared in
  constant time). Use one token per person/device; remove a line to revoke.
- Use HTTPS (the included Caddy setup gets a Let's Encrypt certificate). Only `/mcp`
  and `/health` are published.
- `allowed_hosts` enables DNS-rebinding protection.
- The SSH method opens no port at all.

## Audit

Every tool call is appended to `data_dir/audit.jsonl` with time, site, arguments
(long values shortened) and result. File contents are not logged in full.

## What you are still responsible for

- `search-replace` and `post update` on a maintenance site change the database.
  Take your normal database backups.
- Plugin updates can break sites. Use the included update skill, which updates
  one plugin at a time and checks the site after each.
- Keep the token secret. Anyone with it has the access you configured.

## Reporting a vulnerability

Email pressbridge.support@gmail.com. Please don't open a public issue.
