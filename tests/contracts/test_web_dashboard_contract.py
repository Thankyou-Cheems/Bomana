# enforces: docs/specs/web-dashboard.md WDB-01..WDB-09 WDB-11..WDB-18 WDB-20..WDB-51
# enforces: docs/specs/threading-ui-contract.md THREAD-10..THREAD-13

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVER = (ROOT / "bomana/web/server.py").read_text(encoding="utf-8")
SNAPSHOT = (ROOT / "bomana/web/snapshot.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "bomana/ui/runtime_services.py").read_text(encoding="utf-8")
APP = (ROOT / "bomana/ui/app.py").read_text(encoding="utf-8")
HTML = (ROOT / "bomana/assets/web/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "bomana/assets/web/dashboard.css").read_text(encoding="utf-8")
JS = (ROOT / "bomana/assets/web/dashboard.js").read_text(encoding="utf-8")
SCHEMA_DIR = ROOT / "docs/specs/schemas"
COMMAND_SCHEMA = json.loads(
    (SCHEMA_DIR / "web-dashboard-command.schema.json").read_text(encoding="utf-8")
)
RESPONSE_SCHEMA = json.loads(
    (SCHEMA_DIR / "web-dashboard-command-response.schema.json").read_text(encoding="utf-8")
)
CONTROL_STATE_SCHEMA = json.loads(
    (SCHEMA_DIR / "web-dashboard-control-state.schema.json").read_text(encoding="utf-8")
)

COMMAND_NAMES = {
    "action.reset_timer",
    "action.cycle_corner",
    "state.set_locked",
    "state.set_beep_enabled",
    "state.set_zone_sound_enabled",
    "config.set_panel_visibility",
    "config.set_timer_cycle_minutes",
    "weapon.select",
    "weapon.set_ballistic_model",
}
PANEL_TARGETS = {
    "zones",
    "airfields",
    "fuel",
    "speed",
    "checklist",
    "weapon_solution",
}


def _schema_errors(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str = "$",
) -> list[str]:
    if "$ref" in schema:
        prefix = "#/$defs/"
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith(prefix):
            return [f"{path}: unsupported ref {ref!r}"]
        return _schema_errors(value, root["$defs"][ref.removeprefix(prefix)], root, path)

    errors: list[str] = []
    if "oneOf" in schema:
        matches = [
            branch for branch in schema["oneOf"] if not _schema_errors(value, branch, root, path)
        ]
        if len(matches) != 1:
            errors.append(f"{path}: expected exactly one oneOf match, got {len(matches)}")
            return errors

    expected_type = schema.get("type")
    type_ok = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
    }
    if expected_type is not None and not type_ok.get(expected_type, False):
        return [f"{path}: expected {expected_type}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const mismatch")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: enum mismatch")

    if isinstance(value, dict):
        required = set(schema.get("required", []))
        missing = required - set(value)
        errors.extend(f"{path}: missing {name}" for name in sorted(missing))
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors.extend(
                f"{path}: unexpected {name}" for name in sorted(set(value) - set(properties))
            )
        for name, child in value.items():
            if name in properties:
                errors.extend(_schema_errors(child, properties[name], root, f"{path}.{name}"))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: too many items")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{path}: duplicate items")
        if "items" in schema:
            for index, child in enumerate(value):
                errors.extend(_schema_errors(child, schema["items"], root, f"{path}[{index}]"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: too long")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            errors.append(f"{path}: pattern mismatch")

    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    ):
        errors.append(f"{path}: below minimum")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and "maximum" in schema
        and value > schema["maximum"]
    ):
        errors.append(f"{path}: above maximum")

    for child in schema.get("allOf", []):
        errors.extend(_schema_errors(value, child, root, path))
    if "if" in schema:
        branch = "then" if not _schema_errors(value, schema["if"], root, path) else "else"
        if branch in schema:
            errors.extend(_schema_errors(value, schema[branch], root, path))
    return errors


def _assert_valid(schema: dict[str, Any], value: Any) -> None:
    assert not _schema_errors(value, schema, schema)


def _assert_invalid(schema: dict[str, Any], value: Any) -> None:
    assert _schema_errors(value, schema, schema)


def _control_state(*, scope: str = "control") -> dict[str, Any]:
    commands = sorted(COMMAND_NAMES) if scope == "control" else []
    panels = sorted(PANEL_TARGETS) if scope == "control" else []
    return {
        "schema_version": 1,
        "revision": 2,
        "permissions": {
            "scope": scope,
            "transport": "loopback" if scope == "control" else "lan",
            "control_epoch": 3,
            "lan_control_enabled": False,
        },
        "csrf": "c" * 43 if scope == "control" else None,
        "capabilities": {"commands": commands, "panel_targets": panels},
        "state": {
            "locked": True,
            "beep_enabled": True,
            "zone_sound_enabled": False,
            "timer_cycle_minutes": 15,
            "panel_visibility": {
                "zones": True,
                "airfields": True,
                "fuel": True,
                "speed": True,
                "checklist": True,
                "weapon_solution": True,
            },
            "selected_weapon_id": "agm_65d",
            "ballistic_model": "foxthree_compatible",
        },
        "weapons": [
            {
                "weapon_id": "agm_65d",
                "display_name": "AGM-65D",
                "role": "agm",
                "compatible": True,
                "selected": True,
            }
        ],
        "recent_commands": [
            {
                "command_id": "mobile-1",
                "command": "weapon.select",
                "status": "succeeded",
                "reason": "ok",
                "submitted_revision": 1,
                "resulting_revision": 2,
            }
        ],
    }


def test_command_schema_is_the_exact_nine_command_matrix() -> None:
    definitions = COMMAND_SCHEMA["$defs"]
    commands = {definition["properties"]["command"]["const"] for definition in definitions.values()}
    assert commands == COMMAND_NAMES
    assert len(COMMAND_SCHEMA["oneOf"]) == len(COMMAND_NAMES) == 9
    assert set(definitions["setPanelVisibility"]["properties"]["target"]["enum"]) == (PANEL_TARGETS)
    assert definitions["setBallisticModel"]["properties"]["model"]["enum"] == [
        "foxthree_compatible",
        "strict_official",
    ]
    assert definitions["resetTimer"]["properties"]["confirmed"] == {"const": True}
    assert definitions["setTimerCycleMinutes"]["properties"]["minutes"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 180,
    }


def test_command_schema_accepts_only_exact_bounded_semantic_requests() -> None:
    accepted = [
        {"schema_version": 1, "command": "action.reset_timer", "confirmed": True},
        {"schema_version": 1, "command": "action.cycle_corner"},
        {"schema_version": 1, "command": "state.set_locked", "locked": False},
        {"schema_version": 1, "command": "state.set_beep_enabled", "enabled": True},
        {
            "schema_version": 1,
            "command": "state.set_zone_sound_enabled",
            "enabled": False,
        },
        {
            "schema_version": 1,
            "command": "config.set_panel_visibility",
            "target": "weapon_solution",
            "enabled": True,
        },
        {
            "schema_version": 1,
            "command": "config.set_timer_cycle_minutes",
            "minutes": 60,
        },
        {"schema_version": 1, "command": "weapon.select", "weapon_id": "agm_65d"},
        {
            "schema_version": 1,
            "command": "weapon.set_ballistic_model",
            "model": "strict_official",
        },
    ]
    for request in accepted:
        _assert_valid(COMMAND_SCHEMA, request)

    rejected = [
        {"schema_version": 1, "command": "action.reset_timer", "confirmed": False},
        {"schema_version": 1, "command": "state.toggle_locked"},
        {"schema_version": 1, "command": "action.cycle_corner", "callback": "_next_corner"},
        {
            "schema_version": 1,
            "command": "config.set_panel_visibility",
            "target": "arbitrary.config.path",
            "enabled": True,
        },
        {
            "schema_version": 1,
            "command": "config.set_timer_cycle_minutes",
            "minutes": 0,
        },
        {
            "schema_version": 1,
            "command": "config.set_timer_cycle_minutes",
            "minutes": 181,
        },
        {
            "schema_version": 1,
            "command": "config.set_timer_cycle_minutes",
            "minutes": True,
        },
        {"schema_version": 1, "command": "weapon.select", "weapon_id": ""},
        {
            "schema_version": 1,
            "command": "weapon.set_ballistic_model",
            "model": "custom",
        },
        {"schema_version": 1, "command": "shell.execute", "command_line": "whoami"},
    ]
    for request in rejected:
        _assert_invalid(COMMAND_SCHEMA, request)


def test_command_response_schema_pins_async_and_stable_error_shapes() -> None:
    _assert_valid(
        RESPONSE_SCHEMA,
        {
            "schema_version": 1,
            "command_id": "mobile-1",
            "status": "queued",
            "submitted_revision": 7,
        },
    )
    _assert_valid(
        RESPONSE_SCHEMA,
        {
            "schema_version": 1,
            "status": "error",
            "error": "idempotency_conflict",
            "command_id": "mobile-1",
        },
    )
    _assert_valid(
        RESPONSE_SCHEMA,
        {"schema_version": 1, "status": "error", "error": "queue_unavailable"},
    )
    _assert_invalid(
        RESPONSE_SCHEMA,
        {
            "schema_version": 1,
            "command_id": "mobile-1",
            "status": "succeeded",
            "submitted_revision": 7,
        },
    )
    _assert_invalid(
        RESPONSE_SCHEMA,
        {"schema_version": 1, "status": "error", "error": "internal traceback"},
    )


def test_control_state_schema_pins_scope_csrf_capabilities_and_bounds() -> None:
    control = _control_state(scope="control")
    view = _control_state(scope="view")
    _assert_valid(CONTROL_STATE_SCHEMA, control)
    _assert_valid(CONTROL_STATE_SCHEMA, view)

    invalid_control = copy.deepcopy(control)
    invalid_control["csrf"] = None
    _assert_invalid(CONTROL_STATE_SCHEMA, invalid_control)

    invalid_view = copy.deepcopy(view)
    invalid_view["csrf"] = "c" * 43
    _assert_invalid(CONTROL_STATE_SCHEMA, invalid_view)

    invalid_view_commands = copy.deepcopy(view)
    invalid_view_commands["capabilities"]["commands"] = ["action.cycle_corner"]
    _assert_invalid(CONTROL_STATE_SCHEMA, invalid_view_commands)

    too_many_completions = copy.deepcopy(control)
    too_many_completions["recent_commands"] = control["recent_commands"] * 65
    _assert_invalid(CONTROL_STATE_SCHEMA, too_many_completions)


def test_schema_bounds_match_http_and_session_contract() -> None:
    command_id = RESPONSE_SCHEMA["$defs"]["commandId"]
    assert command_id["pattern"] == "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    assert CONTROL_STATE_SCHEMA["properties"]["recent_commands"]["maxItems"] == 64
    assert CONTROL_STATE_SCHEMA["properties"]["weapons"]["maxItems"] == 512
    assert CONTROL_STATE_SCHEMA["$defs"]["capabilities"]["properties"]["commands"]["maxItems"] == 9


def test_server_is_dedicated_loopback_first_and_never_an_8111_proxy() -> None:
    assert 'self._start_listener("127.0.0.1"' in SERVER
    assert "DEFAULT_PORT = 8777" in SERVER
    assert "8111" not in SERVER
    assert "NetworkConfig" not in SERVER
    assert "requests" not in SERVER
    assert "urllib.request" not in SERVER
    assert "proxy" not in SERVER.lower()


def test_server_has_no_tk_dependency_and_app_publishes_snapshot_state() -> None:
    control_path = ROOT / "bomana/web/control.py"
    assert control_path.exists()
    control = control_path.read_text(encoding="utf-8")
    assert "tkinter" not in SERVER
    assert "bomana.ui" not in SERVER
    assert "tkinter" not in control
    assert "bomana.ui" not in control
    assert "ConfigManager" not in control
    assert "PanelConfig" not in control
    assert "publish_dashboard(snap, list(self.chk_items))" in APP
    assert "DashboardSnapshotStore" in RUNTIME


def test_lan_and_tray_paths_use_auto_discovery_and_one_control_action() -> None:
    assert "_is_rfc1918" in SERVER
    assert "discover_private_ipv4" in SERVER
    assert "self.address_provider()" in SERVER
    assert '("0.0.0.0"' not in SERVER
    assert "10.126.126.2" not in SERVER
    assert "192.168.31.69" not in SERVER
    assert "enable_dashboard_lan" in RUNTIME
    assert "disable_dashboard_lan" in RUNTIME
    assert "enable_dashboard_lan_control" not in RUNTIME
    assert "disable_dashboard_lan_control" not in RUNTIME
    assert "开启局域网访问与控制" in RUNTIME
    assert "app.dispatcher.post(app._toggle_web_dashboard_lan)" in RUNTIME
    assert "app.dispatcher.post(app._toggle_web_dashboard_lan_control)" not in RUNTIME
    assert "app.dispatcher.post(app._open_web_dashboard)" in RUNTIME
    assert "web_dashboard_lan_enabled" in RUNTIME
    assert "lan_addresses" in SERVER
    assert "for address in addresses" in SERVER
    main_window = (ROOT / "bomana/ui/main_window.py").read_text(encoding="utf-8")
    assert "web_access_row" in APP or "web_access_row" in main_window

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Enabling LAN also grants fixed-function control" in readme
    assert "disabling LAN immediately invalidates every LAN session" in readme
    assert "keeps LAN sessions view-only unless control is explicitly enabled" not in readme


def test_map_projection_allowlist_includes_current_hostile_units_not_raw_payloads() -> None:
    assert 'allowed.update(("poi", "traceback"))' in SNAPSHOT
    assert 'allowed.add("zone")' in SNAPSHOT
    assert 'allowed.add("airfield")' in SNAPSHOT
    assert "HOSTILE_MAP_KINDS" in SNAPSHOT
    assert '"hostile_aircraft"' in SNAPSHOT
    assert '"hostile_ground"' in SNAPSHOT
    assert '"hostile_naval"' in SNAPSHOT
    assert '"hostile_unit"' in SNAPSHOT
    assert "hostile_air_contacts" not in SNAPSHOT
    assert "source_debug" not in SNAPSHOT
    assert "perf_debug" not in SNAPSHOT
    assert "hostile_aircraft" in JS
    assert "hostile_ground" in JS
    assert "hostile_naval" in JS


def test_routes_auth_headers_and_no_cors_are_closed_by_construction() -> None:
    for route in (
        'path == "/"',
        'path == "/healthz"',
        'path == "/api/v1/snapshot"',
        'path == "/api/v1/control-state"',
        'path == "/api/v1/map-image"',
        'path == "/api/v1/commands"',
        '"/assets/dashboard.css"',
        '"/assets/dashboard.js"',
        '"/assets/app.png"',
        '"/favicon.svg"',
    ):
        assert route in SERVER
    assert "SimpleCookie" in SERVER
    assert "SameSite=Strict" in SERVER
    assert "HttpOnly" in SERVER
    assert "host_allowed" in SERVER
    assert "_origin_allowed" in SERVER
    assert "X-Bomana-CSRF" in SERVER
    assert "Idempotency-Key" in SERVER
    assert "Content-Length" in SERVER
    assert "Transfer-Encoding" in SERVER
    assert "MAX_COMMAND_BODY_BYTES = 4096" in SERVER
    assert "MAX_IDEMPOTENCY_KEYS = 128" in SERVER
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
    assert 'fetch("/api/v1/control-state"' in JS
    assert 'fetch("/api/v1/commands"' in JS
    assert 'fetch("/api/v1/map-image"' in JS
    assert "innerHTML" not in JS
    assert 'data-capability="weapon"' in HTML
    assert 'querySelectorAll("[data-capability]")' in JS
    assert ".capability-hidden" in CSS
    assert "缺少官方数据时：使用推测替代" in HTML
    assert "缺少官方数据时：不应用模型" in HTML
    assert "官方数据始终优先" in HTML
    assert "Bomana 托盘" not in HTML
    assert 'src="/assets/app.png"' in HTML
    assert "weaponRange" in JS
    assert "mapImage" in JS


def test_command_dispatch_is_explicit_immutable_and_owner_thread_revalidated() -> None:
    control_path = ROOT / "bomana/web/control.py"
    assert control_path.exists()
    control = control_path.read_text(encoding="utf-8")
    combined_executor = "\n".join((APP, RUNTIME))

    for command in COMMAND_NAMES:
        assert command in control
    for forbidden in (
        "callback_name",
        "config_path",
        "command_line",
        "keybd_event",
        "SendInput",
        "pyautogui",
        "subprocess",
        "eval(",
        "exec(",
    ):
        assert forbidden not in control
    assert "frozen=True" in control
    assert "dispatcher.post(" in combined_executor
    queue_sink = RUNTIME.split("def _queue_web_command", 1)[1].split("def init_dashboard", 1)[0]
    assert "self.app" not in queue_sink
    assert "_web_command_queue_open.is_set()" in queue_sink
    assert "authorization_epoch" in combined_executor
    assert "recent_commands" in combined_executor
    assert "resulting_revision" in combined_executor
    for gate in (
        "ENABLE_CCRP",
        "ENABLE_ZONES",
        "ENABLE_AIRFIELDS",
        "ENABLE_FUEL",
        "ENABLE_CHECKLIST",
    ):
        assert gate in combined_executor
    assert ".compatible(" in combined_executor


def test_production_and_tests_load_the_same_three_control_schemas() -> None:
    control_path = ROOT / "bomana/web/control.py"
    assert control_path.exists()
    production = "\n".join((SERVER, control_path.read_text(encoding="utf-8")))
    for name in (
        "web-dashboard-command.schema.json",
        "web-dashboard-command-response.schema.json",
        "web-dashboard-control-state.schema.json",
    ):
        assert name in production
        assert (SCHEMA_DIR / name).exists()


def test_all_packaging_paths_include_web_assets_and_runtime_modules() -> None:
    portable = (ROOT / "tools/build_portable.py").read_text(encoding="utf-8")
    build_bat = (ROOT / "tools/scripts/build.bat").read_text(encoding="utf-8")
    build_sh = (ROOT / "tools/scripts/build.sh").read_text(encoding="utf-8")

    assert "app_root = root / APP_DIR" in portable
    assert 'app_root.rglob("*")' in portable
    for name in (
        "web-dashboard-command.schema.json",
        "web-dashboard-command-response.schema.json",
        "web-dashboard-control-state.schema.json",
    ):
        assert name in portable
    assert '"http.server"' in portable
    assert '"http.cookies"' in portable
    assert '"ipaddress"' in portable
    assert '--add-data "bomana/assets;bomana/assets"' in build_bat
    assert '"--add-data" "bomana/assets:bomana/assets"' in build_sh
