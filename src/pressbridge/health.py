"""Site health guard: check the site right after a change, and undo the change if it broke it.

After every change Claude makes (file write/edit/move/trash/restore, or a WP-CLI command
that changes the site), PressBridge loads the site's key pages and asks WordPress to boot
through WP-CLI. If the site worked before the change and is broken after it, the change is
rolled back automatically and Claude is told exactly what happened.

"Broken" means one of:
* a page answers with HTTP 5xx, can't be reached, or shows a WordPress/PHP fatal error;
* WP-CLI can't load WordPress (a fatal error in a plugin or theme also breaks WP-CLI).

Pages that were already broken before the change don't trigger a rollback: the guard only
undoes damage it can attribute to the change.
"""
from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from .config import Config, Site

# Text WordPress or PHP prints when a page dies. Matched case-insensitively in the first
# part of the response body.
FATAL_MARKERS = (
    "there has been a critical error on this website",
    "error establishing a database connection",
    "fatal error</b>:",
    "fatal error:",
    "parse error</b>:",
    "parse error:",
    "uncaught error:",
    "the site is experiencing technical difficulties",
)
MAX_BODY = 200_000
USER_AGENT = "PressBridge-HealthCheck/1.0 (+https://pressbridgesupport.github.io/pressbridge)"


@dataclass
class HealthSettings:
    enabled: bool = True
    base_url: str | None = None
    urls: list[str] = field(default_factory=lambda: ["/"])
    auto_rollback: bool = True
    timeout: int = 15
    verify_tls: bool = True
    wp_cli: bool = True


def parse_health(raw, wp_url: str | None) -> HealthSettings:
    """Turn the site's `health_check` config block into settings. Raises ValueError on bad input."""
    if raw is None or raw is True:
        raw = {}
    if raw is False:
        return HealthSettings(enabled=False)
    if not isinstance(raw, dict):
        raise ValueError("health_check must be a mapping, true or false")
    urls = raw.get("urls", ["/"])
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list) or not all(isinstance(u, str) and u for u in urls) or len(urls) > 10:
        raise ValueError("health_check.urls must be a list of up to 10 paths, e.g. ['/', '/shop/']")
    base = raw.get("base_url") or wp_url
    if base and urlparse(base).scheme not in ("http", "https"):
        raise ValueError("health_check.base_url must start with http:// or https://")
    timeout = int(raw.get("timeout", 15))
    if not 1 <= timeout <= 120:
        raise ValueError("health_check.timeout must be between 1 and 120 seconds")
    return HealthSettings(
        enabled=bool(raw.get("enabled", True)),
        base_url=base,
        urls=urls,
        auto_rollback=bool(raw.get("auto_rollback", True)),
        timeout=timeout,
        verify_tls=bool(raw.get("verify_tls", True)),
        wp_cli=bool(raw.get("wp_cli", True)),
    )


@dataclass
class Probe:
    target: str
    ok: bool
    detail: str

    def to_dict(self) -> dict:
        return {"check": self.target, "ok": self.ok, "detail": self.detail}


@dataclass
class Snapshot:
    probes: list[Probe]
    skipped: frozenset[str] = frozenset()

    @property
    def ok(self) -> bool:
        return all(p.ok for p in self.probes)

    @property
    def checked(self) -> bool:
        return bool(self.probes)

    def broken_targets(self) -> set[str]:
        return {p.target for p in self.probes if not p.ok}

    def to_list(self) -> list[dict]:
        return [p.to_dict() for p in self.probes]

    def passed(self) -> set[str]:
        return {p.target for p in self.probes if p.ok}


def _fatal_marker(body: str) -> str | None:
    low = body.lower()
    for m in FATAL_MARKERS:
        if m in low:
            return m
    return None


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only on the site's own host (http->https and trailing slashes)."""

    def __init__(self, host: str):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).hostname != self.host:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe_url(url: str, timeout: int, verify_tls: bool = True) -> Probe:
    host = urlparse(url).hostname or ""
    handlers: list = [_SameHostRedirects(host)]
    if url.startswith("https://"):
        ctx = ssl.create_default_context()
        if not verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read(MAX_BODY).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = e.read(MAX_BODY).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return Probe(url, False, f"unreachable: {reason}")

    if status >= 500:
        marker = _fatal_marker(body)
        return Probe(url, False, f"HTTP {status}" + (f" ({marker})" if marker else ""))
    marker = _fatal_marker(body)
    if marker:
        return Probe(url, False, f"HTTP {status} but the page shows '{marker}'")
    return Probe(url, True, f"HTTP {status}")


def probe_wp(cfg: Config, site: Site) -> Probe:
    """Ask WordPress to boot fully (plugins and theme load) through WP-CLI."""
    from . import wpcli

    try:
        r = wpcli.run(cfg, site, ["option", "get", "blogname"])
    except RuntimeError as e:  # WP-CLI missing or timed out
        return Probe("wp-cli", False, str(e))
    if r["exit_code"] == 0:
        return Probe("wp-cli", True, "WordPress loads")
    text = (r["stderr"] or r["stdout"]).strip()
    m = re.search(r"(PHP )?(Fatal|Parse) error:.*", text, re.IGNORECASE)
    detail = (m.group(0) if m else text)[:400] or f"exit code {r['exit_code']}"
    return Probe("wp-cli", False, detail)


def snapshot(cfg: Config, site: Site, skip: set[str] | None = None) -> Snapshot | None:
    """Check the site now. Returns None when there is nothing to check (guard disabled).

    `skip` lists checks not to run (pages that couldn't be reached before a change can't be
    blamed on it, so there's no point waiting for their timeout again)."""
    hs = site.health
    if not hs.enabled:
        return None
    skip = skip or set()
    probes: list[Probe] = []
    skipped: set[str] = set()
    if hs.base_url:
        base = hs.base_url if hs.base_url.endswith("/") else hs.base_url + "/"
        for path in hs.urls:
            url = urljoin(base, path.lstrip("/"))
            if url in skip:
                skipped.add(url)
            else:
                probes.append(probe_url(url, hs.timeout, hs.verify_tls))
    if hs.wp_cli and site.wp_path:
        if "wp-cli" in skip:
            skipped.add("wp-cli")
        else:
            probes.append(probe_wp(cfg, site))
    return Snapshot(probes, frozenset(skipped)) if probes or skipped else None


def unreachable(snap: Snapshot | None) -> set[str]:
    """Checks that couldn't run at all (network error, WP-CLI missing), including ones that
    were already skipped for that reason. They're skipped after the change too."""
    if not snap:
        return set()
    return set(snap.skipped) | {p.target for p in snap.probes if not p.ok and (
        p.detail.startswith("unreachable") or (p.target == "wp-cli" and "WP-CLI" in p.detail))}


def newly_broken(before: Snapshot | None, after: Snapshot | None) -> list[dict]:
    """Checks that passed before the change and fail after it.

    Only a check that was run AND passed before the change can be blamed on it: a page that
    was down, unreachable or not checked before proves nothing about the change."""
    if not after or after.ok or not before:
        return []
    was_ok = before.passed()
    return [p.to_dict() for p in after.probes if not p.ok and p.target in was_ok]
