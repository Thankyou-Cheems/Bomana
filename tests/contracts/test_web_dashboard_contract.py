# enforces: docs/specs/web-dashboard.md WDB-01..WDB-05 WDB-07 WDB-10..WDB-14 WDB-16 WDB-17

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = (ROOT / "bomana/web/server.py").read_text(encoding="utf-8")
SNAPSHOT = (ROOT / "bomana/web/snapshot.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "bomana/ui/runtime_services.py").read_text(encoding="utf-8")
APP = (ROOT / "bomana/ui/app.py").read_text(encoding="utf-8")
HTML = (ROOT / "bomana/assets/web/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "bomana/assets/web/dashboard.css").read_text(encoding="utf-8")
JS = (ROOT / "bomana/assets/web/dashboard.js").read_text(encoding="utf-8")


def test_server_is_dedicated_loopback_first_and_never_an_8111_proxy() -> None:
    assert 'self._start_listener("127.0.0.1"' in SERVER
    assert "DEFAULT_PORT = 8777" in SERVER
    assert "8111" not in SERVER
    assert "NetworkConfig" not in SERVER
    assert "requests" not in SERVER
    assert "urllib.request" not in SERVER
    assert "proxy" not in SERVER.lower()


def test_server_has_no_tk_dependency_and_app_publishes_snapshot_state() -> None:
    assert "tkinter" not in SERVER
    assert "bomana.ui" not in SERVER
    assert "publish_dashboard(snap, list(self.chk_items))" in APP
    assert "DashboardSnapshotStore" in RUNTIME


def test_lan_and_tray_paths_are_explicit_current_run_actions() -> None:
    assert "_is_rfc1918" in SERVER
    assert '("0.0.0.0"' not in SERVER
    assert "enable_dashboard_lan" in RUNTIME
    assert "disable_dashboard_lan" in RUNTIME
    assert "允许局域网访问（本次运行）" in RUNTIME
    assert "app.dispatcher.post(app._toggle_web_dashboard_lan)" in RUNTIME
    assert "app.dispatcher.post(app._open_web_dashboard)" in RUNTIME
    assert "enabled=self._dashboard_lan_share_available" in RUNTIME
    assert "web_dashboard_lan_enabled" not in APP


def test_map_projection_allowlist_excludes_hostile_contacts_and_raw_payloads() -> None:
    assert 'allowed.update(("poi", "traceback"))' in SNAPSHOT
    assert 'allowed.add("zone")' in SNAPSHOT
    assert 'allowed.add("airfield")' in SNAPSHOT
    assert "hostile_air_contacts" not in SNAPSHOT
    assert "source_debug" not in SNAPSHOT
    assert "perf_debug" not in SNAPSHOT


def test_routes_auth_headers_and_no_cors_are_closed_by_construction() -> None:
    for route in (
        'path == "/"',
        'path == "/healthz"',
        'path == "/api/v1/snapshot"',
        '"/assets/dashboard.css"',
        '"/assets/dashboard.js"',
        '"/favicon.svg"',
    ):
        assert route in SERVER
    assert "SimpleCookie" in SERVER
    assert "SameSite=Strict" in SERVER
    assert "HttpOnly" in SERVER
    assert "host_allowed" in SERVER
    assert "_origin_allowed" in SERVER
    assert "Access-Control-Allow-Origin" not in SERVER
    assert "Content-Security-Policy" in SERVER
    assert "no-store" in SERVER
    assert "def log_message" in SERVER
    assert "def handle_error" in SERVER


def test_browser_assets_are_self_hosted_and_do_not_execute_remote_code() -> None:
    combined = "\n".join((HTML, CSS, JS)).lower()
    assert "http://" not in combined
    assert "https://" not in combined
    assert "@import" not in combined
    assert "eval(" not in combined
    assert "new function" not in combined
    assert 'fetch("/api/v1/snapshot"' in JS
    assert "innerHTML" not in JS
    assert 'data-capability="weapon"' in HTML
    assert 'querySelectorAll("[data-capability]")' in JS
    assert ".capability-hidden" in CSS


def test_all_packaging_paths_include_web_assets_and_runtime_modules() -> None:
    portable = (ROOT / "tools/build_portable.py").read_text(encoding="utf-8")
    build_bat = (ROOT / "tools/scripts/build.bat").read_text(encoding="utf-8")
    build_sh = (ROOT / "tools/scripts/build.sh").read_text(encoding="utf-8")

    assert "app_root = root / APP_DIR" in portable
    assert 'app_root.rglob("*")' in portable
    assert '"http.server"' in portable
    assert '"http.cookies"' in portable
    assert '"ipaddress"' in portable
    assert '--add-data "bomana/assets;bomana/assets"' in build_bat
    assert '"--add-data" "bomana/assets:bomana/assets"' in build_sh
