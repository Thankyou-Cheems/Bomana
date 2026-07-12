import http.client
import json
import socket
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from bomana.core.state import Phase, UISnapshot
from bomana.web import (
    COMMAND_NAMES,
    PANEL_TARGETS,
    ControlStateProjection,
    ControlTargetState,
    DashboardControlStore,
    DashboardSnapshotStore,
    PanelVisibility,
    WeaponChoice,
    WebCommandEnvelope,
    WebDashboardRuntime,
)
from bomana.web.control import validate_command_payload
from bomana.web.server import (
    SESSION_MAX_AGE_SEC,
    DashboardServerError,
    _CommandBridge,
    _Listener,
    _SecurityState,
    discover_private_ipv4,
)


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


def _control_projection(revision: int = 1) -> ControlStateProjection:
    return ControlStateProjection(
        revision=revision,
        commands=COMMAND_NAMES,
        panel_targets=PANEL_TARGETS,
        state=ControlTargetState(
            locked=False,
            beep_enabled=True,
            zone_sound_enabled=True,
            panel_visibility=PanelVisibility(True, True, True, True, True, True),
            selected_weapon_id="aim_9l",
            ballistic_model="foxthree_compatible",
        ),
        weapons=(WeaponChoice("aim_9l", "AIM-9L", "air_to_air", True, True),),
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


@pytest.fixture
def controlled_dashboard() -> Iterator[tuple[WebDashboardRuntime, list[WebCommandEnvelope]]]:
    snapshot_store = DashboardSnapshotStore(wall_time=lambda: 100.0)
    snapshot_store.publish(_minimal_snapshot(), ["启动发动机"])
    control_store = DashboardControlStore()
    control_store.publish(_control_projection())
    envelopes: list[WebCommandEnvelope] = []

    def enqueue(envelope: WebCommandEnvelope) -> bool:
        envelopes.append(envelope)
        return True

    runtime = WebDashboardRuntime(
        snapshot_store,
        control_store=control_store,
        command_sink=enqueue,
        preferred_port=0,
    )
    runtime.start()
    try:
        yield runtime, envelopes
    finally:
        runtime.stop()


def _request(
    runtime: WebDashboardRuntime,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    assert runtime.port is not None
    connection = http.client.HTTPConnection("127.0.0.1", runtime.port, timeout=3)
    merged = {"Host": f"127.0.0.1:{runtime.port}", **(headers or {})}
    connection.request(method, path, body=body, headers=merged)
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


def _control_session(runtime: WebDashboardRuntime) -> tuple[str, dict]:
    cookie = _pair(runtime)
    status, _, body = _request(
        runtime,
        "GET",
        "/api/v1/control-state",
        headers={"Cookie": cookie},
    )
    assert status == 200
    return cookie, json.loads(body)


def _post_command(
    runtime: WebDashboardRuntime,
    cookie: str,
    csrf: str,
    command_id: str,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    assert runtime.port is not None
    body = json.dumps(payload, separators=(",", ":"))
    base_headers = {
        "Cookie": cookie,
        "Origin": f"http://127.0.0.1:{runtime.port}",
        "X-Bomana-CSRF": csrf,
        "Idempotency-Key": command_id,
        "Content-Type": "application/json",
    }
    return _request(
        runtime,
        "POST",
        "/api/v1/commands",
        headers={**base_headers, **(headers or {})},
        body=body,
    )


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
        ("/assets/qrcode.js", "text/javascript"),
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


def test_lan_enable_keeps_every_successful_exact_private_listener(monkeypatch) -> None:
    store = DashboardSnapshotStore()
    runtime = WebDashboardRuntime(
        store,
        preferred_port=0,
        address_provider=lambda: [
            "192.168.31.69",
            "172.20.0.1",
            "10.126.126.2",
            "192.168.31.69",
        ],
    )
    runtime.start()
    assert runtime.port is not None
    stopped = []
    real_stop = runtime._stop_listener

    def fake_start(address, port):
        if address == "172.20.0.1":
            raise OSError("adapter unavailable")
        return _Listener(
            server=SimpleNamespace(server_address=(address, port)),
            thread=SimpleNamespace(),
            address=address,
        )

    monkeypatch.setattr(runtime, "_start_listener", fake_start)
    monkeypatch.setattr(
        runtime, "_stop_listener", lambda listener: stopped.append(listener.address)
    )
    try:
        assert runtime.enable_lan() == "192.168.31.69"
        assert runtime.lan_control_enabled is True
        assert runtime.lan_addresses == ("192.168.31.69", "10.126.126.2")
        assert runtime.lan_urls == (
            f"http://192.168.31.69:{runtime.port}/",
            f"http://10.126.126.2:{runtime.port}/",
        )
        for address in runtime.lan_addresses:
            assert runtime.security.host_allowed(f"{address}:{runtime.port}")
        runtime.disable_lan()
        assert stopped == ["192.168.31.69", "10.126.126.2"]
        assert runtime.lan_addresses == ()
        assert runtime.lan_control_enabled is False
    finally:
        monkeypatch.setattr(runtime, "_stop_listener", real_stop)
        runtime.stop()


def test_lan_enable_rolls_back_listeners_if_control_authority_fails(monkeypatch) -> None:
    runtime = WebDashboardRuntime(
        DashboardSnapshotStore(),
        preferred_port=0,
        address_provider=lambda: ["192.168.31.69"],
    )
    runtime.start()
    assert runtime.port is not None
    stopped: list[str] = []
    real_stop = runtime._stop_listener

    monkeypatch.setattr(
        runtime,
        "_start_listener",
        lambda address, port: _Listener(
            server=SimpleNamespace(server_address=(address, port)),
            thread=SimpleNamespace(),
            address=address,
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_stop_listener",
        lambda listener: stopped.append(listener.address),
    )
    monkeypatch.setattr(
        runtime.security,
        "enable_lan_control",
        lambda: (_ for _ in ()).throw(RuntimeError("control unavailable")),
    )
    try:
        with pytest.raises(RuntimeError, match="control unavailable"):
            runtime.enable_lan()
        assert runtime.lan_addresses == ()
        assert runtime.lan_control_enabled is False
        assert stopped == ["192.168.31.69"]
        assert not runtime.security.host_allowed(f"192.168.31.69:{runtime.port}")
    finally:
        monkeypatch.setattr(runtime, "_stop_listener", real_stop)
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
        "qrcode.js",
        "favicon.svg",
    }


def test_map_image_route_is_paired_and_serves_only_published_bytes(
    running_dashboard: WebDashboardRuntime,
) -> None:
    status, _, _ = _request(running_dashboard, "GET", "/api/v1/map-image")
    assert status == 401
    cookie = _pair(running_dashboard)
    status, _, _ = _request(
        running_dashboard,
        "GET",
        "/api/v1/map-image",
        headers={"Cookie": cookie},
    )
    assert status == 404

    body = b"\x89PNG\r\n\x1a\nmap"
    assert running_dashboard.store.publish_map_image(body, "image/png") is True
    status, headers, returned = _request(
        running_dashboard,
        "GET",
        "/api/v1/map-image",
        headers={"Cookie": cookie},
    )
    assert status == 200
    assert headers["content-type"] == "image/png"
    assert headers["cache-control"].startswith("no-store")
    assert returned == body


def test_map_icon_font_route_is_paired_and_serves_only_valid_published_bytes(
    running_dashboard: WebDashboardRuntime,
) -> None:
    route = "/api/v1/map-icons-font"
    assert _request(running_dashboard, "GET", route)[0] == 401
    cookie = _pair(running_dashboard)
    assert _request(running_dashboard, "GET", route, headers={"Cookie": cookie})[0] == 404

    body = b"\x00\x01\x00\x00" + b"official-font"
    assert running_dashboard.store.publish_map_icon_font(body) is True
    status, headers, returned = _request(
        running_dashboard, "GET", route, headers={"Cookie": cookie}
    )
    assert status == 200
    assert headers["content-type"] == "font/ttf"
    assert headers["cache-control"].startswith("no-store")
    assert returned == body


def test_each_pairing_creates_a_distinct_control_session_and_csrf(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, _ = controlled_dashboard

    first_cookie, first_state = _control_session(runtime)
    second_cookie, second_state = _control_session(runtime)

    assert first_cookie != second_cookie
    assert first_state["permissions"]["scope"] == "control"
    assert first_state["permissions"]["transport"] == "loopback"
    assert first_state["csrf"] != second_state["csrf"]
    assert set(first_state["capabilities"]["commands"]) == set(COMMAND_NAMES)


def test_command_is_queued_once_replayed_and_completed_per_session(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)
    other_cookie, other_state = _control_session(runtime)
    payload = {"schema_version": 1, "command": "state.set_locked", "locked": True}

    first = _post_command(runtime, cookie, state["csrf"], "lock-1", payload)
    replay = _post_command(runtime, cookie, state["csrf"], "lock-1", payload)

    assert first[0] == replay[0] == 202
    assert (
        json.loads(first[2])
        == json.loads(replay[2])
        == {
            "schema_version": 1,
            "command_id": "lock-1",
            "status": "queued",
            "submitted_revision": 1,
        }
    )
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope.command.name == "state.set_locked"
    assert envelope.command.locked is True
    assert runtime.reauthorize_command(envelope) is True

    runtime.publish_control_state(_control_projection(2))
    assert (
        runtime.publish_command_completion(
            envelope,
            status="succeeded",
            reason="ok",
            resulting_revision=2,
        )
        is True
    )
    assert (
        runtime.publish_command_completion(
            envelope,
            status="succeeded",
            reason="ok",
            resulting_revision=2,
        )
        is False
    )

    _, _, own_body = _request(
        runtime,
        "GET",
        "/api/v1/control-state",
        headers={"Cookie": cookie},
    )
    _, _, other_body = _request(
        runtime,
        "GET",
        "/api/v1/control-state",
        headers={"Cookie": other_cookie},
    )
    assert json.loads(own_body)["recent_commands"] == [
        {
            "command_id": "lock-1",
            "command": "state.set_locked",
            "status": "succeeded",
            "reason": "ok",
            "submitted_revision": 1,
            "resulting_revision": 2,
        }
    ]
    assert json.loads(other_body)["recent_commands"] == []
    assert other_state["csrf"] != state["csrf"]


def test_reusing_idempotency_key_for_different_body_conflicts(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)

    assert (
        _post_command(
            runtime,
            cookie,
            state["csrf"],
            "beep-1",
            {"schema_version": 1, "command": "state.set_beep_enabled", "enabled": True},
        )[0]
        == 202
    )
    status, _, body = _post_command(
        runtime,
        cookie,
        state["csrf"],
        "beep-1",
        {"schema_version": 1, "command": "state.set_beep_enabled", "enabled": False},
    )

    assert status == 409
    assert json.loads(body)["error"] == "idempotency_conflict"
    assert len(envelopes) == 1


def test_accepted_idempotency_replay_survives_later_capability_change(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)
    payload = {"schema_version": 1, "command": "state.set_locked", "locked": True}
    first = _post_command(runtime, cookie, state["csrf"], "lock-replay", payload)
    projection = _control_projection(2)
    runtime.publish_control_state(
        ControlStateProjection(
            **{
                **projection.__dict__,
                "commands": ("action.cycle_corner",),
                "panel_targets": (),
            }
        )
    )

    replay = _post_command(runtime, cookie, state["csrf"], "lock-replay", payload)

    assert first[0] == replay[0] == 202
    assert json.loads(first[2]) == json.loads(replay[2])
    assert len(envelopes) == 1


def test_unicode_semantic_value_has_a_stable_replay_digest(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)
    payload = {"schema_version": 1, "command": "weapon.select", "weapon_id": "测试武器"}

    first = _post_command(runtime, cookie, state["csrf"], "unicode-1", payload)
    replay = _post_command(runtime, cookie, state["csrf"], "unicode-1", payload)

    assert first[0] == replay[0] == 202
    assert json.loads(first[2]) == json.loads(replay[2])
    assert len(envelopes) == 1


def test_queue_failure_is_not_retained_and_same_key_can_retry(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)
    payload = {"schema_version": 1, "command": "action.cycle_corner"}
    runtime.set_command_sink(None)

    status, _, body = _post_command(runtime, cookie, state["csrf"], "corner-1", payload)
    assert status == 503
    assert json.loads(body)["error"] == "queue_unavailable"
    assert envelopes == []

    def enqueue(envelope: WebCommandEnvelope) -> bool:
        envelopes.append(envelope)
        return True

    runtime.set_command_sink(enqueue)
    assert _post_command(runtime, cookie, state["csrf"], "corner-1", payload)[0] == 202
    assert len(envelopes) == 1


@pytest.mark.parametrize(
    ("header_changes", "expected_status", "expected_error"),
    [
        ({"Origin": ""}, 403, "origin_required"),
        ({"Origin": "http://localhost:1"}, 403, "origin_mismatch"),
        ({"X-Bomana-CSRF": "wrong"}, 403, "csrf_invalid"),
        ({"Content-Type": "application/json; charset=utf-8"}, 415, "content_type_required"),
        ({"Idempotency-Key": "bad key"}, 400, "idempotency_invalid"),
    ],
)
def test_command_requires_exact_origin_csrf_content_type_and_idempotency(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
    header_changes: dict[str, str],
    expected_status: int,
    expected_error: str,
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)

    status, _, body = _post_command(
        runtime,
        cookie,
        state["csrf"],
        "strict-1",
        {"schema_version": 1, "command": "action.cycle_corner"},
        headers=header_changes,
    )

    assert status == expected_status
    assert json.loads(body)["error"] == expected_error
    assert envelopes == []


@pytest.mark.parametrize(
    ("raw_body", "expected_error"),
    [
        (b'{"schema_version":1,"command":"action.cycle_corner"} trailing', "invalid_json"),
        (
            b'{"schema_version":1,"schema_version":1,"command":"action.cycle_corner"}',
            "invalid_json",
        ),
        (
            b'{"schema_version":1,"command":"action.reset_timer","confirmed":false}',
            "schema_invalid",
        ),
        (b'{"schema_version":1,"command":"action.cycle_corner","value":NaN}', "invalid_json"),
    ],
)
def test_command_body_is_one_strict_json_value_matching_shared_schema(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
    raw_body: bytes,
    expected_error: str,
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)
    assert runtime.port is not None

    status, _, body = _request(
        runtime,
        "POST",
        "/api/v1/commands",
        headers={
            "Cookie": cookie,
            "Origin": f"http://127.0.0.1:{runtime.port}",
            "X-Bomana-CSRF": state["csrf"],
            "Idempotency-Key": "json-1",
            "Content-Type": "application/json",
        },
        body=raw_body,
    )

    assert status == 400
    assert json.loads(body)["error"] == expected_error
    assert envelopes == []


def test_command_body_over_4096_bytes_fails_before_queueing(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)
    assert runtime.port is not None

    status, _, body = _request(
        runtime,
        "POST",
        "/api/v1/commands",
        headers={
            "Cookie": cookie,
            "Origin": f"http://127.0.0.1:{runtime.port}",
            "X-Bomana-CSRF": state["csrf"],
            "Idempotency-Key": "large-1",
            "Content-Type": "application/json",
        },
        body=b"x" * 4097,
    )

    assert status == 413
    assert json.loads(body)["error"] == "body_too_large"
    assert envelopes == []


def test_command_body_accepts_only_json_whitespace_around_one_value(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, envelopes = controlled_dashboard
    cookie, state = _control_session(runtime)
    assert runtime.port is not None
    body = b'\r\n {"schema_version":1,"command":"action.cycle_corner"}\t '

    status, _, _ = _request(
        runtime,
        "POST",
        "/api/v1/commands",
        headers={
            "Cookie": cookie,
            "Origin": f"http://127.0.0.1:{runtime.port}",
            "X-Bomana-CSRF": state["csrf"],
            "Idempotency-Key": "whitespace-1",
            "Content-Type": "application/json",
        },
        body=body,
    )

    assert status == 202
    assert len(envelopes) == 1


def test_current_capabilities_are_checked_before_queueing(
    controlled_dashboard: tuple[WebDashboardRuntime, list[WebCommandEnvelope]],
) -> None:
    runtime, envelopes = controlled_dashboard
    initial = _control_projection(2)
    runtime.publish_control_state(
        ControlStateProjection(
            **{
                **initial.__dict__,
                "commands": ("action.cycle_corner",),
                "panel_targets": (),
            }
        )
    )
    cookie, state = _control_session(runtime)

    status, _, body = _post_command(
        runtime,
        cookie,
        state["csrf"],
        "weapon-1",
        {"schema_version": 1, "command": "weapon.select", "weapon_id": "aim_9l"},
    )

    assert status == 409
    assert json.loads(body)["error"] == "capability_unavailable"
    assert envelopes == []


def test_lan_control_rotation_and_revocation_are_immediate() -> None:
    security = _SecurityState()
    old_code = security.pairing_code
    result, view_token = security.verify_pairing("client-1", old_code, "lan")
    assert result == "ok"
    assert view_token is not None
    view = security.session_view(f"bomana_session={view_token}")
    assert view is not None and view.scope == "view"

    assert security.enable_lan_control() is True
    assert security.pairing_code != old_code
    assert security.verify_pairing("client-2", old_code, "lan")[0] == "invalid"
    result, control_token = security.verify_pairing("client-3", security.pairing_code, "lan")
    assert result == "ok"
    assert control_token is not None
    control = security.session_view(f"bomana_session={control_token}")
    assert control is not None and control.scope == "control"
    command = validate_command_payload({"schema_version": 1, "command": "action.cycle_corner"})
    envelopes: list[WebCommandEnvelope] = []
    bridge = _CommandBridge(lambda envelope: envelopes.append(envelope) is None)
    submitted = security.submit_command(
        control,
        csrf=control.csrf,
        command_id="lan-1",
        command=command,
        submitted_revision=1,
        capability_available=True,
        bridge=bridge,
    )
    assert submitted.kind == "accepted"
    assert security.reauthorize_command(envelopes[0]) is True

    assert security.disable_lan_control() is True
    assert security.reauthorize_command(envelopes[0]) is False
    assert security.session_view(f"bomana_session={control_token}") is None
    still_view = security.session_view(f"bomana_session={view_token}")
    assert still_view is not None and still_view.scope == "view"


def test_session_expiry_is_rechecked_at_submit_and_tk_reauthorization() -> None:
    now = [0.0]
    command = validate_command_payload({"schema_version": 1, "command": "action.cycle_corner"})

    submit_security = _SecurityState(monotonic=lambda: now[0])
    result, token = submit_security.verify_pairing(
        "submit-client",
        submit_security.pairing_code,
        "loopback",
    )
    assert result == "ok" and token is not None
    submit_view = submit_security.session_view(f"bomana_session={token}")
    assert submit_view is not None
    submit_envelopes: list[WebCommandEnvelope] = []
    now[0] = SESSION_MAX_AGE_SEC + 1

    submitted = submit_security.submit_command(
        submit_view,
        csrf=submit_view.csrf,
        command_id="expired-submit",
        command=command,
        submitted_revision=1,
        capability_available=True,
        bridge=_CommandBridge(lambda envelope: submit_envelopes.append(envelope) is None),
    )

    assert submitted.kind == "authorization_revoked"
    assert submit_envelopes == []

    now[0] = 0.0
    execute_security = _SecurityState(monotonic=lambda: now[0])
    result, token = execute_security.verify_pairing(
        "execute-client",
        execute_security.pairing_code,
        "loopback",
    )
    assert result == "ok" and token is not None
    execute_view = execute_security.session_view(f"bomana_session={token}")
    assert execute_view is not None
    execute_envelopes: list[WebCommandEnvelope] = []
    accepted = execute_security.submit_command(
        execute_view,
        csrf=execute_view.csrf,
        command_id="expire-before-execute",
        command=command,
        submitted_revision=1,
        capability_available=True,
        bridge=_CommandBridge(lambda envelope: execute_envelopes.append(envelope) is None),
    )
    assert accepted.kind == "accepted"
    assert len(execute_envelopes) == 1

    now[0] = SESSION_MAX_AGE_SEC + 1

    assert execute_security.reauthorize_command(execute_envelopes[0]) is False
    assert execute_security.session_view(f"bomana_session={token}") is None


def test_session_retains_128_accepted_idempotency_keys_without_eviction() -> None:
    security = _SecurityState()
    result, token = security.verify_pairing("local", security.pairing_code, "loopback")
    assert result == "ok" and token is not None
    view = security.session_view(f"bomana_session={token}")
    assert view is not None
    command = validate_command_payload({"schema_version": 1, "command": "action.cycle_corner"})
    bridge = _CommandBridge(lambda _envelope: True)

    for index in range(128):
        submitted = security.submit_command(
            view,
            csrf=view.csrf,
            command_id=f"key-{index}",
            command=command,
            submitted_revision=1,
            capability_available=True,
            bridge=bridge,
        )
        assert submitted.kind == "accepted"
    assert (
        security.submit_command(
            view,
            csrf=view.csrf,
            command_id="key-overflow",
            command=command,
            submitted_revision=1,
            capability_available=True,
            bridge=bridge,
        ).kind
        == "idempotency_capacity"
    )
    assert (
        security.submit_command(
            view,
            csrf=view.csrf,
            command_id="key-0",
            command=command,
            submitted_revision=1,
            capability_available=True,
            bridge=bridge,
        ).kind
        == "replay"
    )
