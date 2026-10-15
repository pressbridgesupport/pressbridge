"""Configuration loading for PressBridge.

A single YAML file describes the WordPress sites the server may touch,
what each one is allowed to do, and where audit logs and backups live.
Secrets (bearer tokens) are pulled from environment variables so the
config file itself can be committed safely.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .edition import EDITION

DEFAULT_DENY = [
    "wp-config*",
    ".env",
    ".env.*",
    ".htpasswd",
    ".git",
    ".git/*",
    "*.sql",
    "*.sql.gz",
    "*.sqlite",
    "*.sqlite3",
    ".ht.sqlite",
    "*.wpress",
    "backup*.zip",
    "*.key",
    "*.pem",
    "id_rsa*",
    "debug.log",
]

VALID_MODES = ("read", "write")
VALID_PROFILES = ("readonly", "maintenance")
_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")


class ConfigError(ValueError):
    """Raised when the config file is missing or invalid."""


@dataclass
class Site:
    name: str
    root: Path
    mode: str = "read"
    wp_path: Path | None = None
    wp_profile: str = "readonly"
    wp_url: str | None = None
    deny: list[str] = field(default_factory=lambda: list(DEFAULT_DENY))
    max_read_bytes: int = 512_000
    max_write_bytes: int = 2_000_000
    watched: bool = True

    @property
    def writable(self) -> bool:
        return self.mode == "write"


@dataclass
class Config:
    sites: dict[str, Site]
    data_dir: Path
    wp_bin: str = "wp"
    wp_timeout: int = 120
    tokens: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    wp_env: list[str] = field(default_factory=list)
    watch: dict = field(default_factory=dict)

    @property
    def audit_log(self) -> Path:
        return self.data_dir / "audit.jsonl"

    def backup_root(self, site: Site) -> Path:
        return self.data_dir / "backups" / site.name

    def trash_root(self, site: Site) -> Path:
        return self.data_dir / "trash" / site.name

    def site(self, name: str | None) -> Site:
        if not name:
            if len(self.sites) == 1:
                return next(iter(self.sites.values()))
            raise ConfigError(
                "Several sites are configured; pass `site`. Known sites: "
                + ", ".join(sorted(self.sites))
            )
        try:
            return self.sites[name]
        except KeyError:
            raise ConfigError(
                f"Unknown site '{name}'. Known sites: " + ", ".join(sorted(self.sites))
            ) from None


def _expand_env(value):
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            # Unset variables become "", and empty tokens/hosts are dropped later.
            # HTTP mode refuses to start without a token, so this cannot open a hole.
            return os.environ.get(m.group(1), "")
        return _ENV_REF.sub(repl, value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def _parse_site(name: str, raw: dict) -> Site:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", name):
        raise ConfigError(f"Site name '{name}' must be lowercase letters, digits, '-' or '_'")
    if not isinstance(raw, dict) or "root" not in raw:
        raise ConfigError(f"Site '{name}' needs a `root` path")
    root = Path(raw["root"]).expanduser()
    if not root.is_absolute():
        raise ConfigError(f"Site '{name}': root must be an absolute path")
    if not root.is_dir():
        raise ConfigError(f"Site '{name}': root {root} does not exist or is not a directory")

    mode = raw.get("mode", "read")
    if mode not in VALID_MODES:
        raise ConfigError(f"Site '{name}': mode must be one of {VALID_MODES}")
    profile = raw.get("wp_profile", "readonly")
    if profile not in VALID_PROFILES:
        raise ConfigError(f"Site '{name}': wp_profile must be one of {VALID_PROFILES}")
    if profile == "maintenance" and mode != "write":
        raise ConfigError(f"Site '{name}': wp_profile 'maintenance' requires mode 'write'")

    wp_path = raw.get("wp_path")
    wp_path = Path(wp_path) if wp_path else None
    if wp_path is None and (root / "wp-includes").is_dir():
        wp_path = root

    deny = list(DEFAULT_DENY)
    if raw.get("replace_default_deny"):
        deny = []
    deny += list(raw.get("deny", []))
    for pattern in raw.get("allow", []):
        if pattern in deny:
            deny.remove(pattern)

    return Site(
        name=name,
        root=root.resolve(),
        mode=mode,
        wp_path=wp_path.resolve() if wp_path else None,
        wp_profile=profile,
        wp_url=raw.get("wp_url"),
        deny=deny,
        max_read_bytes=int(raw.get("max_read_bytes", 512_000)),
        max_write_bytes=int(raw.get("max_write_bytes", 2_000_000)),
        watched=bool(raw.get("watch", True)),
    )


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Config file is not valid YAML: {e}") from e
    raw = _expand_env(raw)

    sites_raw = raw.get("sites") or {}
    if not sites_raw:
        raise ConfigError("Config needs at least one entry under `sites`")
    sites = {name: _parse_site(name, s) for name, s in sites_raw.items()}

    if EDITION == "free":
        if len(sites) > 1:
            raise ConfigError(
                "PressBridge Free supports one site. Remove the extra sites or upgrade to Pro."
            )
        for s in sites.values():
            s.mode = "read"
            s.wp_profile = "readonly"

    data_dir = Path(raw.get("data_dir", "/data")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    tokens = raw.get("tokens") or []
    if isinstance(tokens, str):
        tokens = [tokens]
    tokens = [t for t in tokens if t]
    for t in tokens:
        if len(t) < 24:
            raise ConfigError("Each token must be at least 24 characters (use `openssl rand -hex 32`)")

    return Config(
        sites=sites,
        data_dir=data_dir.resolve(),
        wp_bin=raw.get("wp_bin", "wp"),
        wp_timeout=int(raw.get("wp_timeout", 120)),
        tokens=tokens,
        allowed_hosts=[h for h in (raw.get("allowed_hosts") or []) if h],
        wp_env=[str(v) for v in (raw.get("wp_env") or [])],
        watch=raw.get("watch") or {},
    )
