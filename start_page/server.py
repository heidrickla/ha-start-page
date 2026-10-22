#!/usr/bin/env python3
"""Start Page: one HTTP server, three JSON routes, four static files.

  GET /               the page (www/index.html)
  GET /services.json  the cards, from the add-on options, grouped in order
  GET /status.json    Uptime Kuma's verdict per monitor, refreshed on a timer
  GET /healthz        "ok" for the Supervisor watchdog

Status comes from Uptime Kuma's /metrics, read with the API key as the Basic
password and an empty username, because Uptime Kuma is the thing that already
checks these services; a second set of probes from here would disagree with
it and, for a panel that accepts one connection at a time, compete with the
integration that talks to it. A monitor Uptime Kuma does not know stays grey.

The same server answers on the host port and behind Home Assistant ingress:
every path the page requests is relative, so the ingress prefix needs no
special handling. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
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
from datetime import datetime, UTC
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import contextlib

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
        "status_source": "uptime_kuma" if options.get("uptime_kuma_url") else None,
        "groups": [{"name": g, "cards": cards} for g, cards in groups.items()],
        "problems": problems,
    }


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
        self.url = url.rstrip("/") + "/metrics" if url else ""
        self.api_key = api_key
        self.interval = max(10, int(interval or 30))
        self.verify_tls = verify_tls
        self.ca_file = ca_file
        self.lock = threading.Lock()
        self.monitors: dict[str, dict] = {}
        self.checked_at: str | None = None
        self.error: str | None = None
        self.error_since: str | None = None

    def fetch_once(self) -> None:
        if not self.url:
            self.error = "uptime_kuma_url is not set"
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
    def __init__(self, www: str, services: dict, poller: StatusPoller):
        self.www = www
        self.services = services
        self.poller = poller
        # /status.json answers for these monitors only: the host port has no login.
        self.card_monitors = {
            c["monitor"] for g in services["groups"] for c in g["cards"] if c.get("monitor")
        }
        self.files: dict[str, bytes] = {}
        for name in {v[0] for v in STATIC.values()}:
            with open(os.path.join(www, name), "rb") as fh:
                self.files[name] = fh.read()

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
                self._json(app.services)
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
    poller = StatusPoller(
        str(options.get("uptime_kuma_url") or ""),
        str(options.get("uptime_kuma_api_key") or ""),
        services["status_interval"],
        verify_tls=options.get("uptime_kuma_verify_tls", True) is not False,
        ca_file=str(options.get("uptime_kuma_ca_file") or ""),
    )
    if poller.url:
        poller.start()
        LOG.info("status from %s every %ds", poller.url, poller.interval)
    else:
        LOG.info("no uptime_kuma_url: cards get no status dot")
    app = App(args.www, services, poller)
    server = serve(app, args.port)
    LOG.info("listening on :%d", args.port)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
