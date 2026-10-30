"""The page server against a fake Uptime Kuma, plus the two pure functions."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import ssl
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

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
    # Inside the Home Assistant ingress iframe a same-frame click looks dead:
    # the targets refuse to be framed. Framed cards must open a new tab.
    assert "window.self !== window.top" in js
    assert "a.target = '_blank'; a.rel = 'noopener'" in js
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
    assert snap["source"] is None and snap["setup"] == server.NO_KUMA and snap["error"] is None


def test_a_missing_key_sends_nothing_and_says_what_to_do(tls_kuma):
    url, _, seen = tls_kuma
    seen.clear()
    poller = server.StatusPoller(url, "", 10, verify_tls=False)
    poller.fetch_once()
    snap = poller.snapshot()
    assert seen == [] and snap["source"] == "uptime_kuma" and snap["setup"] == server.NO_KEY
    assert "API Keys" in snap["setup"] and snap["error"] is None


def test_status_source_follows_the_poller(page):
    base, _ = page
    poller = server.StatusPoller("", "", 10)
    app = server.App(WWW, server.build_services({}), poller)
    assert app.model()["status_source"] is None and app.model()["home_assistant"] is None
    poller.set_url(base)
    assert app.model()["status_source"] == "uptime_kuma"


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


def test_status_json_carries_only_the_monitors_on_cards(page):
    base, poller = page
    assert {"Tuxedo Touch panel", "NUT server"} <= poller.monitors.keys(), (
        "control: Kuma lists them"
    )
    doc = json.loads(get(base + "/status.json")[2])
    assert set(doc["monitors"]) == {"Home Assistant", "Gitea (personal forge)"}


@pytest.fixture(scope="module")
def tls_kuma(tmp_path_factory):
    """Uptime Kuma on https with a certificate from a throwaway CA, which names 127.0.0.1."""
    d = tmp_path_factory.mktemp("tls")

    def ossl(*args):
        subprocess.run(["openssl", *args], check=True, capture_output=True, cwd=d)

    ca_ext = (
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    ossl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.pem",
        "-days",
        "2",
        "-subj",
        "/CN=test ca",
        *ca_ext,
    )
    ossl(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "kuma.key",
        "-out",
        "kuma.csr",
        "-subj",
        "/CN=kuma",
    )
    (d / "san.cnf").write_text("subjectAltName=IP:127.0.0.1\n")
    ossl(
        "x509",
        "-req",
        "-in",
        "kuma.csr",
        "-CA",
        "ca.pem",
        "-CAkey",
        "ca.key",
        "-CAcreateserial",
        "-out",
        "kuma.pem",
        "-days",
        "2",
        "-extfile",
        "san.cnf",
    )
    seen = []

    class Recording(FakeKuma):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            super().do_GET()

    srv = HTTPServer(("127.0.0.1", 0), Recording)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(d / "kuma.pem", d / "kuma.key")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{srv.server_port}", str(d / "ca.pem"), seen
    srv.shutdown()


def test_the_key_goes_only_to_a_certificate_that_verifies(tls_kuma):
    url, ca, seen = tls_kuma
    seen.clear()
    poller = server.StatusPoller(url, KEY, 10)  # the system store does not know the CA
    poller.fetch_once()
    assert "CERTIFICATE_VERIFY_FAILED" in poller.error and poller.monitors == {} and seen == []
    poller = server.StatusPoller(url, KEY, 10, ca_file=ca)
    poller.fetch_once()
    assert (
        poller.error is None
        and poller.monitors["Home Assistant"]["status"] == "up"
        and len(seen) == 1
    )


def test_verification_off_accepts_any_certificate(tls_kuma):
    url, _, _ = tls_kuma
    poller = server.StatusPoller(url, KEY, 10, verify_tls=False)
    poller.fetch_once()
    assert poller.error is None and poller.monitors


def test_a_missing_ca_file_is_an_error_and_sends_nothing(tls_kuma):
    url, _, seen = tls_kuma
    seen.clear()
    poller = server.StatusPoller(url, KEY, 10, ca_file="/nonexistent/ca.pem")
    poller.fetch_once()
    assert poller.error.startswith("uptime_kuma_ca_file:") and seen == []


# ------------------------------------------------------------------- discovery
SUP_TOKEN = "supervisor-token"


class FakeSupervisor(BaseHTTPRequestHandler):
    """The four */info answers the default role may read, in the Supervisor's envelope."""

    routes: ClassVar[dict[str, dict]] = {}
    paths: ClassVar[list[str]] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakeSupervisor.paths.append(self.path)
        if self.headers.get("Authorization") != f"Bearer {SUP_TOKEN}":
            self.send_response(401)
            self.end_headers()
            return
        data = FakeSupervisor.routes.get(self.path)
        if data is None:
            self.send_response(403)
            self.end_headers()
            return
        body = json.dumps({"result": "ok", "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def supervisor_routes(kuma_port: int, core_version: str = "2026.10.4") -> dict[str, dict]:
    """An install with this app, an ingress app, a web UI app, a stopped app, an app with no web
    interface, and the Uptime Kuma app on the port of the fake Kuma."""
    listed = [
        ("local_start_page", "Start Page", "started"),
        ("a0d7b954_vscode", "Studio Code Server", "started"),
        ("abcd1234_bookstack", "BookStack", "started"),
        ("core_samba", "Samba share", "started"),
        ("core_letsencrypt", "Let's Encrypt", "stopped"),
        ("a0d7b954_uptime-kuma", "Uptime Kuma", "started"),
    ]
    info = {
        "local_start_page": {"ingress": True, "webui": None},
        "a0d7b954_vscode": {"ingress": True, "webui": None, "description": "Code"},
        "abcd1234_bookstack": {"ingress": False, "webui": "http://[HOST]:2665"},
        "core_samba": {"ingress": False, "webui": None},
        "core_letsencrypt": {"ingress": False, "webui": "https://[HOST]:8443"},
        "a0d7b954_uptime-kuma": {
            "ingress": False,
            "webui": f"http://[HOST]:{kuma_port}",
            "hostname": "127.0.0.1",
            "network": {f"{kuma_port}/tcp": kuma_port},
        },
    }
    routes = {
        "/addons/self/info": {"slug": "local_start_page"},
        "/core/info": {"version": core_version, "port": 8123, "ssl": True},
        "/supervisor/info": {
            "addons": [{"slug": s, "name": n, "state": st, "version": "1.0"} for s, n, st in listed]
        },
    }
    for slug, name, _ in listed:
        routes[f"/addons/{slug}/info"] = {"slug": slug, "name": name, **info[slug]}
    return routes


@pytest.fixture
def supervisor(kuma):
    port = int(kuma.rsplit(":", 1)[1])
    FakeSupervisor.routes = supervisor_routes(port)
    FakeSupervisor.paths = []
    srv = HTTPServer(("127.0.0.1", 0), FakeSupervisor)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield server.Supervisor(SUP_TOKEN, f"http://127.0.0.1:{srv.server_port}")
    srv.shutdown()


def test_app_panel_path_follows_the_home_assistant_version():
    assert server.app_panel_path("2026.10.4") == "/app/"
    assert server.app_panel_path("2026.2.0") == "/app/"
    assert server.app_panel_path("2026.1.3") == "/hassio/ingress/"
    assert server.app_panel_path("2025.12.0") == "/hassio/ingress/"
    assert server.app_panel_path("") == "/app/"


def app_reads() -> list[str]:
    return [p for p in FakeSupervisor.paths if p.startswith("/addons/") and "/self/" not in p]


def test_discovery_cards_are_home_assistant_and_each_running_app_with_a_web_interface(
    supervisor, kuma
):
    found = server.discover(supervisor, {})
    cards = {c["name"]: c["url"] for c in found["cards"]}
    port = kuma.rsplit(":", 1)[1]
    assert cards == {
        "Home Assistant": "[HA]/",
        "BookStack": "http://[HOST]:2665",
        "Studio Code Server": "[HA]/app/a0d7b954_vscode",
        "Uptime Kuma": f"http://[HOST]:{port}",
    }, "not itself, not a stopped app, not one with no web interface"
    assert found["cards"][0]["name"] == "Home Assistant"
    assert {c["group"] for c in found["cards"]} == {"Home Assistant"}
    assert found["home_assistant"] == {"ssl": True, "port": 8123}


def test_discovery_reads_each_app_once_per_version(supervisor):
    cache: dict = {}
    server.discover(supervisor, cache)
    assert len(app_reads()) == 5
    FakeSupervisor.paths.clear()
    server.discover(supervisor, cache)
    assert app_reads() == []
    FakeSupervisor.routes["/supervisor/info"]["addons"][1]["version"] = "1.1"
    FakeSupervisor.paths.clear()
    server.discover(supervisor, cache)
    assert app_reads() == ["/addons/a0d7b954_vscode/info"]


def test_the_poller_follows_the_uptime_kuma_app_when_no_url_is_typed(supervisor, kuma):
    poller = server.StatusPoller("", KEY, 10)
    discovery = server.Discovery(
        supervisor, cards=True, on_refresh=lambda f: poller.set_url(f["uptime_kuma_url"])
    )
    discovery.refresh()
    assert poller.url == kuma + "/metrics"
    poller.fetch_once()
    assert (
        poller.snapshot()["setup"] is None and poller.monitors["Home Assistant"]["status"] == "up"
    )


def test_discovery_off_still_finds_uptime_kuma_and_reads_no_other_app(supervisor, kuma):
    found = server.discover(supervisor, {}, cards=False)
    assert found["cards"] == [] and found["uptime_kuma_url"] == kuma
    assert app_reads() == ["/addons/a0d7b954_uptime-kuma/info"]


def test_a_typed_card_replaces_the_discovered_card_of_the_same_name(supervisor):
    discovery = server.Discovery(supervisor, cards=True)
    discovery.refresh()
    typed = server.build_services(
        {"services": [{"group": "Lab", "name": "bookstack", "url": "https://books.test"}]}
    )
    model = server.with_discovered(typed, discovery.snapshot())
    names = [(g["name"], c["name"]) for g in model["groups"] for c in g["cards"]]
    assert names[0] == ("Lab", "bookstack")
    assert ("Home Assistant", "BookStack") not in names and (
        "Home Assistant",
        "Home Assistant",
    ) in names
    assert (
        model["home_assistant"] == {"ssl": True, "port": 8123} and model["discovery_error"] is None
    )


def test_a_refusing_supervisor_is_named_and_the_typed_cards_stay(supervisor):
    del FakeSupervisor.routes["/core/info"]
    discovery = server.Discovery(supervisor, cards=True)
    discovery.refresh()
    typed = server.build_services(
        {"services": [{"group": "G", "name": "A", "url": "https://a.test"}]}
    )
    model = server.with_discovered(typed, discovery.snapshot())
    assert model["discovery_error"] == "the Supervisor answered HTTP 403 for /core/info"
    assert [c["name"] for g in model["groups"] for c in g["cards"]] == ["A"]


def test_a_supervisor_without_the_app_list_says_so(supervisor):
    FakeSupervisor.routes["/supervisor/info"] = {"version": "2027.1.0"}
    with pytest.raises(server.SupervisorError, match="no longer lists the installed apps"):
        server.discover(supervisor, {})


def test_the_page_fills_in_discovered_addresses_and_shows_what_is_missing():
    js = read("app.js")
    assert "a.href = resolve(c.url)" in js
    assert "replaceAll('[HA]', base).replaceAll('[HOST]', location.hostname)" in js
    assert "framed || !ha ? location.origin" in js
    assert "if (s.setup) line.textContent" in js
    assert 'id="nocards"' in read("index.html")
