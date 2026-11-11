---
description: Set up the PressBridge MCP server for a WordPress site (install, config, connect Claude)
---

Help the user connect Claude to a WordPress site with PressBridge. Ask only what you need:
where the site runs (this machine, or a server reached over SSH) and the path to the
WordPress folder.

Steps to walk them through, adapting paths:

1. On the machine where the site files are, as the user that owns them:
   `pip install pressbridge` in a virtualenv, or use `uvx pressbridge` (needs `uv`).
   WP-CLI (`wp`) should be installed for the WP-CLI tools.
2. Create `~/.pressbridge/config.yaml`:

   ```yaml
   data_dir: ~/.pressbridge/data
   sites:
     mysite:
       root: /var/www/mysite/public_html
       wp_url: https://mysite.example
   ```

3. Check it: `pressbridge check --config ~/.pressbridge/config.yaml`.
4. Connect Claude Code:
   - Same machine: `claude mcp add pressbridge -- pressbridge serve --config ~/.pressbridge/config.yaml`
   - Remote server: `claude mcp add pressbridge -- ssh you@server /path/to/pressbridge serve --config /home/you/.pressbridge/config.yaml`
5. Restart Claude Code and run `check_site_health` to confirm.

Full guide: https://github.com/pressbridgesupport/pressbridge#install-5-minutes-nothing-exposed-to-the-internet

The Free edition is read-only. Editing with backups and automatic rollback, updates and the
nightly security watch are in Pro: https://pressbridgesupport.github.io/pressbridge/#pricing
