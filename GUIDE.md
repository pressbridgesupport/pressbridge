# PressBridge — User Guide

**Let Claude work on your WordPress sites without handing it the keys to the server.**

PressBridge is a small MCP server that runs on the same machine as your WordPress
sites. Claude (Claude Code, Claude Desktop, Cursor or any MCP client) connects to it and
gets a fixed set of tools: read and search files, make edits, run allowed WP-CLI
commands, undo changes. It never gets a shell, never sees your secrets, and never
reaches outside the folders you list.

This guide covers everything: installing, configuring, connecting Claude, everyday use,
maintenance and troubleshooting. Features marked **Pro** are not in the Free edition.

---

## Contents

1. [How it works](#1-how-it-works)
2. [Editions](#2-editions)
3. [Requirements](#3-requirements)
4. [Installation](#4-installation)
   - [A. Docker, WordPress on the host](#a-docker-wordpress-on-the-host-pro)
   - [B. Docker, WordPress in Docker](#b-docker-wordpress-in-docker-pro)
   - [C. Python, no Docker](#c-python-no-docker-free-and-pro)
5. [Configuration reference](#5-configuration-reference)
6. [Connecting Claude](#6-connecting-claude)
7. [Installing the skills](#7-installing-the-skills)
8. [Using PressBridge with Claude](#8-using-pressbridge-with-claude)
9. [Tool reference](#9-tool-reference)
10. [WP-CLI allow-list](#10-wp-cli-allow-list)
11. [Command-line reference](#11-command-line-reference)
12. [Backups, trash and undo](#12-backups-trash-and-undo)
13. [Audit log](#13-audit-log)
14. [Day-to-day administration](#14-day-to-day-administration)
15. [Security model](#15-security-model)
16. [Troubleshooting](#16-troubleshooting)
17. [Uninstalling](#17-uninstalling)
18. [PressBridge Watch: the nightly security agent (Agent)](#18-pressbridge-watch-the-nightly-security-agent-agent)
19. [Support and license](#19-support-and-license)

---

## 1. How it works

```
 Your computer                          Your server
┌──────────────────┐   HTTPS + token  ┌─────────────────────────────────────┐
│ Claude Code      │ ───────────────► │ Caddy (HTTPS) ──► PressBridge :8765 │
│ Claude Desktop   │       or SSH     │                     │                │
│ Cursor, ...      │ ───────────────► │                     ├─► /var/www/... │
└──────────────────┘                  │                     ├─► WP-CLI       │
                                      │                     └─► /data        │
                                      │                        (backups, log)│
                                      └─────────────────────────────────────┘
```

- Claude asks PressBridge to do something (read a file, run `wp plugin list`).
- PressBridge checks the request against your rules: is the path inside the site? Is it
  a secret? Is the site writable? Is this WP-CLI command allowed?
- If allowed, it runs it, backs up anything it changes, logs the call, and returns the
  result. If not, Claude gets a clear refusal.

---

## 2. Editions

| Feature | Free | Pro | Agent |
|---|:-:|:-:|:-:|
| `list_sites`, `list_dir`, `read_file`, `search`, `stat` | ✓ | ✓ | ✓ |
| `site_overview`, `wp_commands`, read-only `wp` | ✓ | ✓ | ✓ |
| Number of sites | 1 | Unlimited | Unlimited |
| `write_file`, `edit_file`, `move`, `trash` | | ✓ | ✓ |
| `list_backups`, `restore_backup` (undo) | | ✓ | ✓ |
| Maintenance WP-CLI (updates, cache, options, posts) | | ✓ | ✓ |
| HTTP/HTTPS server with bearer tokens | | ✓ | ✓ |
| Docker image, Caddy HTTPS | | ✓ | ✓ |
| `audit_log` tool (the log file is written in all) | | ✓ | ✓ |
| Skills | care report | all 3 | all 3 |
| **PressBridge Watch**: nightly security checks, alerts, Claude review ([section 18](#18-pressbridge-watch-the-nightly-security-agent-agent)) | | | ✓ |
| `security_scan`, `watch_report` tools in chat | | | ✓ |

Check which edition you have:

```bash
pressbridge --version
# pressbridge 1.1.0 (pro)
```

---

## 3. Requirements

**Server**
- Linux with SSH access (Ubuntu 22.04/24.04, Debian 12 or similar)
- One of:
  - Docker 24+ with the compose plugin (`docker compose version`) — install methods A and B
  - Python 3.11+, PHP CLI and WP-CLI — install method C
- For automatic HTTPS: a domain or subdomain pointing at the server, ports 80 and 443 open

**Your computer**
- Claude Code, or Claude Desktop, or another MCP client
- For the SSH connection: an SSH key that logs in without a password prompt
- For Claude Desktop over HTTPS: Node.js 18+ (for `npx mcp-remote`)

**Not supported:** shared hosting without SSH access.

---

## 4. Installation

Pick one method. A is the most common.

### A. Docker, WordPress on the host (Pro)

For VPS servers where Apache/Nginx, PHP and MySQL are installed directly (plain Ubuntu
servers, RunCloud, Ploi, SpinupWP, GridPane, ...).

**1. Upload and unpack**

```bash
# on your computer
scp pressbridge-pro-1.1.0.zip you@server:~

# on the server
ssh you@server
unzip pressbridge-pro-1.1.0.zip
cd pressbridge
```

**2. Create your config**

```bash
cp config.example.yaml config.yaml
nano config.yaml
```

Replace the example sites with yours. Minimal example:

```yaml
data_dir: /data
tokens:
  - ${PB_TOKEN}
allowed_hosts:
  - ${PB_DOMAIN}

sites:
  acme:
    root: /var/www/acme.com/public_html
    mode: write
    wp_profile: maintenance
```

Find the right `root`: it's the folder that contains `wp-config.php`.

```bash
sudo find / -name wp-config.php -not -path "*/proc/*" 2>/dev/null
```

**3. Create the secrets file**

```bash
echo "PB_TOKEN=$(openssl rand -hex 32)" > .env
echo "PB_DOMAIN=mcp.yourdomain.com" >> .env
chmod 600 .env
cat .env
```

Copy the `PB_TOKEN` value somewhere safe (a password manager). You'll paste it into Claude.

**4. Point DNS at the server**

Create an **A record** `mcp.yourdomain.com` → your server's IP. Check it:

```bash
dig +short mcp.yourdomain.com
```

Open ports 80 and 443 if you use a firewall:

```bash
sudo ufw allow 80,443/tcp
```

**5. Set the file owner**

PressBridge must run as the user that owns your site files, so edited files keep the
right owner.

```bash
stat -c '%u:%g %U' /var/www/acme.com/public_html/wp-config.php
# 33:33 www-data      ← the default, nothing to do
```

If you see different numbers (for example `1001:1001 acme`), add them to `.env`:

```bash
echo "PUID=1001" >> .env
echo "PGID=1001" >> .env
```

Sites owned by different users? Run one PressBridge per owner, or give the common
group write access.

**6. Check the volume paths**

`docker-compose.yml` mounts `/var/www` and the MySQL socket `/var/run/mysqld`. If your
sites live elsewhere (`/home/*/webapps`, `/srv/www`), edit the volume lines so each
path is mounted at **the same path** inside the container:

```yaml
    volumes:
      - /home/runcloud/webapps:/home/runcloud/webapps
```

Check where your MySQL socket is:

```bash
mysql -e "select @@socket"     # e.g. /var/run/mysqld/mysqld.sock
```

**7. Start**

```bash
docker compose --profile tls up -d --build
```

This builds the image (1–3 minutes the first time), starts PressBridge on
`127.0.0.1:8765`, and starts Caddy, which gets a Let's Encrypt certificate for
`PB_DOMAIN`.

Already running Nginx, Caddy or Traefik on ports 80/443? Leave out `--profile tls`:

```bash
docker compose up -d --build
```

and add a reverse proxy rule to `http://127.0.0.1:8765`. Nginx example:

```nginx
location /mcp {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

**8. Verify**

```bash
docker compose exec pressbridge pressbridge check
```

Expected:

```
PressBridge 1.1.0 (pro)
Data dir: /data
- acme: root=/var/www/acme.com/public_html mode=write wp=/var/www/acme.com/public_html profile=maintenance
    WordPress 6.8.3
OK
```

```bash
curl https://mcp.yourdomain.com/health
# {"ok":true,"version":"1.1.0"}

curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.yourdomain.com/mcp
# 401   ← correct: no token, no access
```

Now [connect Claude](#6-connecting-claude).

---

### B. Docker, WordPress in Docker (Pro)

For WordPress running in containers (official `wordpress` image, Coolify, CapRover,
Dokploy, your own compose file).

**1. Find your WordPress network and files volume**

```bash
docker network ls          # e.g. mysite_default
docker volume ls           # e.g. mysite_wp_data
docker inspect <wordpress-container> --format '{{json .Mounts}}'
```

If your WordPress files are a bind mount (a host folder) rather than a named volume,
edit `docker-compose.wp-in-docker.yml` and replace `wp_files:/var/www/html` with
`/path/on/host:/var/www/html`, and delete the `wp_files` entry under `volumes:`.

**2. Config**

```bash
cp config.example.yaml config.yaml
```

```yaml
data_dir: /data
tokens:
  - ${PB_TOKEN}
sites:
  mysite:
    root: /var/www/html
    mode: write
    wp_profile: maintenance
```

**3. Secrets and database settings**

The official WordPress image reads database settings from environment variables, so
PressBridge needs the same ones:

```bash
cat > .env <<EOF
PB_TOKEN=$(openssl rand -hex 32)
WP_NETWORK=mysite_default
WP_VOLUME=mysite_wp_data
WORDPRESS_DB_HOST=db
WORDPRESS_DB_USER=wordpress
WORDPRESS_DB_PASSWORD=the-same-password-as-your-wordpress-container
WORDPRESS_DB_NAME=wordpress
EOF
chmod 600 .env
```

Copy the values from your WordPress container:

```bash
docker inspect <wordpress-container> --format '{{range .Config.Env}}{{println .}}{{end}}' | grep WORDPRESS_DB
```

**4. Start and verify**

```bash
docker compose -f docker-compose.wp-in-docker.yml up -d --build
docker compose -f docker-compose.wp-in-docker.yml exec pressbridge pressbridge check
```

PressBridge listens on `127.0.0.1:8765`. Either put it behind your reverse proxy on a
hostname (and add that hostname to `allowed_hosts`), or use the
[SSH connection](#option-2-ssh-no-open-port), which needs no proxy at all.

---

### C. Python, no Docker (Free and Pro)

Works everywhere you have SSH. Nothing listens on the network: Claude starts
PressBridge over SSH when it needs it.

**1. Install PHP and WP-CLI** (skip what you already have)

```bash
sudo apt update
sudo apt install -y python3-venv php-cli php-mysql php-xml php-mbstring
curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
sudo install -m 755 wp-cli.phar /usr/local/bin/wp
wp --info
```

**2. Install PressBridge**

Run this as the user that owns the site files (or a user in their group).

```bash
unzip pressbridge-pro-1.1.0.zip        # or pressbridge-free-1.1.0.zip
python3 -m venv ~/pressbridge-venv
~/pressbridge-venv/bin/pip install ./pressbridge
~/pressbridge-venv/bin/pressbridge --version
```

**3. Config**

```bash
mkdir -p ~/.pressbridge
nano ~/.pressbridge/config.yaml
```

```yaml
data_dir: /home/you/.pressbridge/data
sites:
  acme:
    root: /var/www/acme.com/public_html
    mode: write                 # Pro only; Free is always read-only
    wp_profile: maintenance     # Pro only
```

**4. Verify**

```bash
~/pressbridge-venv/bin/pressbridge check --config ~/.pressbridge/config.yaml
```

**5. Optional: run as an HTTP service (Pro)**

```bash
sudo tee /etc/systemd/system/pressbridge.service >/dev/null <<EOF
[Unit]
Description=PressBridge MCP server
After=network.target

[Service]
User=www-data
Environment=PB_TOKEN=paste-your-token-here
Environment=PB_DOMAIN=mcp.yourdomain.com
ExecStart=/home/you/pressbridge-venv/bin/pressbridge serve --http --host 127.0.0.1 --port 8765 --config /home/you/.pressbridge/config.yaml
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now pressbridge
systemctl status pressbridge
```

Add `tokens: ["${PB_TOKEN}"]` and `allowed_hosts: ["${PB_DOMAIN}"]` to the config, and
put a reverse proxy with HTTPS in front (see the Nginx example in method A).

---

## 5. Configuration reference

The config is one YAML file. Docker reads it from `/config/config.yaml`
(mounted from `./config.yaml`). Restart PressBridge after every change.

### Top-level keys

| Key | Default | What it does |
|---|---|---|
| `data_dir` | `/data` | Where the audit log, backups, trash and WP-CLI cache live. Must be outside every webroot. Created if missing. |
| `tokens` | none | List of bearer tokens accepted in HTTP mode. At least 24 characters each. HTTP mode refuses to start without one. |
| `allowed_hosts` | none | Hostnames clients use to reach the server. Turns on DNS-rebinding protection. Leave empty when using only SSH. |
| `wp_bin` | `wp` | WP-CLI command or full path. |
| `wp_timeout` | `120` | Seconds before a WP-CLI command is stopped. Raise it for slow core updates. |
| `wp_env` | none | Extra environment variable names to pass to WP-CLI, for `wp-config.php` files that read other `getenv()` values. Variables starting with `WORDPRESS_`, `WP_`, `DB_`, `MYSQL_` and `MARIADB_` are always passed; `PB_*` and `PRESSBRIDGE_*` never are. |
| `sites` | — | Required. One entry per site (below). |

`${NAME}` anywhere in the file is replaced with the environment variable `NAME`.
Unset variables become empty, and empty tokens or hosts are ignored.

### Site keys

| Key | Default | What it does |
|---|---|---|
| *(the key itself)* | — | The site's name, used when talking to Claude. Lowercase letters, digits, `-`, `_`. |
| `root` | — | Required. Absolute path to the folder with `wp-config.php`. Claude can't go above it. |
| `mode` | `read` | `read`: nothing can be changed. `write`: edits allowed (with backups). **Pro** |
| `wp_profile` | `readonly` | `readonly` or `maintenance`. Maintenance needs `mode: write`. **Pro** |
| `wp_path` | auto | WordPress install folder for WP-CLI. Detected automatically when `root` contains `wp-includes`. Set it for sites where WordPress is in a subfolder (e.g. `root: /var/www/site`, `wp_path: /var/www/site/wp`). |
| `wp_url` | none | The site URL. Needed for multisite; also shown to Claude. |
| `deny` | — | Extra glob patterns to hide, added to the defaults. |
| `allow` | — | Default patterns to remove from the deny list (e.g. `debug.log`). |
| `replace_default_deny` | `false` | `true` drops all default deny patterns. Not recommended. |
| `max_read_bytes` | `512000` | Maximum bytes returned by one `read_file`. |
| `max_write_bytes` | `2000000` | Maximum size of one write. |

### Default deny patterns

Hidden at any depth, in listings, searches, reads and writes:

```
wp-config*  .env  .env.*  .htpasswd  .git  .git/*  *.sql  *.sql.gz
*.sqlite  *.sqlite3  .ht.sqlite  *.wpress  backup*.zip
*.key  *.pem  id_rsa*  debug.log
```

Patterns without `/` match any single path part (`*.sql` hides `a/b/dump.sql`).
Patterns with `/` match the path from the site root (`wp-content/uploads/private/*`).

### Full example

```yaml
data_dir: /data
tokens:
  - ${PB_TOKEN}          # Paul's laptop
  - ${PB_TOKEN_ANA}      # Ana's laptop
allowed_hosts:
  - ${PB_DOMAIN}
wp_timeout: 300

sites:
  acme:                              # live shop: updates allowed
    root: /var/www/acme.com/public_html
    wp_url: https://acme.com
    mode: write
    wp_profile: maintenance
    deny:
      - "wp-content/uploads/wc-logs/*"

  acme-staging:                      # staging: same rights
    root: /var/www/staging.acme.com
    mode: write
    wp_profile: maintenance

  bistro:                            # client who only wants reports
    root: /var/www/bistro.ro/htdocs

  network:                           # multisite, WordPress in /wp
    root: /var/www/network
    wp_path: /var/www/network/wp
    wp_url: https://network.example.com
    mode: write
```

Apply changes:

```bash
docker compose restart pressbridge
docker compose exec pressbridge pressbridge check
```

---

## 6. Connecting Claude

You have two ways to connect:

| | HTTPS + token | SSH |
|---|---|---|
| Edition | Pro | Free and Pro |
| Open port | 443 | none |
| Works from | anywhere | where your SSH key is |
| Team sharing | one token per person | one SSH key per person |

### Option 1: HTTPS with a token (Pro)

**Claude Code** — one command:

```bash
claude mcp add --transport http pressbridge https://mcp.yourdomain.com/mcp \
  --header "Authorization: Bearer YOUR_PB_TOKEN"
```

Make it available in every project with `--scope user`:

```bash
claude mcp add --scope user --transport http pressbridge https://mcp.yourdomain.com/mcp \
  --header "Authorization: Bearer YOUR_PB_TOKEN"
```

Or share it with your team through the project's `.mcp.json`, with each person's token
kept in their own environment:

```json
{
  "mcpServers": {
    "pressbridge": {
      "type": "http",
      "url": "https://mcp.yourdomain.com/mcp",
      "headers": { "Authorization": "Bearer ${PRESSBRIDGE_TOKEN}" }
    }
  }
}
```

```bash
export PRESSBRIDGE_TOKEN=your-token     # add to ~/.bashrc or ~/.zshrc
```

**Claude Desktop** — Claude's "Add custom connector" screen only supports OAuth and has
no field for a token, so use the `mcp-remote` bridge. Open Settings → Developer → Edit
Config and add:

```json
{
  "mcpServers": {
    "pressbridge": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "https://mcp.yourdomain.com/mcp",
        "--header", "Authorization: Bearer YOUR_PB_TOKEN"
      ]
    }
  }
}
```

Save and restart Claude Desktop completely (quit, not just close the window).

**Cursor** — `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "pressbridge": {
      "url": "https://mcp.yourdomain.com/mcp",
      "headers": { "Authorization": "Bearer YOUR_PB_TOKEN" }
    }
  }
}
```

### Option 2: SSH, no open port

Claude starts PressBridge on the server through SSH each time it connects.

First make sure SSH works without a password prompt:

```bash
ssh-copy-id you@server        # once, if you haven't set up a key
ssh you@server true && echo OK
```

**Claude Code**

```bash
# Docker install (A or B):
claude mcp add pressbridge -- ssh you@server docker exec -i pressbridge pressbridge serve

# Python install (C):
claude mcp add pressbridge -- ssh you@server \
  /home/you/pressbridge-venv/bin/pressbridge serve --config /home/you/.pressbridge/config.yaml
```

Your SSH user must be allowed to run `docker exec` (be in the `docker` group) for the
Docker variant.

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "pressbridge": {
      "command": "ssh",
      "args": ["-o", "BatchMode=yes", "you@server",
               "docker", "exec", "-i", "pressbridge", "pressbridge", "serve"]
    }
  }
}
```

Python install:

```json
{
  "mcpServers": {
    "pressbridge": {
      "command": "ssh",
      "args": ["-o", "BatchMode=yes", "you@server",
               "/home/you/pressbridge-venv/bin/pressbridge", "serve",
               "--config", "/home/you/.pressbridge/config.yaml"]
    }
  }
}
```

On Windows, Claude Desktop uses the built-in OpenSSH client; `ssh` must work from a
normal Command Prompt.

### Checking the connection

Claude Code:

```bash
claude mcp list                  # pressbridge should show ✓ Connected
claude mcp get pressbridge       # details
claude mcp remove pressbridge    # to remove it
```

Inside a Claude Code session, type `/mcp` to see the server and its tools.

Then ask Claude:

> List my PressBridge sites.

---

## 7. Installing the skills

Skills teach Claude the safe way to do common jobs. They are in the `skills/` folder.

| Skill | Use it for | Edition |
|---|---|---|
| `wp-care-report` | Health/security check and a client-ready monthly report | Free, Pro |
| `wp-safe-edit` | Theme and code changes: child theme first, smallest change, verify, report undo ID | Pro |
| `wp-safe-updates` | Plugin/theme/core updates one at a time, stop at the first error | Pro |

**Claude Code** (on your computer):

```bash
mkdir -p ~/.claude/skills
cp -r pressbridge/skills/* ~/.claude/skills/
ls ~/.claude/skills
```

For one project only, copy them into that project's `.claude/skills/` folder instead.

**Claude Desktop / claude.ai**: zip each skill folder and upload it in the Skills
section of Claude's settings:

```bash
cd pressbridge/skills
for s in */; do (cd "$s" && zip -r "../${s%/}.zip" .); done
ls *.zip
```

Claude picks the right skill automatically from what you ask. You can also name it:
*"Use wp-care-report for all my sites."*

---

## 8. Using PressBridge with Claude

You talk to Claude normally. Name the site if you have more than one.

### Looking around

> List my sites and what each one allows.

> Give me a health overview of acme.

> On acme, which plugins have updates?

> Where in the theme is the footer copyright text set?

> Show me the last 50 lines of the active theme's functions.php.

> Find every file in acme's theme that uses `get_template_part`.

### Making changes (Pro)

> On acme-staging, change the header phone number to 0745 123 456.

> Add a CSS rule to the child theme so the cookie banner text is 14px.

> Create a must-use plugin on acme that disables XML-RPC.

> Rename `wp-content/themes/acme-child/old-footer.php` to `footer-legacy.php`.

> Remove the unused file `wp-content/themes/acme-child/test.php`.

Claude reports a `backup_id` after each change. Keep it in the conversation.

### Undoing (Pro)

> Undo the last change on acme-staging.

> Show me the backups for header.php on acme.

> Restore `wp-content/themes/acme-child/style.css` from backup 20261014T091322.418302Z.

### Maintenance (Pro, sites with `wp_profile: maintenance`)

> Update all plugins on acme-staging, one at a time, and stop if anything fails.

> Update WordPress core on acme and run the database upgrade.

> Flush the cache on acme.

> Turn on maintenance mode on acme, I'm about to deploy.

> Change the site tagline on bistro to "Bistro artizanal din Cluj".

### Reports

> Run a care report for all my sites.

> Check acme for signs of a hack.

> What did PressBridge do on acme today? (Pro)

### Tips

- **Test on staging first.** Add the staging copy as its own site with the same rights.
- **Be specific.** "In the child theme's header.php" is better than "in the header".
- **Ask Claude to read before it writes** if a change matters; the `wp-safe-edit`
  skill does this automatically.
- **Claude can't see the rendered page.** Check the result in your browser.
- **Content in the database** (pages, widgets, Customizer) isn't in files. Claude uses
  `wp post get` / `wp post update` for posts and pages on maintenance sites.

---

## 9. Tool reference

Every tool takes an optional `site`. If you configured only one site, it can be left
out. All paths are relative to the site's `root`; a leading `/` means the root.

### `list_sites`
Sites Claude can reach and what each allows.
Returns: `edition`, and per site `site`, `mode`, `wordpress`, `wp_profile`, `url`.

### `list_dir`
| Param | Default | |
|---|---|---|
| `path` | `.` | Folder to list |
| `depth` | `1` | 1–4 levels deep |

Hidden files matching deny rules are left out. `node_modules`, `vendor` and `.git` are
not descended into. At most 1000 entries (`truncated: true` if cut).

### `read_file`
| Param | Default | |
|---|---|---|
| `path` | — | File to read |
| `offset` | `1` | First line (1-based) |
| `limit` | `2000` | Number of lines (max 5000) |

Returns `content`, `start_line`, `end_line`, `total_lines`, `size`. Binary files return
`binary: true` and no content. Large files are read in pieces.

### `search`
| Param | Default | |
|---|---|---|
| `pattern` | — | Regular expression (Python syntax) |
| `path` | `.` | Folder to search in |
| `glob` | none | File name filter, e.g. `*.php`, `*.css` |
| `max_results` | `100` | Up to 500 |
| `ignore_case` | `false` | |

Skips binary files, files over 1 MB, symlinks, denied paths, `node_modules`, `vendor`,
`.git`. Returns `path`, `line`, `text` per match.

### `stat`
| Param | |
|---|---|
| `path` | File or folder |

Returns `type`, `size`, `mode` (like `-rw-r--r--`), `modified` (UTC).

### `site_overview`
No parameters besides `site`. Runs four WP-CLI commands and returns
`core_version`, `core_updates`, `plugins` and `themes` (name, status, version,
update_version).

### `wp_commands`
Lists every WP-CLI command the site allows, with a short description. Claude calls this
before using `wp` on an unfamiliar site.

### `wp`
| Param | |
|---|---|
| `args` | List of WP-CLI arguments without the leading `wp`, e.g. `["plugin", "list", "--update=available"]` |

Returns `command`, `exit_code`, `stdout` (up to 100 KB), `stderr`, `truncated`.
See [WP-CLI allow-list](#10-wp-cli-allow-list).

### `write_file` (Pro)
| Param | Default | |
|---|---|---|
| `path` | — | File to create or overwrite |
| `content` | — | Full new content (UTF-8) |
| `create_dirs` | `false` | Create missing folders |

Backs up the old version first. PHP files are syntax-checked; if the check fails,
nothing is written. Returns `bytes`, `created`, `backup_id`.

### `edit_file` (Pro)
| Param | Default | |
|---|---|---|
| `path` | — | File to change |
| `old_text` | — | Exact text to find |
| `new_text` | — | Replacement |
| `replace_all` | `false` | Replace every occurrence |

`old_text` must appear exactly once unless `replace_all` is true. Same backup and PHP
check as `write_file`. Returns `backup_id` and `replacements`.

### `move` (Pro)
| Param | |
|---|---|
| `source` | Existing file or folder |
| `destination` | New path (must not exist) |

Both must be inside the same site. Backs up the source first.

### `trash` (Pro)
| Param | |
|---|---|
| `path` | File or folder to remove |

Moves it to `data_dir/trash/<site>/<id>/`, outside the webroot. Returns `trash_id`.
Nothing is ever deleted outright.

### `list_backups` (Pro)
| Param | Default | |
|---|---|---|
| `path` | none | Only show backups whose path starts with this |
| `limit` | `50` | Up to 500 |

Newest first. Each entry: `id`, `kind` (`backup` or `trash`), `path`.

### `restore_backup` (Pro)
| Param | |
|---|---|
| `backup_id` | From `list_backups`, or the `backup_id`/`trash_id` a change returned |
| `path` | The file's path in the site |

Backs up the current version first (so a restore can itself be undone), then puts the
old version back. Works for trashed files too.

### `audit_log` (Pro)
| Param | Default | |
|---|---|---|
| `limit` | `50` | Up to 500 |

Recent calls, newest first, optionally for one site.

---

## 10. WP-CLI allow-list

Claude sends WP-CLI arguments as a list. PressBridge matches the command against the
allow-list for the site's profile, checks the flags, adds `--path` itself, and runs it
without a shell.

### Always allowed (`readonly` profile)

| Command | |
|---|---|
| `cli version` | WP-CLI version |
| `core version`, `core check-update`, `core verify-checksums` | Core info and integrity |
| `plugin list`, `plugin get`, `plugin status`, `plugin verify-checksums` | Plugins |
| `theme list`, `theme get`, `theme status` | Themes |
| `option get <name>` | One option; secret-looking names blocked |
| `post list`, `post get`, `post-type list`, `term list`, `menu list` | Content |
| `user list`, `role list` | Users (emails hidden unless `--fields` is given) |
| `cron event list` | Scheduled tasks |
| `cache type`, `rewrite list`, `db size`, `db check` | Diagnostics |
| `site list` | Multisite |
| `maintenance-mode status`, `language core list` | Status |
| `search-replace ... --dry-run` | Preview only |

### Added by `wp_profile: maintenance` (Pro)

| Command | |
|---|---|
| `plugin activate / deactivate / update / install` | Install only from wordpress.org slugs |
| `plugin auto-updates enable / disable` | |
| `theme activate / update / install` | wordpress.org slugs only |
| `core update`, `core update-db` | |
| `cache flush`, `transient delete`, `rewrite flush` | |
| `cron event run` | |
| `post create`, `post update` | |
| `option update <name> <value>` | Protected options blocked |
| `maintenance-mode activate / deactivate` | |
| `language core install / update` | |
| `search-replace` (without `--dry-run`) | Changes the database |

### Always refused

- Commands not listed above: `eval`, `eval-file`, `shell`, `db query`, `db export`,
  `db import`, `db reset`, `config ...`, `user create/update/delete`, `package ...`,
  `site delete`, `scaffold`, and everything else.
- Flags: `--exec`, `--require`, `--path`, `--ssh`, `--http`, `--context`, `--prompt`.
- `search-replace --export`.
- `option get` on names containing `pass`, `secret`, `token`, `key`, `salt`, `auth`,
  `license`, `smtp`, `api`.
- `option update` on those names and on `siteurl`, `home`, `admin_email`,
  `new_admin_email`, `users_can_register`, `default_role`, `active_plugins`,
  `template`, `stylesheet`, `wp_user_roles`.
- `plugin/theme install` from a URL or `.zip`.

### Testing a command yourself

Run the same thing PressBridge would, inside the container:

```bash
docker compose exec pressbridge wp plugin list --path=/var/www/acme.com/public_html
```

---

## 11. Command-line reference

```
pressbridge --version
pressbridge serve  [--config FILE] [--http] [--host ADDR] [--port N]
pressbridge check  [--config FILE]
pressbridge token
```

| Command | What it does |
|---|---|
| `pressbridge serve` | Runs the MCP server over stdio. This is what the SSH connection uses. |
| `pressbridge serve --http` | Runs it as an HTTP server on `/mcp` with `/health` (Pro). Needs `tokens` in the config. |
| `--host` | Interface to bind. `0.0.0.0` by default; the Docker compose file uses `127.0.0.1` behind Caddy. |
| `--port` | Port, default `8765`. |
| `--config` | Config file, default `/config/config.yaml`. |
| `pressbridge check` | Validates the config, checks WP-CLI and connects to each WordPress. Exit code 0 when everything works. |
| `pressbridge token` | Prints a new random 64-character token. |

Environment variables:

| Variable | Same as |
|---|---|
| `PRESSBRIDGE_CONFIG` | `--config` |
| `PRESSBRIDGE_HOST` | `--host` |
| `PRESSBRIDGE_PORT` | `--port` |

With Docker, prefix commands with `docker compose exec pressbridge`:

```bash
docker compose exec pressbridge pressbridge check
docker compose exec pressbridge pressbridge token
```

---

## 12. Backups, trash and undo

Every `write_file`, `edit_file`, `move`, `trash` and `restore_backup` saves the
previous version first.

```
data_dir/
├── audit.jsonl
├── backups/
│   └── acme/
│       └── 20261014T091322.418302Z/        ← backup_id
│           └── wp-content/themes/acme-child/header.php
└── trash/
    └── acme/
        └── 20261014T101500.001234Z/        ← trash_id
            └── wp-content/themes/acme-child/test.php
```

**Undo through Claude:** *"Undo the last change on acme"*, or
*"restore header.php from backup 20261014T091322.418302Z"*.

**Undo by hand on the server** (if Claude isn't available):

```bash
# list backups for a site, newest first
docker compose exec pressbridge sh -c 'ls -1 /data/backups/acme | sort -r | head'

# see what's inside one
docker compose exec pressbridge find /data/backups/acme/20261014T091322.418302Z -type f

# copy it back
docker compose exec pressbridge cp -p \
  /data/backups/acme/20261014T091322.418302Z/wp-content/themes/acme-child/header.php \
  /var/www/acme.com/public_html/wp-content/themes/acme-child/header.php
```

**Disk space.** Backups are never deleted automatically. Check their size and remove
old ones from time to time:

```bash
docker compose exec pressbridge du -sh /data/backups /data/trash

# delete backups and trash older than 30 days
docker compose exec pressbridge find /data/backups /data/trash \
  -mindepth 2 -maxdepth 2 -type d -mtime +30 -exec rm -rf {} +
```

To do it automatically every night, add to the server's crontab (`crontab -e`):

```cron
15 3 * * * cd /home/you/pressbridge && docker compose exec -T pressbridge find /data/backups /data/trash -mindepth 2 -maxdepth 2 -type d -mtime +30 -exec rm -rf {} +
```

**What backups don't cover:** the database, and files changed by WP-CLI (plugin and
core updates). Keep your normal database and site backups.

---

## 13. Audit log

Every tool call, allowed or refused, is one line in `data_dir/audit.jsonl`:

```json
{"ts": "2026-10-14T09:13:22+00:00", "tool": "edit_file", "site": "acme", "args": {"path": "wp-content/themes/acme-child/header.php", "old_text": "0744 987 001", "new_text": "0745 123 456", "site": "acme"}, "ok": true, "result": {"path": "wp-content/themes/acme-child/header.php", "bytes": 4120, "backup_id": "20261014T091322.418302Z", "replacements": 1}}
{"ts": "2026-10-14T09:13:40+00:00", "tool": "read_file", "site": "acme", "args": {"path": "wp-config.php", "site": "acme"}, "ok": false, "error": "Path 'wp-config.php' is blocked by deny rule 'wp-config*'"}
```

Long values are shortened to 500 characters; full file contents are never logged.

```bash
# last 20 entries
docker compose exec pressbridge tail -n 20 /data/audit.jsonl

# only changes (needs jq on the host)
docker compose exec -T pressbridge cat /data/audit.jsonl \
  | jq -c 'select(.tool | test("write|edit|move|trash|restore")) | {ts, site, tool, path: .args.path}'

# every refused call
docker compose exec -T pressbridge cat /data/audit.jsonl | jq -c 'select(.ok == false)'

# today's activity on one site
docker compose exec -T pressbridge cat /data/audit.jsonl \
  | jq -c --arg d "$(date -u +%F)" 'select(.site == "acme" and (.ts | startswith($d)))'
```

The log grows forever; rotate it yearly or when it gets large:

```bash
docker compose exec pressbridge sh -c 'mv /data/audit.jsonl /data/audit-$(date +%Y).jsonl'
```

---

## 14. Day-to-day administration

All commands from the `pressbridge` folder on the server.

### Status and logs

```bash
docker compose ps                         # running? healthy?
docker compose logs -f pressbridge        # live server log (Ctrl+C to stop)
docker compose logs --tail 100 caddy      # certificate problems
docker compose exec pressbridge pressbridge check
```

### Add or change a site

```bash
nano config.yaml
```

If the new site is outside the folders already mounted, add a volume line in
`docker-compose.yml`, then:

```bash
docker compose up -d
docker compose exec pressbridge pressbridge check
```

For config-only changes:

```bash
docker compose restart pressbridge
```

### Make a site read-only (temporarily or for good)

```yaml
  acme:
    root: /var/www/acme.com/public_html
    mode: read            # was: write
```

```bash
docker compose restart pressbridge
```

### Give a teammate access

1. Make a token: `openssl rand -hex 32`
2. Add it to `.env`: `PB_TOKEN_ANA=...`
3. Add it to `config.yaml` under `tokens:` as `- ${PB_TOKEN_ANA}`
4. Pass it into the container: in `docker-compose.yml`, under `pressbridge:` →
   `environment:`, add `PB_TOKEN_ANA: ${PB_TOKEN_ANA}`
5. `docker compose up -d`
6. Send Ana the token through a password manager, not email.

### Revoke a token

Delete its line from `config.yaml` (and `.env`), then:

```bash
docker compose up -d
```

Anyone using it gets `401` immediately.

### Rotate your own token

```bash
NEW=$(openssl rand -hex 32)
sed -i "s/^PB_TOKEN=.*/PB_TOKEN=$NEW/" .env
docker compose up -d
echo $NEW
```

Then update it in Claude:

```bash
claude mcp remove pressbridge
claude mcp add --transport http pressbridge https://mcp.yourdomain.com/mcp \
  --header "Authorization: Bearer $NEW"
```

### Update PressBridge to a new version

```bash
cd ~
cp pressbridge/config.yaml pressbridge/.env /tmp/      # keep your settings
unzip -o pressbridge-pro-1.1.0.zip
cp /tmp/config.yaml /tmp/.env pressbridge/
cd pressbridge
docker compose --profile tls up -d --build
docker compose exec pressbridge pressbridge check
```

Your backups and audit log are in the `pressbridge-data` volume and are kept.

Python install:

```bash
~/pressbridge-venv/bin/pip install --upgrade ./pressbridge
sudo systemctl restart pressbridge     # if you run it as a service
```

### Update WP-CLI inside the image

Change `WP_CLI_VERSION` at the top of the `Dockerfile`, then:

```bash
docker compose build --no-cache pressbridge && docker compose up -d
```

### Stop and start

```bash
docker compose stop          # stop, keep everything
docker compose start
docker compose --profile tls down    # remove containers, keep data volumes
```

---

## 15. Security model

PressBridge assumes the AI can make mistakes and that text Claude reads (a web page, a
plugin readme, a comment in a file) might try to manipulate it. The limits are enforced
by the server, so they hold no matter what Claude is told.

- **No shell, no arbitrary code.** Claude only has the tools in section 9. WP-CLI runs
  without a shell, from an allow-list, with `--path` pinned.
- **Path sandbox.** Every path is resolved (symlinks followed) and must stay inside the
  site's `root`.
- **Secrets hidden.** Deny patterns apply to listings, search, reads and writes, at any
  depth.
- **Read-only by default.** A site can be changed only with `mode: write`; WP-CLI changes
  only with `wp_profile: maintenance`.
- **Undo for every file change**, stored outside the webroot.
- **PHP syntax check** before saving `.php`, `.phtml` and `.inc` files.
- **Atomic writes** (temp file + rename), so visitors never load a half-written file.
- **Tokens** of at least 24 characters, compared in constant time. HTTP mode won't start
  without one.
- **DNS-rebinding protection** when `allowed_hosts` is set.
- **Only `/mcp` and `/health` are published** by the included Caddy config.

What you still own: database backups, testing updates on staging, keeping tokens
secret. Full details: [SECURITY.md](SECURITY.md).

---

## 16. Troubleshooting

Start with:

```bash
docker compose exec pressbridge pressbridge check
docker compose logs --tail 50 pressbridge
```

| Symptom | Cause and fix |
|---|---|
| `check`: *Error establishing a database connection* | WP-CLI can't reach MySQL. Method A: the socket mount must match `mysql -e "select @@socket"`; if `wp-config.php` uses `127.0.0.1`, MySQL must listen on it. Method B: check `WP_NETWORK` and the `WORDPRESS_DB_*` values. |
| `check`: *root ... does not exist* | The site folder isn't mounted. Add a volume line with the same path on both sides. |
| `Config error: ... requires mode 'write'` | `wp_profile: maintenance` needs `mode: write`. |
| `Config error: Each token must be at least 24 characters` | Generate with `openssl rand -hex 32`. |
| `HTTP mode needs at least one entry in tokens` | `PB_TOKEN` isn't reaching the container. `docker compose exec pressbridge env \| grep PB_` |
| Claude gets `401` | Wrong or old token in Claude. Compare with `.env`; re-add with `claude mcp add`. |
| Claude gets `421 Invalid Host header` | The hostname in Claude's URL isn't in `allowed_hosts`. Set `PB_DOMAIN` to exactly that hostname. |
| `curl https://.../health` fails, no certificate | DNS must point at the server and ports 80/443 must be open before Caddy's first start. `docker compose logs caddy`, fix, then `docker compose restart caddy`. |
| Edited files owned by root or `Permission denied` | Set `PUID`/`PGID` in `.env` to the files' owner (section 4A step 5), then `docker compose up -d`. |
| Claude Desktop shows no PressBridge tools | Quit Claude Desktop fully and reopen. Check the JSON is valid. For SSH, `ssh -o BatchMode=yes you@server true` must succeed without a prompt. For `mcp-remote`, Node.js must be installed (`npx --version`). |
| `claude mcp list` shows *Failed to connect* | Run the URL check: `curl -H "Authorization: Bearer TOKEN" -X POST https://mcp.yourdomain.com/mcp` should not return 401. For SSH, run the exact command after `--` yourself. |
| *Path ... is blocked by deny rule* | On purpose for secrets. If you really need a file (e.g. `debug.log`), add it under `allow:` for that site. |
| *... is not on the allow-list* | The WP-CLI command isn't allowed for this site. See section 10. Maintenance commands need `wp_profile: maintenance`. |
| *PHP syntax check failed, nothing was saved* | Working as intended: the file had a syntax error. Ask Claude to fix the syntax. |
| *old_text was not found* | The file changed or Claude's copy is stale. Ask Claude to read the file again. |
| WP-CLI times out on core updates | Raise `wp_timeout` (e.g. `300`) and restart. |
| `verify-checksums` says it can't retrieve checksums | Normal for premium plugins (not on wordpress.org). Core failures need internet access from the server. |
| Free edition: *HTTP mode is a PressBridge Pro feature* | Use the SSH connection, or upgrade. |
| Free edition: *supports one site* | Remove extra sites, or upgrade. |

Still stuck? Email support with:

```bash
docker compose exec pressbridge pressbridge --version
docker compose exec pressbridge pressbridge check
docker compose logs --tail 100 pressbridge
```

None of these print your tokens or database passwords.

---

## 17. Uninstalling

Docker:

```bash
cd ~/pressbridge
docker compose --profile tls down -v       # -v also deletes backups and audit log
docker image rm pressbridge:1.1.0
cd ~ && rm -rf pressbridge
```

Want to keep the backups first?

```bash
docker run --rm -v pressbridge_pressbridge-data:/data -v "$PWD":/out alpine \
  tar czf /out/pressbridge-data.tgz -C /data .
```

Python:

```bash
sudo systemctl disable --now pressbridge 2>/dev/null
sudo rm -f /etc/systemd/system/pressbridge.service
rm -rf ~/pressbridge-venv ~/.pressbridge
```

On your computer:

```bash
claude mcp remove pressbridge
rm -rf ~/.claude/skills/wp-safe-edit ~/.claude/skills/wp-safe-updates ~/.claude/skills/wp-care-report
```

and remove the `pressbridge` entry from `claude_desktop_config.json`.

PressBridge never modifies WordPress itself, so nothing needs cleaning up on your sites.

---

## 18. PressBridge Watch: the nightly security agent (Agent)

PressBridge Watch checks every site on a schedule (by default every night at 03:30),
compares it with the night before and tells you when something changed that shouldn't
have. If you add an Anthropic API key, Claude then investigates what was found and
explains it in plain language.

It's the check nobody on your team has time to do by hand on 30 sites every day.

### 18.1 What it watches

| Signal | Severity | Why it matters |
|---|---|---|
| New administrator account | Critical | The first thing most attackers do |
| PHP files in `wp-content/uploads` | Critical | Almost always a web shell (guard files that only say "silence is golden" are ignored) |
| Backdoor-like code in new or changed files (`eval(base64_decode(...))`, code run from `$_POST`, including `.ico` files as PHP, ...) | Critical | Typical malware patterns |
| WordPress core files changed without a core update | Critical | Core is never edited legitimately |
| Core or plugin files that don't match wordpress.org checksums | Critical | Tampered files, even when dates were faked |
| New must-use plugin | Critical | Always runs, hidden from the plugin list |
| WordPress crashes with a PHP fatal error | Critical | The site is probably down |
| Site address (`siteurl`/`home`) changed | Critical | Used to redirect visitors |
| Registration opened, or new users get a privileged role | Critical / Warning | Lets anyone create admin accounts |
| Many new user accounts since the last check | Warning (Critical with open admin registration) | Bot sign-ups, spam, or a compromise |
| New plugin or theme, theme switched | Warning | Fine if you did it; worth knowing if you didn't |
| Plugin/theme code changed without a version change | Warning | Someone edited code on the live site |
| `wp-config.php`, `.htaccess` or `.user.ini` changed | Warning | Redirect hacks and code injection live here. wp-config's contents are never read out, only its hash is compared |
| Admin email changed, site hidden from search engines | Warning | Account takeover / SEO damage |
| New scheduled tasks (WP-Cron) without a plugin change | Warning | Malware reinstalls itself through cron |
| Plugin, theme, core and translation updates | Info | So you have a record |

Changes that are explained are not alarms: files changed by a plugin update are listed
as info, and changes you or Claude made through PressBridge are matched against the
audit log and marked as such.

Problems that are already reported stay visible as "Still present" in every report until
they're fixed, but you only get an alert when something is new.

### 18.2 Setup

**1. Add a `watch:` block to `config.yaml`.** The example config has one; the minimum is:

```yaml
watch:
  schedule: ["03:30"]
  timezone: Europe/Bucharest
  email:
    host: smtp.gmail.com
    username: alerts@youragency.com
    password: ${SMTP_PASSWORD}
    to: [you@youragency.com]
```

**2. Put the secrets in `.env`** (next to `docker-compose.yml`):

```bash
echo "TZ=Europe/Bucharest" >> .env
echo "SMTP_PASSWORD=your-smtp-or-app-password" >> .env
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env          # optional, for Claude's review
echo "WATCH_WEBHOOK=https://hooks.slack.com/..." >> .env   # optional
```

For Gmail, use an **app password** (search "App passwords" in your Google Account; it
needs 2-Step Verification), not your normal password.

**3. Start the watcher:**

```bash
docker compose --profile watch up -d --build
# WordPress in Docker:
docker compose -f docker-compose.wp-in-docker.yml --profile watch up -d --build
```

The watcher runs in its own container, `pressbridge-watch`, with your site folders
mounted **read-only**: it physically can't change your sites.

**4. Test the alerts and take the first snapshot:**

```bash
docker compose exec pressbridge-watch pressbridge watch test-alert
docker compose exec pressbridge-watch pressbridge watch run
```

The first run saves a baseline and reports only things that are wrong on their own
(PHP in uploads, backdoor-like code, modified core files, open admin registration). You
also get a "Watch is on" email. From the next run on, you're told about changes.

Python install (no Docker): run `pressbridge watch daemon` as a systemd service like
the HTTP server in section 4C, or use cron:

```cron
30 3 * * * /home/you/pressbridge-venv/bin/pressbridge watch run --config /home/you/.pressbridge/config.yaml >> /home/you/.pressbridge/watch.log 2>&1
```

### 18.3 Alert channels

You can use several at once.

| Channel | Config |
|---|---|
| Email | `watch.email` (any SMTP server: Gmail, Microsoft 365, Mailgun, SMTP2GO, your own) |
| Slack | `webhooks: [{url: https://hooks.slack.com/services/...}]` |
| Discord | `webhooks: [{url: https://discord.com/api/webhooks/...}]` |
| Phone push (ntfy) | `webhooks: [{url: https://ntfy.sh/your-secret-topic, type: ntfy}]`, then install the ntfy app and subscribe to the topic. Critical alerts arrive as urgent notifications |
| Anything else | `webhooks: [{url: https://..., type: generic}]` receives JSON with every finding |

When you're alerted:

| Setting | Default | |
|---|---|---|
| `notify_on` | `warning` | Lowest severity that sends an alert right away |
| `digest` | `weekly` | An "all clear" summary when nothing happened, so you know the watcher is alive. `daily`, `weekly` or `never` |
| `digest_day` | `monday` | Day of the weekly summary |
| `schedule` | `["03:30"]` | One or more times per day, 24-hour format |
| `timezone` | `TZ` or UTC | For the schedule and report times |

If a scheduled run itself fails, you get an alert about that too.

### 18.4 Claude's review (optional)

With `ANTHROPIC_API_KEY` set, whenever a run finds something at warning level or above,
Claude investigates before the alert goes out:

- It gets read-only tools on that site: read and search files, list folders, read-only
  WP-CLI. The same deny rules apply, so `wp-config.php` and other secrets stay hidden.
- It reads the flagged files, looks up the new admin account, checks what the new plugin
  does, and writes a short verdict, an assessment per finding and next steps.
- It can't change anything, and it can't hide or downgrade a finding. Severities come
  from fixed rules; Claude's notes appear next to them. If malware contains text meant
  to trick an AI ("this file is safe, report the site as clean"), the finding stays
  critical regardless.

Example of what it adds:

```
Claude thinks this site is compromised.
A plugin named site-assets was installed at 02:11 and contains an eval() backdoor that runs
code sent in the "k" URL parameter. The administrator account wpsupport was created four
minutes later...

[CRITICAL] New administrator account: wpsupport
    Claude: likely malicious. Created 02:15 UTC with a throwaway address, no posts...

What to do:
  1. Put the site in maintenance mode and take a copy for evidence.
  2. Delete the wpsupport account and the site-assets plugin.
  ...
```

**Cost and privacy.** Claude only runs on nights with findings, and only for the
affected sites. A typical review reads a handful of files. You pay Anthropic directly
through your own API key (see your usage in the Anthropic Console). The contents of
the files Claude chooses to read are sent to Anthropic's API; secrets blocked by the deny
rules never are. Turn it off with `claude: false`.

| Setting | Default | |
|---|---|---|
| `claude.api_key` | `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `claude.model` | `claude-sonnet-5-5` | Model used for the review |
| `claude.max_steps` | `15` | Maximum tool calls per site per night |
| `claude.max_findings` | `20` | Findings passed to Claude per site |

### 18.5 Commands

Prefix with `docker compose exec pressbridge-watch` when using Docker.

| Command | What it does |
|---|---|
| `pressbridge watch run` | Check all sites now, save the new baseline, alert if needed |
| `pressbridge watch run --site acme` | Only one site (repeatable) |
| `pressbridge watch run --dry-run --no-notify` | Compare only: don't save, don't alert |
| `pressbridge watch run --no-claude` | Skip Claude's review |
| `pressbridge watch run --notify-always` | Send the report even if all is clear |
| `pressbridge watch status` | Last run, next run, baseline per site, open problems |
| `pressbridge watch report` | The latest report |
| `pressbridge watch test-alert` | Send a test message to every channel |
| `pressbridge watch daemon [--now]` | Run on the schedule forever (what the container does) |

`watch run` exit codes, for your own monitoring: `0` all clear, `1` warnings,
`2` critical findings, `3` a check failed.

Files kept in `data_dir/watch/`: `state/<site>.json` (baseline), `reports/` (every
report, plus `latest.txt`), `findings.jsonl` (history of all findings).

### 18.6 In chat

Two extra tools for Claude:

- `security_scan` compares a site with the last nightly baseline right now, without
  saving or alerting. *"Run a security scan on acme."*
- `watch_report` returns the latest nightly report. *"Explain last night's watch report
  and help me clean up acme."*

Combine them with the editing tools to clean up: Claude finds the backdoor, you confirm,
Claude trashes it (restorable) and the next nightly run shows whether it's gone.

### 18.7 After a critical alert

1. Don't panic, and don't start deleting things at random.
2. If you didn't make the change: put the site in maintenance mode and take a full
   backup (files + database) as evidence.
3. Change passwords: all WordPress administrators, hosting panel, SFTP/SSH, database.
4. Remove what was found (new admin, backdoor files, unknown plugins). Claude can help
   through PressBridge, and every removal is restorable.
5. Update WordPress, plugins and themes; most hacks come through an outdated plugin.
6. Run `pressbridge watch run` again. The report should be quiet, and nothing should be
   left under "Still present".

If the site handles payments or personal data, check your legal obligations about
reporting a breach.

### 18.8 Tuning

- **Too noisy?** Add folders that change on their own to `watch.ignore`
  (e.g. `"wp-content/uploads/my-plugin-cache/*"`). Caches, backup folders, Wordfence
  logs and `node_modules` are ignored by default.
- **Leave a site out:** `watch: false` on that site.
- **Staging sites** often switch "discourage search engines" on and off; that's only a
  warning, but you can leave staging out entirely.
- **Many sites or huge sites:** each run hashes the site's PHP files (a few seconds per
  site) and runs about a dozen read-only WP-CLI commands. Up to 150,000 files per site.

### 18.9 Watch troubleshooting

| Symptom | Fix |
|---|---|
| `test-alert` fails with an SMTP error | Wrong host/port/password. For Gmail: an app password, port 587, `security: starttls`. For port 465: `security: ssl` |
| No "all clear" summary | It's sent on `digest_day` only; check `watch status` for the last run |
| Container shows `unhealthy` | The daemon stopped writing its heartbeat. `docker compose logs pressbridge-watch` |
| "Couldn't verify core files against wordpress.org" | The server can't reach api.wordpress.org. Info only; the other checks still run. Or set `verify_checksums: false` |
| "WordPress didn't load during the check" | WP-CLI can't connect to the database from the watch container. Same fixes as in section 16 |
| Claude's review: "API key was rejected" | Check `ANTHROPIC_API_KEY` in `.env`, then `docker compose --profile watch up -d` |
| After cleaning a hack, every night still shows "Still present" | Something is still there: read the list; it names the files |

---

## 19. Support and license

- **Support:** support@pressbridge.dev. Include the output from the troubleshooting
  section.
- **Security issues:** security@pressbridge.dev, please not a public issue.
- **Changelog:** [CHANGELOG.md](CHANGELOG.md)
- **License:** Pro and Agent — [LICENSE-PRO.md](LICENSE-PRO.md). Free — MIT.

PressBridge is not affiliated with WordPress, Automattic or Anthropic.
