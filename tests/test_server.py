"""The page server against a fake Uptime Kuma, plus the two pure functions."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "start_page")
WWW = os.path.join(ROOT, "www")
spec = importlib.util.spec_from_file_location("server", os.path.join(ROOT, "server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

# The shape Uptime Kuma 2.x writes, copied from a live /metrics: one status
# line and one response-time line per monitor, labels in this order.
METRICS = """\
# HELP monitor_status Monitor Status (1 = UP, 0= DOWN, 2= PENDING, 3= MAINTENANCE)
# TYPE monitor_status gauge
monitor_status{monitor_name="Home Assistant",monitor_type="http",monitor_url="https://10.0.0.2:8123/",monitor_hostname="null",monitor_port="null"} 1
monitor_status{monitor_name="Gitea (personal forge)",monitor_type="http",monitor_url="http://10.0.0.3:3000/",monitor_hostname="null",monitor_port="null"} 0
monitor_status{monitor_name="Tuxedo Touch panel",monitor_type="ping",monitor_url="https://",monitor_hostname="10.0.0.5",monitor_port="null"} 2
monitor_status{monitor_name="NUT server",monitor_type="port",monitor_url="https://",monitor_hostname="10.0.0.6",monitor_port="3493"} 3
# TYPE monitor_response_time gauge
monitor_response_time{monitor_name="Home Assistant",monitor_type="http",monitor_url="https://10.0.0.2:8123/",monitor_hostname="null",monitor_port="null"} 42.5
monitor_response_time{monitor_name="Gitea (personal forge)",monitor_type="http",monitor_url="http://10.0.0.3:3000/",monitor_hostname="null",monitor_port="null"} -1
"""
KEY = "uk1_secret"


class FakeKuma(BaseHTTPRequestHandler):
    """Answers /metrics only with the right Basic credentials: empty user, key."""

    fail = False

    def log_message(self, *a):
        pass

    def do_GET(self):
        want = "Basic " + base64.b64encode(f":{KEY}".encode()).decode()
        if self.path != "/metrics" or self.headers.get("Authorization") != want:
            self.send_response(401)
            self.end_headers()
            return
        if FakeKuma.fail:
            self.send_response(503)
            self.end_headers()
            return
        body = METRICS.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def kuma():
    srv = HTTPServer(("127.0.0.1", 0), FakeKuma)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def get(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, dict(resp.headers), resp.read()


# ------------------------------------------------------------- pure functions
def test_parse_metrics_maps_every_status_word_and_response_time():
    m = server.parse_metrics(METRICS)
    assert m["Home Assistant"] == {"status": "up", "response_ms": 42.5, "type": "http"}
    assert m["Gitea (personal forge)"]["status"] == "down"
    assert m["Tuxedo Touch panel"]["status"] == "pending"
    assert m["NUT server"]["status"] == "maintenance"
    assert m["NUT server"]["response_ms"] is None


def test_parse_metrics_ignores_comments_and_other_metrics():
    assert server.parse_metrics('# comment\nsomething_else{monitor_name="x"} 1\n') == {}


def test_build_services_keeps_group_order_and_drops_liars():
    options = {
        "title": "Home",
        "services": [
            {
                "group": "Home",
                "name": "HA",
                "url": "https://ha.test:8123",
                "monitor": "Home Assistant",
            },
            {"group": "Network", "name": "Router", "url": "https://10.0.0.1"},
            {
                "group": "Home",
                "name": "Kuma",
                "url": "http://ha.test:3001",
                "description": "watches",
            },
            {"group": "Home", "name": "", "url": "https://nameless.test"},
            {"group": "Home", "name": "Relative", "url": "/local/page"},
            {"group": "Home", "name": "Twin", "url": "https://ha.test:8123"},
            "not a mapping",
        ],
    }
    model = server.build_services(options)
    assert [g["name"] for g in model["groups"]] == ["Home", "Network"]
    assert [c["name"] for c in model["groups"][0]["cards"]] == ["HA", "Kuma"]
    assert model["groups"][0]["cards"][0]["monitor"] == "Home Assistant"
    assert model["groups"][0]["cards"][1]["monitor"] is None
    assert len(model["problems"]) == 4
    assert any("no name" in p for p in model["problems"])
    assert any("not absolute" in p for p in model["problems"])
    assert any("duplicate" in p for p in model["problems"])
    assert any("not a mapping" in p for p in model["problems"])
    assert model["status_source"] is None


def test_build_services_defaults():
    model = server.build_services({})
    assert model["title"] == "Home"
    assert model["groups"] == []
    assert model["status_interval"] == 30


# --------------------------------------------------------------------- server
@pytest.fixture(scope="module")
def page(kuma, tmp_path_factory):
    options = {
        "title": "Test House",
        "tagline": "start here",
        "lede": "hello",
        "uptime_kuma_url": kuma,
        "uptime_kuma_api_key": KEY,
        "status_interval": 10,
        "services": [
            {
                "group": "Home",
                "name": "HA",
                "url": "https://ha.test:8123",
                "monitor": "Home Assistant",
            },
            {
                "group": "Home",
                "name": "Forge",
                "url": "http://forge.test:3000",
                "monitor": "Gitea (personal forge)",
            },
            {
                "group": "Home",
                "name": "Nobody",
                "url": "https://nobody.test",
                "monitor": "Not In Kuma",
            },
            {"group": "Elsewhere", "name": "Docs", "url": "https://docs.test"},
        ],
    }
    services = server.build_services(options)
    poller = server.StatusPoller(kuma, KEY, 10)
    poller.fetch_once()
    app = server.App(WWW, services, poller)
    srv = server.serve(app, 0, host="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", poller
    srv.shutdown()


def test_index_and_static_files_are_served(page):
    base, _ = page
    status, headers, body = get(base + "/")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert b'<script src="app.js">' in body
    for path, ctype in (
        ("/styles.css", "text/css"),
        ("/app.js", "text/javascript"),
        ("/glyph.png", "image/png"),
    ):
        status, headers, body = get(base + path)
        assert status == 200 and headers["Content-Type"].startswith(ctype) and body


def read(name: str) -> str:
    with open(os.path.join(WWW, name), encoding="utf-8") as fh:
        return fh.read()


def test_every_file_the_page_references_exists_and_is_relative():
    refs = re.findall(r'(?:href|src)="([^"]+)"', read("index.html"))
    assert refs and all("/" not in r for r in refs), refs
    for r in refs:
        assert os.path.exists(os.path.join(WWW, r)), r
    js = read("app.js")
    assert "fetch('services.json'" in js and "fetch('status.json'" in js
    assert re.search(r"\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important", read("styles.css"))


def test_services_json_is_the_model(page):
    base, _ = page
    status, headers, body = get(base + "/services.json")
    assert status == 200 and headers["Cache-Control"] == "no-store"
    model = json.loads(body)
    assert model["title"] == "Test House"
    assert [g["name"] for g in model["groups"]] == ["Home", "Elsewhere"]
    assert model["status_source"] == "uptime_kuma"


def test_status_json_carries_kumas_verdicts(page):
    base, _ = page
    status, _, body = get(base + "/status.json")
    doc = json.loads(body)
    assert status == 200 and doc["error"] is None and doc["checked_at"]
    assert doc["monitors"]["Home Assistant"]["status"] == "up"
    assert doc["monitors"]["Gitea (personal forge)"]["status"] == "down"
    assert "Not In Kuma" not in doc["monitors"]


def test_status_keeps_the_last_verdict_when_kuma_fails(page):
    base, poller = page
    FakeKuma.fail = True
    try:
        poller.fetch_once()
        doc = json.loads(get(base + "/status.json")[2])
        assert doc["error"] == "HTTP 503 from Uptime Kuma" and doc["error_since"]
        assert doc["monitors"]["Home Assistant"]["status"] == "up"
    finally:
        FakeKuma.fail = False
    poller.fetch_once()
    doc = json.loads(get(base + "/status.json")[2])
    assert doc["error"] is None and doc["error_since"] is None


def test_wrong_key_is_an_error_not_a_crash(kuma):
    poller = server.StatusPoller(kuma, "wrong", 10)
    poller.fetch_once()
    assert poller.error == "HTTP 401 from Uptime Kuma" and poller.monitors == {}


def test_no_kuma_configured_says_so():
    poller = server.StatusPoller("", "", 10)
    poller.fetch_once()
    snap = poller.snapshot()
    assert snap["source"] is None and snap["error"] == "uptime_kuma_url is not set"


def test_healthz_head_and_404(page):
    base, _ = page
    assert get(base + "/healthz")[2] == b"ok\n"
    status, headers, body = get(base + "/", method="HEAD")
    assert status == 200 and body == b"" and int(headers["Content-Length"]) > 0
    for path in ("/etc/passwd", "/../server.py", "/www/index.html", "/services.json/x"):
        with pytest.raises(urllib.error.HTTPError) as err:
            get(base + path)
        assert err.value.code == 404


def test_query_string_does_not_change_the_route(page):
    base, _ = page
    assert get(base + "/healthz?x=1")[2] == b"ok\n"
