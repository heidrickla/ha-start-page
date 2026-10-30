#!/usr/bin/env python3
"""Start Page: one HTTP server, three JSON routes, four static files.

  GET /               the page (www/index.html)
  GET /services.json  the cards: the typed ones, then Home Assistant and its apps
  GET /status.json    Uptime Kuma's verdict per monitor, refreshed on a timer
  GET /healthz        "ok" for the Supervisor watchdog

Status comes from Uptime Kuma's /metrics, read with the API key as the Basic
password and an empty username, because Uptime Kuma is the thing that already
checks these services; a second set of probes from here would disagree with
it and, for a panel that accepts one connection at a time, compete with the
integration that talks to it. A monitor Uptime Kuma does not know stays grey.

Under the Supervisor the server reads its API (the default role reads every
*/info) for a card to Home Assistant and one to each running app with a web
interface, and for the Uptime Kuma app's address when none is typed. Those
cards carry [HA] and [HOST], which the page fills in from the address it was
loaded from, as Home Assistant's own Open Web UI button does.

The same server answers on the host port and behind Home Assistant ingress:
every path the page requests is relative, so the ingress prefix needs no
special handling. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import logging
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

LOG = logging.getLogger("start-page")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/glyph.png": ("glyph.png", "image/png"),
    "/favicon.ico": ("glyph.png", "image/png"),
}
STATUS_WORDS = {"0": "down", "1": "up", "2": "pending", "3": "maintenance"}
METRIC_RE = re.compile(r"^(monitor_status|monitor_response_time)\{(.*)\}\s+(\S+)$")
LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')
SUPERVISOR_URL = "http://supervisor"
DISCOVERY_INTERVAL = 300
DISCOVERED_GROUP = "Home Assistant"
KUMA_SLUGS = ("uptime-kuma", "uptime_kuma")
KUMA_PORT = 3001
NO_KUMA = "No Uptime Kuma found: install the Uptime Kuma app, or set uptime_kuma_url."
NO_KEY = (
    "Uptime Kuma needs an API key: make one in Uptime Kuma, Settings, API Keys, "
    "and set uptime_kuma_api_key."
)


# --------------------------------------------------------------------- options
def load_options(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc if isinstance(doc, dict) else {}


def build_services(options: dict) -> dict:
    """The page model: groups in first-seen order, cards validated.

    A card that would lie is dropped and logged: no name, no absolute URL,
    or a URL already on the page. The page is a set of availability claims
    and a dead or duplicate card teaches the reader to distrust it.
    """
    groups: dict[str, list[dict]] = {}
    seen_urls: set[str] = set()
    problems: list[str] = []
    for i, raw in enumerate(options.get("services") or []):
        if not isinstance(raw, dict):
            problems.append(f"services[{i}]: not a mapping")
            continue
        name = str(raw.get("name") or "").strip()
        url = str(raw.get("url") or "").strip()
        group = str(raw.get("group") or "Other").strip() or "Other"
        parts = urlsplit(url)
        if not name:
            problems.append(f"services[{i}]: no name")
            continue
        if parts.scheme not in ("http", "https") or not parts.netloc:
            problems.append(f"services[{i}] {name}: url is not absolute http(s): {url!r}")
            continue
        if url in seen_urls:
            problems.append(f"services[{i}] {name}: duplicate url {url}")
            continue
        seen_urls.add(url)
        card = {
            "name": name,
            "url": url,
            "description": str(raw.get("description") or "").strip(),
            "monitor": str(raw.get("monitor") or "").strip() or None,
        }
        groups.setdefault(group, []).append(card)
    for p in problems:
        LOG.warning("dropped: %s", p)
    return {
        "title": str(options.get("title") or "Home"),
        "tagline": str(options.get("tagline") or ""),
        "lede": str(options.get("lede") or ""),
        "status_interval": int(options.get("status_interval") or 30),
        "groups": [{"name": g, "cards": cards} for g, cards in groups.items()],
        "problems": problems,
    }


def with_discovered(model: dict, found: dict | None) -> dict:
    """The typed cards, then each discovered card whose name no card before it uses.

    A typed card replaces the discovered one of the same name, so an address typed
    for the LAN or a tunnel wins over the one the page would work out.
    """
    if not found:
        return {**model, "home_assistant": None, "discovery_error": None}
    names = {c["name"].casefold() for g in model["groups"] for c in g["cards"]}
    groups = {g["name"]: list(g["cards"]) for g in model["groups"]}
    for card in found["cards"]:
        if card["name"].casefold() in names:
            continue
        names.add(card["name"].casefold())
        groups.setdefault(card["group"], []).append(
            {
                "name": card["name"],
                "url": card["url"],
                "description": card["description"],
                "monitor": None,
            }
        )
    return {
        **model,
        "groups": [{"name": g, "cards": cards} for g, cards in groups.items()],
        "home_assistant": found["home_assistant"],
        "discovery_error": found["error"],
    }


# ------------------------------------------------------------------ supervisor
class SupervisorError(Exception):
    """The Supervisor could not be read, in words for the log and the page."""


class Supervisor:
    """The Supervisor API, read with the add-on's own token."""

    def __init__(self, token: str, base: str = SUPERVISOR_URL):
        self.token = token
        self.base = base.rstrip("/")

    def get(self, path: str) -> dict:
        req = urllib.request.Request(self.base + path)
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                doc = json.load(resp)
        except urllib.error.HTTPError as err:
            raise SupervisorError(f"the Supervisor answered HTTP {err.code} for {path}") from err
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise SupervisorError(f"the Supervisor could not be read: {err}") from err
        data = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(data, dict):
            raise SupervisorError(f"the Supervisor sent no data for {path}")
        return data


def app_panel_path(version: str) -> str:
    """Home Assistant 2026.2 moved an app's web interface from /hassio/ingress/ to /app/."""
    m = re.match(r"(\d+)\.(\d+)", version)
    if m and (int(m[1]), int(m[2])) < (2026, 2):
        return "/hassio/ingress/"
    return "/app/"


def is_uptime_kuma(slug: str) -> bool:
    """The Uptime Kuma app from any repository: the slug after the repository ID."""
    return slug.split("_", 1)[-1] in KUMA_SLUGS


def kuma_url(info: dict) -> str:
    """The app's address on the internal network: its host name and its container port."""
    host = str(info.get("hostname") or "")
    ports = [p.split("/")[0] for p in info.get("network") or {} if p.endswith("/tcp")]
    port = ports[0] if ports and ports[0].isdigit() else KUMA_PORT
    return f"http://{host}:{port}" if host else ""


def discover(sup: Supervisor, cache: dict, cards: bool = True) -> dict:
    """Home Assistant, each running app with a web interface, and the Uptime Kuma app's address.

    `cache` holds each app's info by slug and version, so a later pass reads only what changed.
    """
    me = sup.get("/addons/self/info").get("slug")
    core = sup.get("/core/info")
    # Deprecated for GET /addons, which the default role may not read; this list it may.
    listed = sup.get("/supervisor/info").get("addons")
    if not isinstance(listed, list):
        raise SupervisorError("the Supervisor no longer lists the installed apps in its info")
    version = str(core.get("version") or "")
    panel = app_panel_path(version)
    found: list[dict] = []
    if cards:
        found.append(
            {
                "group": DISCOVERED_GROUP,
                "name": "Home Assistant",
                "url": "[HA]/",
                "description": f"Version {version}" if version else "",
            }
        )
    kuma = ""
    seen: dict = {}
    for item in sorted(listed, key=lambda a: str(a.get("name") or "").casefold()):
        slug = str(item.get("slug") or "")
        started = item.get("state") == "started"
        if not slug or slug == me or not (cards or is_uptime_kuma(slug)):
            continue
        key = (slug, str(item.get("version")))
        info = seen[key] = cache.get(key) or sup.get(f"/addons/{slug}/info")
        if is_uptime_kuma(slug) and (started or not kuma):
            kuma = kuma_url(info)
        if not (cards and started):
            continue
        url = f"[HA]{panel}{slug}" if info.get("ingress") else str(info.get("webui") or "")
        if url:
            found.append(
                {
                    "group": DISCOVERED_GROUP,
                    "name": str(info.get("name") or item.get("name") or slug),
                    "url": url,
                    "description": str(info.get("description") or ""),
                }
            )
    cache.clear()
    cache.update(seen)
    return {
        "home_assistant": {"ssl": bool(core.get("ssl")), "port": int(core.get("port") or 8123)},
        "cards": found,
        "uptime_kuma_url": kuma,
    }


class Discovery:
    """Reads the Supervisor on an interval and keeps the last good answer."""

    def __init__(
        self,
        sup: Supervisor,
        cards: bool,
        on_refresh: Callable[[dict], None] | None = None,
        interval: int = DISCOVERY_INTERVAL,
    ):
        self.sup = sup
        self.cards = cards
        self.on_refresh = on_refresh
        self.interval = interval
        self.cache: dict = {}
        self.lock = threading.Lock()
        self.found: dict | None = None
        self.error: str | None = None

    def refresh(self) -> None:
        try:
            found = discover(self.sup, self.cache, cards=self.cards)
        except SupervisorError as err:
            with self.lock:
                if self.error != str(err):
                    LOG.warning("discovery: %s", err)
                self.error = str(err)
            return
        with self.lock:
            before = self.found
            self.found = found
            self.error = None
        names = [c["name"] for c in found["cards"]]
        if before is None or [c["name"] for c in before["cards"]] != names:
            LOG.info("discovery: %d cards for Home Assistant and its apps", len(names))
        if self.on_refresh:
            self.on_refresh(found)

    def snapshot(self) -> dict:
        with self.lock:
            base = self.found or {"home_assistant": None, "cards": [], "uptime_kuma_url": ""}
            return {**base, "error": self.error}

    def run_forever(self) -> None:
        while True:
            time.sleep(self.interval)
            self.refresh()

    def start(self) -> None:
        threading.Thread(target=self.run_forever, name="discovery", daemon=True).start()


# ---------------------------------------------------------------------- status
def parse_metrics(text: str) -> dict[str, dict]:
    """monitor name -> {"status": word, "response_ms": float | None}."""
    out: dict[str, dict] = {}
    for line in text.splitlines():
        m = METRIC_RE.match(line.strip())
        if not m:
            continue
        metric, raw_labels, value = m.groups()
        labels = dict(LABEL_RE.findall(raw_labels))
        name = labels.get("monitor_name")
        if not name:
            continue
        entry = out.setdefault(name, {"status": "unknown", "response_ms": None})
        if metric == "monitor_status":
            entry["status"] = STATUS_WORDS.get(value, "unknown")
            entry["type"] = labels.get("monitor_type")
        else:
            with contextlib.suppress(ValueError):
                entry["response_ms"] = float(value)
    return out


class StatusPoller:
    """Fetches /metrics on an interval; serves the last good answer with its age."""

    def __init__(
        self, url: str, api_key: str, interval: int, verify_tls: bool = True, ca_file: str = ""
    ):
        self.api_key = api_key
        self.interval = max(10, int(interval or 30))
        self.verify_tls = verify_tls
        self.ca_file = ca_file
        self.lock = threading.Lock()
        self.url = ""
        self.monitors: dict[str, dict] = {}
        self.checked_at: str | None = None
        self.error: str | None = None
        self.error_since: str | None = None
        self.noted: str | None = None
        self.set_url(url)

    def set_url(self, url: str) -> None:
        """Point at another Uptime Kuma; what the old one said no longer holds."""
        metrics = url.rstrip("/") + "/metrics" if url else ""
        with self.lock:
            if metrics == self.url:
                return
            self.url = metrics
            self.monitors = {}
            self.checked_at = self.error = self.error_since = None
        if metrics:
            LOG.info("status from %s every %ds", metrics, self.interval)

    def setup(self) -> str | None:
        """What the user still has to give for status dots, in the words the page shows."""
        if not self.url:
            return NO_KUMA
        if not self.api_key:
            return NO_KEY
        return None

    def fetch_once(self) -> None:
        missing = self.setup()
        if missing != self.noted:
            self.noted = missing
            if missing:
                LOG.warning("uptime kuma: %s", missing)
        if missing:
            return
        req = urllib.request.Request(self.url)
        token = base64.b64encode(f":{self.api_key}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        try:
            ctx = self.tls_context()
        except (OSError, ssl.SSLError) as err:
            self._fail(f"uptime_kuma_ca_file: {err}")
            return
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            self._fail(f"HTTP {err.code} from Uptime Kuma")
            return
        except (urllib.error.URLError, OSError, ValueError) as err:
            self._fail(str(err))
            return
        monitors = parse_metrics(text)
        with self.lock:
            self.monitors = monitors
            self.checked_at = _now()
            if self.error:
                LOG.info("uptime kuma reachable again: %d monitors", len(monitors))
            self.error = None
            self.error_since = None

    def tls_context(self) -> ssl.SSLContext | None:
        """The key goes only to a certificate that verifies: against `ca_file` when set, else the
        system store. `verify_tls` off skips the check."""
        if not self.url.startswith("https"):
            return None
        if not self.verify_tls:
            return ssl._create_unverified_context()
        return ssl.create_default_context(cafile=self.ca_file or None)

    def _fail(self, message: str) -> None:
        with self.lock:
            if self.error != message:
                LOG.warning("uptime kuma: %s", message)
            self.error = message
            self.error_since = self.error_since or _now()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "source": "uptime_kuma" if self.url else None,
                "setup": self.setup(),
                "checked_at": self.checked_at,
                "error": self.error,
                "error_since": self.error_since,
                "monitors": dict(self.monitors),
                "generated_at": _now(),
            }

    def run_forever(self) -> None:
        while True:
            self.fetch_once()
            time.sleep(self.interval)

    def start(self) -> None:
        threading.Thread(target=self.run_forever, name="status", daemon=True).start()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------------ http
class App:
    def __init__(
        self, www: str, services: dict, poller: StatusPoller, discovery: Discovery | None = None
    ):
        self.www = www
        self.services = services
        self.poller = poller
        self.discovery = discovery
        # /status.json answers for these monitors only, so the page shows nothing beyond its cards.
        self.card_monitors = {
            c["monitor"] for g in services["groups"] for c in g["cards"] if c.get("monitor")
        }
        self.files: dict[str, bytes] = {}
        for name in {v[0] for v in STATIC.values()}:
            with open(os.path.join(www, name), "rb") as fh:
                self.files[name] = fh.read()

    def model(self) -> dict:
        found = self.discovery.snapshot() if self.discovery else None
        model = with_discovered(self.services, found)
        model["status_source"] = "uptime_kuma" if self.poller.url else None
        return model

    def status(self) -> dict:
        snap = self.poller.snapshot()
        snap["monitors"] = {k: v for k, v in snap["monitors"].items() if k in self.card_monitors}
        return snap


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "start-page"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet by default; errors still log
            if LOG.isEnabledFor(logging.DEBUG):
                LOG.debug("%s " + fmt, self.address_string(), *args)

        def _send(self, status: int, body: bytes, ctype: str, cache: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, doc: dict) -> None:
            self._send(200, json.dumps(doc).encode(), "application/json", "no-store")

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urlsplit(self.path).path or "/"
            if path == "/healthz":
                self._send(200, b"ok\n", "text/plain", "no-store")
            elif path == "/services.json":
                self._json(app.model())
            elif path == "/status.json":
                self._json(app.status())
            elif path in STATIC:
                name, ctype = STATIC[path]
                self._send(200, app.files[name], ctype, "no-cache")
            else:
                self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain", "no-store")

    return Handler


def serve(app: App, port: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--options", required=True)
    ap.add_argument("--www", required=True)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "info"))
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[start-page] %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    options = load_options(args.options)
    services = build_services(options)
    cards = sum(len(g["cards"]) for g in services["groups"])
    LOG.info(
        "%d cards in %d groups, %d dropped",
        cards,
        len(services["groups"]),
        len(services["problems"]),
    )
    typed_kuma = str(options.get("uptime_kuma_url") or "")
    poller = StatusPoller(
        typed_kuma,
        str(options.get("uptime_kuma_api_key") or ""),
        services["status_interval"],
        verify_tls=options.get("uptime_kuma_verify_tls", True) is not False,
        ca_file=str(options.get("uptime_kuma_ca_file") or ""),
    )
    want_cards = options.get("discover_cards", True) is not False
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    discovery = None
    if token and (want_cards or not typed_kuma):

        def follow_kuma(found: dict) -> None:
            if not typed_kuma:
                poller.set_url(found["uptime_kuma_url"])

        discovery = Discovery(Supervisor(token), cards=want_cards, on_refresh=follow_kuma)
        discovery.refresh()
        discovery.start()
    elif not token:
        LOG.info("no Supervisor token: no discovered cards, no Uptime Kuma app found")
    poller.start()
    app = App(args.www, services, poller, discovery)
    server = serve(app, args.port)
    LOG.info("listening on :%d", args.port)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
