# PressBridge Free

**Let Claude look inside your WordPress site safely: read-only, sandboxed, secrets hidden.**

[Website](https://pressbridgesupport.github.io/pressbridge) · [Get Pro](https://pressbridge.lemonsqueezy.com/checkout/buy/bbeb6cfe-d46a-40b9-bb7c-3fb0e0c77ac0) · [User guide](GUIDE.md) · [Security](SECURITY.md)

```
you     On mysite, where is the footer phone number set? And show me the DB password.

claude  search "0744" in wp-content/themes  →  footer.php:41
        read_file wp-config.php             →  refused: blocked by deny rule 'wp-config*'

        The number is in wp-content/themes/mysite/footer.php, line 41.
        I can't read wp-config.php: PressBridge hides it so passwords never reach me.
```

PressBridge is an MCP server that gives Claude (Claude Code, Claude Desktop, any MCP
client) controlled access to a WordPress site. The Free edition is read-only and made
for one site: perfect for debugging, audits and "where is this text coming from?".

- Read, list and search theme and plugin files
- `wp-config.php`, `.env`, SQL dumps, keys and `.git` are invisible
- Nothing outside the site folder, symlink tricks included
- Read-only WP-CLI: versions, plugin and theme lists, checksums, cron, users
- `site_overview`: version and pending updates in one call
- Includes the **wp-care-report** skill: a client-ready health and security report

## Install (5 minutes, nothing exposed to the internet)

On the server:

```bash
sudo apt install python3-venv php-cli php-mysql
curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
sudo install wp-cli.phar /usr/local/bin/wp
python3 -m venv ~/pressbridge-venv
~/pressbridge-venv/bin/pip install ./pressbridge
mkdir -p ~/.pressbridge
cat > ~/.pressbridge/config.yaml <<EOF
data_dir: $HOME/.pressbridge/data
sites:
  mysite:
    root: /var/www/mysite/public_html
EOF
~/pressbridge-venv/bin/pressbridge check --config ~/.pressbridge/config.yaml
```

Run it as the user that owns the site files (or one that can read them).

On your computer, Claude Code:

```bash
claude mcp add pressbridge -- ssh you@server \
  /home/you/pressbridge-venv/bin/pressbridge serve --config /home/you/.pressbridge/config.yaml
```

Claude Desktop (`claude_desktop_config.json`, Settings → Developer → Edit Config):

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

Then ask Claude: *"Give me a health overview of mysite"* or *"Where in the theme is the
footer phone number set?"*

The full user guide, with every command, config option and tool, is in
[GUIDE.md](GUIDE.md) (features marked **Pro** aren't in this edition).

## Want Claude to fix things too?

**PressBridge Pro** adds editing with automatic backups and one-call undo, PHP syntax
checks before saving, plugin/theme/core updates, unlimited sites, a remote HTTPS server
with Docker and automatic certificates, the audit log, and skills for safe edits and
safe updates.

**→ https://pressbridgesupport.github.io/pressbridge**

## License

MIT. See LICENSE.
