import http.client
import json
import socket
from pathlib import Path

import pytest

from bomana.core.state import Phase, UISnapshot
from bomana.web import DashboardSnapshotStore, WebDashboardRuntime
from bomana.web.server import DashboardServerError, discover_private_ipv4


def _minimal_snapshot() -> UISnapshot:
    return UISnapshot(
        phase=Phase.IDLE,
        life_index=None,
        cycle=None,
        remaining_sec=None,
        progress=0,
        sortie_id=0,
        api_down=False,
        api_down_pending=False,
        on_ground=False,
        landed_flash=False,
    )


@pytest.fixture
def running_dashboard() -> WebDashboardRuntime:
    store = DashboardSnapshotStore(wall_time=lambda: 100.0)
    store.publish(_minimal_snapshot(), ["启动发动机"])
    runtime = WebDashboardRuntime(store, preferred_port=0)
    runtime.start()
    try:
        yield runtime
    finally:
        runtime.stop()


def _request(
    runtime: WebDashboardRuntime,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    assert runtime.port is not None
    connection = http.client.HTTPConnection("127.0.0.1", runtime.port, timeout=3)
    merged = {"Host": f"127.0.0.1:{runtime.port}", **(headers or {})}
    connection.request(method, path, headers=merged)
    response = connection.getresponse()
    body = response.read()
    response_headers = {name.lower(): value for name, value in response.getheaders()}
    status = response.status
    connection.close()
    return status, response_headers, body


def _pair(runtime: WebDashboardRuntime) -> str:
    status, headers, body = _request(runtime, "GET", f"/?pair={runtime.pairing_code}")
    assert status == 302
    assert body == b""
    assert headers["location"] == "/"
    return headers["set-cookie"].split(";", 1)[0]


def test_dashboard_serves_self_hosted_assets_and_strict_headers(
    running_dashboard: WebDashboardRuntime,
) -> None:
    status, headers, body = _request(running_dashboard, "GET", "/")

    assert status == 200
    assert b"Bomana Web Cockpit" in body
    assert headers["cache-control"].startswith("no-store")
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "access-control-allow-origin" not in headers

    for path, expected_type in (
        ("/assets/dashboard.css", "text/css"),
        ("/assets/dashboard.js", "text/javascript"),
        ("/favicon.svg", "image/svg+xml"),
    ):
        asset_status, asset_headers, asset_body = _request(running_dashboard, "GET", path)
        assert asset_status == 200
        assert asset_headers["content-type"].startswith(expected_type)
        assert asset_body


def test_snapshot_requires_pairing_cookie_and_returns_schema_payload(
    running_dashboard: WebDashboardRuntime,
) -> None:
    status, _, body = _request(running_dashboard, "GET", "/api/v1/snapshot")
    assert status == 401
    assert json.loads(body) == {"error": "pairing_required"}

    cookie = _pair(running_dashboard)
    status, headers, body = _request(
        running_dashboard,
        "GET",
        "/api/v1/snapshot",
        headers={"Cookie": cookie},
    )

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert json.loads(body)["schema_version"] == 1
    assert (
        "httponly"
        in _request(running_dashboard, "GET", f"/?pair={running_dashboard.pairing_code}")[1][
            "set-cookie"
        ].lower()
    )
    assert (
        "samesite=strict"
        in _request(running_dashboard, "GET", f"/?pair={running_dashboard.pairing_code}")[1][
            "set-cookie"
        ].lower()
    )


def test_dashboard_rejects_wrong_host_origin_paths_and_methods(
    running_dashboard: WebDashboardRuntime,
) -> None:
    assert (
        _request(
            running_dashboard,
            "GET",
            "/",
            headers={"Host": "evil.example"},
        )[0]
        == 421
    )
    assert (
        _request(
            running_dashboard,
            "GET",
            "/",
            headers={"Origin": "http://evil.example"},
        )[0]
        == 403
    )
    assert _request(running_dashboard, "GET", "/assets/../server.py")[0] == 404
    method_status, headers, _ = _request(running_dashboard, "POST", "/api/v1/snapshot")
    assert method_status == 405
    assert headers["allow"] == "GET"
    assert "access-control-allow-origin" not in headers


def test_pairing_failures_are_rate_limited(running_dashboard: WebDashboardRuntime) -> None:
    for _ in range(8):
        assert _request(running_dashboard, "GET", "/?pair=AAAA-AAAA")[0] == 403

    status, headers, _ = _request(running_dashboard, "GET", "/?pair=AAAA-AAAA")
    assert status == 429
    assert headers["retry-after"] == "60"


def test_shutdown_releases_listener_port() -> None:
    store = DashboardSnapshotStore()
    runtime = WebDashboardRuntime(store, preferred_port=0)
    runtime.start()
    port = runtime.port
    assert port is not None

    runtime.stop()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_second_runtime_cannot_share_an_active_listener() -> None:
    store = DashboardSnapshotStore()
    first = WebDashboardRuntime(store, preferred_port=0)
    first.start()
    assert first.port is not None
    second = WebDashboardRuntime(store, preferred_port=first.port, port_search_count=1)
    try:
        with pytest.raises(DashboardServerError, match="unable to bind loopback"):
            second.start()
    finally:
        second.stop()
        first.stop()


def test_lan_enable_rejects_public_or_missing_addresses() -> None:
    store = DashboardSnapshotStore()
    runtime = WebDashboardRuntime(
        store,
        preferred_port=0,
        address_provider=lambda: ["8.8.8.8", "127.0.0.1"],
    )
    runtime.start()
    try:
        with pytest.raises(DashboardServerError, match="no RFC1918"):
            runtime.enable_lan()
        assert runtime.lan_enabled is False
    finally:
        runtime.stop()


def test_private_address_discovery_filters_and_prioritizes(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.2.3.4", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.20.0.1", 0)),
        ],
    )

    assert discover_private_ipv4() == ["192.168.1.20", "10.2.3.4", "172.20.0.1"]


def test_dashboard_assets_are_packaged_under_existing_asset_root() -> None:
    root = Path("bomana/assets/web")
    assert {path.name for path in root.iterdir()} == {
        "index.html",
        "dashboard.css",
        "dashboard.js",
        "favicon.svg",
    }
