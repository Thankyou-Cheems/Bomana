"""Hardened standard-library HTTP runtime for the Bomana Web Cockpit."""

from __future__ import annotations

import contextlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bomana.utils.file_utils import resource_path
from bomana.web.control import (
    COMPLETION_REASONS,
    CompletionReason,
    CompletionStatus,
    ControlScope,
    ControlStateProjection,
    ControlValidationError,
    DashboardControlStore,
    Transport,
    ValidatedWebCommand,
    WebCommandEnvelope,
    build_control_state_payload,
    validate_command_payload,
    validate_command_response,
)
from bomana.web.snapshot import DashboardSnapshotStore, build_dashboard_payload

DEFAULT_PORT = 8777
PORT_SEARCH_COUNT = 11
PAIRING_ATTEMPT_LIMIT = 8
PAIRING_WINDOW_SEC = 60.0
SESSION_MAX_AGE_SEC = 43_200.0
MAX_SESSIONS = 256
MAX_PAIRING_CLIENTS = 256
MAX_COMMAND_BODY_BYTES = 4096
MAX_IDEMPOTENCY_KEYS = 128
MAX_RECENT_COMMANDS = 64
COOKIE_NAME = "bomana_session"

_IDEMPOTENCY_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_RFC1918_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)

_SECURITY_HEADERS = (
    ("Cache-Control", "no-store, max-age=0"),
    ("Pragma", "no-cache"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    (
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    ),
    (
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    ),
)


def _constant_time_text_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


class DashboardServerError(RuntimeError):
    """Raised when a requested dashboard listener cannot be started."""


@dataclass
class _Listener:
    server: ThreadingHTTPServer
    thread: threading.Thread
    address: str


class _DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows SO_REUSEADDR allows unrelated processes to share one listener.
    # Shutdown closes the socket cleanly, so exclusive bind is the safer default.
    allow_reuse_address = False

    def handle_error(self, _request: Any, _client_address: Any) -> None:
        # socketserver's default handler prints the client address to stderr.
        return


@dataclass(frozen=True)
class _AcceptedCommand:
    canonical_json: str
    command_name: str
    response: tuple[tuple[str, Any], ...]
    completed: bool = False

    def response_payload(self) -> dict[str, Any]:
        return dict(self.response)


@dataclass
class _Session:
    token: str
    csrf: str
    transport: Transport
    scope: ControlScope
    authorization_epoch: int
    created_at: float
    active: bool = True
    idempotency: dict[str, _AcceptedCommand] = field(default_factory=dict)
    recent_commands: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=MAX_RECENT_COMMANDS)
    )


@dataclass(frozen=True)
class _SessionView:
    token: str = field(repr=False)
    csrf: str = field(repr=False)
    transport: Transport
    scope: ControlScope
    authorization_epoch: int


@dataclass(frozen=True)
class _SubmissionResult:
    kind: str
    response: dict[str, Any] | None = None


class _CommandBridge:
    """Holds the nonblocking App-owned queue callback without importing Tk."""

    def __init__(self, sink: Callable[[WebCommandEnvelope], bool] | None = None) -> None:
        self._lock = threading.Lock()
        self._sink = sink

    def set_sink(self, sink: Callable[[WebCommandEnvelope], bool] | None) -> None:
        with self._lock:
            self._sink = sink

    def enqueue(self, envelope: WebCommandEnvelope) -> bool:
        with self._lock:
            sink = self._sink
        if sink is None:
            return False
        try:
            return sink(envelope) is True
        except Exception:
            return False


class _SecurityState:
    """Process-local pairing, session, authorization, and replay state."""

    def __init__(self, *, monotonic=time.monotonic) -> None:
        self._allowed_hosts = {"127.0.0.1", "localhost"}
        self._failures: dict[str, list[float]] = {}
        self._sessions: dict[str, _Session] = {}
        self._authorization_epoch = 0
        self._lan_control_enabled = False
        self._lock = threading.RLock()
        self._monotonic = monotonic
        self._pairing_code = self._new_pairing_code()

    @staticmethod
    def _new_pairing_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        raw_code = "".join(secrets.choice(alphabet) for _ in range(8))
        return f"{raw_code[:4]}-{raw_code[4:]}"

    @property
    def pairing_code(self) -> str:
        with self._lock:
            return self._pairing_code

    @property
    def lan_control_enabled(self) -> bool:
        with self._lock:
            return self._lan_control_enabled

    @property
    def authorization_epoch(self) -> int:
        with self._lock:
            return self._authorization_epoch

    def _rotate_pairing_locked(self) -> None:
        previous = self._pairing_code
        candidate = self._new_pairing_code()
        while candidate == previous:
            candidate = self._new_pairing_code()
        self._pairing_code = candidate

    def add_host(self, host: str) -> None:
        with self._lock:
            self._allowed_hosts.add(host.lower())

    def remove_host(self, host: str) -> None:
        with self._lock:
            self._allowed_hosts.discard(host.lower())

    def host_allowed(self, host_header: str) -> bool:
        hostname = _host_from_header(host_header)
        if hostname is None:
            return False
        with self._lock:
            return hostname in self._allowed_hosts

    def _prune_sessions_locked(self, now: float) -> None:
        expired = [
            token
            for token, session in self._sessions.items()
            if now - session.created_at >= SESSION_MAX_AGE_SEC
        ]
        for token in expired:
            self._sessions.pop(token, None)

    def verify_pairing(
        self, client: str, candidate: str, transport: Transport
    ) -> tuple[str, str | None]:
        normalized = str(candidate or "").strip().upper().replace(" ", "").replace("-", "")
        now = float(self._monotonic())
        with self._lock:
            expected = self._pairing_code.replace("-", "")
            recent = [
                seen for seen in self._failures.get(client, []) if now - seen < PAIRING_WINDOW_SEC
            ]
            if len(recent) >= PAIRING_ATTEMPT_LIMIT:
                self._failures[client] = recent
                return "rate_limited", None
            if not _constant_time_text_equal(normalized, expected):
                recent.append(now)
                if len(self._failures) >= MAX_PAIRING_CLIENTS and client not in self._failures:
                    self._failures.pop(next(iter(self._failures)), None)
                self._failures[client] = recent
                return "invalid", None
            self._failures.pop(client, None)
            self._prune_sessions_locked(now)
            while len(self._sessions) >= MAX_SESSIONS:
                oldest = min(self._sessions.values(), key=lambda item: item.created_at)
                self._sessions.pop(oldest.token, None)
            token = secrets.token_urlsafe(32)
            while token in self._sessions:
                token = secrets.token_urlsafe(32)
            scope: ControlScope = (
                "control" if transport == "loopback" or self._lan_control_enabled else "view"
            )
            csrf = secrets.token_urlsafe(32)
            retained_csrf = {session.csrf for session in self._sessions.values()}
            while csrf in retained_csrf:
                csrf = secrets.token_urlsafe(32)
            self._sessions[token] = _Session(
                token=token,
                csrf=csrf,
                transport=transport,
                scope=scope,
                authorization_epoch=self._authorization_epoch,
                created_at=now,
            )
            return "ok", token

    def _token_from_cookie(self, cookie_header: str) -> str | None:
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return str(morsel.value) if morsel is not None and morsel.value else None

    def session_view(self, cookie_header: str) -> _SessionView | None:
        token = self._token_from_cookie(cookie_header)
        if token is None:
            return None
        now = float(self._monotonic())
        with self._lock:
            self._prune_sessions_locked(now)
            session = self._sessions.get(token)
            if session is None or not session.active:
                return None
            return _SessionView(
                token=session.token,
                csrf=session.csrf,
                transport=session.transport,
                scope=session.scope,
                authorization_epoch=session.authorization_epoch,
            )

    def csrf_valid(self, view: _SessionView, candidate: str) -> bool:
        if not candidate:
            return False
        with self._lock:
            session = self._sessions.get(view.token)
            return bool(
                session is not None
                and session.active
                and session.scope == "control"
                and _constant_time_text_equal(session.csrf, candidate)
            )

    def control_state_payload(
        self,
        view: _SessionView,
        projection: ControlStateProjection,
    ) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(view.token)
            if session is None or not session.active:
                return None
            return build_control_state_payload(
                projection,
                scope=session.scope,
                transport=session.transport,
                authorization_epoch=session.authorization_epoch,
                lan_control_enabled=self._lan_control_enabled,
                csrf=session.csrf if session.scope == "control" else None,
                recent_commands=tuple(session.recent_commands),
            )

    def submit_command(
        self,
        view: _SessionView,
        *,
        csrf: str,
        command_id: str,
        command: ValidatedWebCommand,
        submitted_revision: int,
        capability_available: bool,
        bridge: _CommandBridge,
    ) -> _SubmissionResult:
        canonical = command.canonical_json
        now = float(self._monotonic())
        with self._lock:
            self._prune_sessions_locked(now)
            session = self._sessions.get(view.token)
            if (
                session is None
                or not session.active
                or session.scope != "control"
                or session.authorization_epoch != view.authorization_epoch
                or session.transport != view.transport
                or not _constant_time_text_equal(session.csrf, csrf)
                or (session.transport == "lan" and not self._lan_control_enabled)
            ):
                return _SubmissionResult("authorization_revoked")
            retained = session.idempotency.get(command_id)
            if retained is not None:
                if not _constant_time_text_equal(retained.canonical_json, canonical):
                    return _SubmissionResult("idempotency_conflict")
                return _SubmissionResult("replay", retained.response_payload())
            if not capability_available:
                return _SubmissionResult("capability_unavailable")
            if len(session.idempotency) >= MAX_IDEMPOTENCY_KEYS:
                return _SubmissionResult("idempotency_capacity")
            envelope = WebCommandEnvelope(
                session_token=session.token,
                transport=session.transport,
                scope=session.scope,
                authorization_epoch=session.authorization_epoch,
                command_id=command_id,
                command=command,
                submitted_revision=submitted_revision,
            )
            if not bridge.enqueue(envelope):
                return _SubmissionResult("queue_unavailable")
            response = {
                "schema_version": 1,
                "command_id": command_id,
                "status": "queued",
                "submitted_revision": submitted_revision,
            }
            validate_command_response(response)
            session.idempotency[command_id] = _AcceptedCommand(
                canonical_json=canonical,
                command_name=command.name,
                response=tuple(response.items()),
            )
            return _SubmissionResult("accepted", response)

    def reauthorize_command(self, envelope: WebCommandEnvelope) -> bool:
        now = float(self._monotonic())
        with self._lock:
            self._prune_sessions_locked(now)
            session = self._sessions.get(envelope.session_token)
            return bool(
                session is not None
                and session.active
                and session.scope == "control"
                and envelope.scope == "control"
                and session.transport == envelope.transport
                and session.authorization_epoch == envelope.authorization_epoch
                and (
                    session.transport == "loopback"
                    or (session.transport == "lan" and self._lan_control_enabled)
                )
            )

    def publish_completion(
        self,
        envelope: WebCommandEnvelope,
        *,
        status: CompletionStatus,
        reason: CompletionReason,
        resulting_revision: int,
    ) -> bool:
        if status not in ("succeeded", "rejected"):
            return False
        if reason not in COMPLETION_REASONS:
            return False
        if (status == "succeeded") != (reason == "ok"):
            return False
        if resulting_revision <= envelope.submitted_revision:
            return False
        with self._lock:
            session = self._sessions.get(envelope.session_token)
            if session is None:
                return False
            retained = session.idempotency.get(envelope.command_id)
            if (
                retained is None
                or retained.completed
                or retained.command_name != envelope.command.name
                or not _constant_time_text_equal(
                    retained.canonical_json, envelope.command.canonical_json
                )
            ):
                return False
            completion = {
                "command_id": envelope.command_id,
                "command": envelope.command.name,
                "status": status,
                "reason": reason,
                "submitted_revision": envelope.submitted_revision,
                "resulting_revision": resulting_revision,
            }
            session.recent_commands.append(completion)
            session.idempotency[envelope.command_id] = replace(retained, completed=True)
            return True

    def enable_lan_control(self) -> bool:
        with self._lock:
            if self._lan_control_enabled:
                return False
            self._lan_control_enabled = True
            self._rotate_pairing_locked()
            return True

    def disable_lan_control(self) -> bool:
        with self._lock:
            if not self._lan_control_enabled:
                return False
            self._lan_control_enabled = False
            self._authorization_epoch += 1
            for session in self._sessions.values():
                if session.transport == "lan" and session.scope == "control":
                    session.active = False
                elif session.active:
                    session.authorization_epoch = self._authorization_epoch
            self._rotate_pairing_locked()
            return True

    def disable_lan_access(self) -> None:
        with self._lock:
            self._lan_control_enabled = False
            self._authorization_epoch += 1
            for session in self._sessions.values():
                if session.transport == "lan":
                    session.active = False
                elif session.active:
                    session.authorization_epoch = self._authorization_epoch
            self._rotate_pairing_locked()

    def invalidate_all(self) -> None:
        with self._lock:
            self._authorization_epoch += 1
            self._lan_control_enabled = False
            for session in self._sessions.values():
                session.active = False
            self._rotate_pairing_locked()


@dataclass(frozen=True)
class _RequestContext:
    snapshot_store: DashboardSnapshotStore
    control_store: DashboardControlStore
    security: _SecurityState
    bridge: _CommandBridge
    assets: dict[str, tuple[str, bytes]]


def _host_from_header(host_header: str) -> str | None:
    value = str(host_header or "").strip().lower()
    if not value or "/" in value or "@" in value:
        return None
    try:
        parsed = urlsplit(f"//{value}")
        if parsed.username or parsed.password:
            return None
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return None
        return parsed.hostname
    except ValueError:
        return None


def _origin_allowed(origin: str, host_header: str) -> bool:
    if not origin:
        return True
    expected = f"http://{host_header.strip()}"
    if origin != expected:
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return bool(
        parsed.scheme == "http"
        and parsed.netloc == host_header.strip()
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
    )


def _listener_transport(handler: BaseHTTPRequestHandler) -> Transport:
    address = str(handler.server.server_address[0])
    try:
        return "loopback" if ipaddress.ip_address(address).is_loopback else "lan"
    except ValueError:
        return "lan"


class _DuplicateJsonKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError


def _decode_single_json(body: bytes) -> Any:
    text = body.decode("utf-8", errors="strict")
    decoder = json.JSONDecoder(
        object_pairs_hook=_unique_object,
        parse_constant=_reject_json_constant,
    )
    start = len(text) - len(text.lstrip(" \t\r\n"))
    value, end = decoder.raw_decode(text, start)
    if text[end:].strip(" \t\r\n"):
        raise ValueError
    return value


def _make_handler(context: _RequestContext) -> type[BaseHTTPRequestHandler]:
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "BomanaWebCockpit"
        sys_version = ""

        def log_message(self, _format: str, *_args: Any) -> None:
            # Request URLs, IPs, pairing codes, and telemetry must never enter logs.
            return

        def _host_header(self) -> str | None:
            values = self.headers.get_all("Host", failobj=[])
            if len(values) != 1:
                return None
            value = str(values[0])
            return value if context.security.host_allowed(value) else None

        def do_GET(self) -> None:
            host_header = self._host_header()
            if host_header is None:
                self._send_text(HTTPStatus.MISDIRECTED_REQUEST, "invalid host")
                return
            origins = self.headers.get_all("Origin", failobj=[])
            if len(origins) > 1 or (origins and not _origin_allowed(str(origins[0]), host_header)):
                self._send_text(HTTPStatus.FORBIDDEN, "invalid origin")
                return

            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/":
                pair_values = parse_qs(parsed.query, keep_blank_values=True).get("pair", [])
                if pair_values:
                    self._handle_pairing(pair_values[-1])
                    return
                self._send_asset("index.html")
                return
            if path == "/healthz":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/api/v1/snapshot":
                if context.security.session_view(str(self.headers.get("Cookie") or "")) is None:
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "pairing_required"})
                    return
                published = context.snapshot_store.read()
                if published is None:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "snapshot_unavailable"}
                    )
                    return
                self._send_json(HTTPStatus.OK, build_dashboard_payload(published))
                return
            if path == "/api/v1/control-state":
                view = context.security.session_view(str(self.headers.get("Cookie") or ""))
                if view is None:
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "pairing_required"})
                    return
                projection = context.control_store.read()
                if projection is None:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": "control_state_unavailable"},
                    )
                    return
                payload = context.security.control_state_payload(view, projection)
                if payload is None:
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "pairing_required"})
                    return
                self._send_json(HTTPStatus.OK, payload)
                return
            if path == "/api/v1/map-image":
                if context.security.session_view(str(self.headers.get("Cookie") or "")) is None:
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "pairing_required"})
                    return
                image = context.snapshot_store.read_map_image()
                if image is None:
                    self._send_text(HTTPStatus.NOT_FOUND, "map image unavailable")
                    return
                self._send_bytes(HTTPStatus.OK, image.body, image.content_type)
                return
            if path == "/api/v1/map-icons-font":
                if context.security.session_view(str(self.headers.get("Cookie") or "")) is None:
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "pairing_required"})
                    return
                font = context.snapshot_store.read_map_icon_font()
                if font is None:
                    self._send_text(HTTPStatus.NOT_FOUND, "map icon font unavailable")
                    return
                self._send_bytes(HTTPStatus.OK, font.body, "font/ttf")
                return
            asset_name = {
                "/assets/dashboard.css": "dashboard.css",
                "/assets/dashboard.js": "dashboard.js",
                "/assets/qrcode.js": "qrcode.js",
                "/assets/app.png": "app.png",
                "/favicon.svg": "favicon.svg",
            }.get(path)
            if asset_name:
                self._send_asset(asset_name)
                return
            self._send_text(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/v1/commands":
                pass
            else:
                self._method_not_allowed()
                return
            host_header = self._host_header()
            if host_header is None:
                self._send_command_error(HTTPStatus.MISDIRECTED_REQUEST, "host_invalid")
                return
            view = context.security.session_view(str(self.headers.get("Cookie") or ""))
            if view is None:
                self._send_command_error(HTTPStatus.UNAUTHORIZED, "pairing_required")
                return
            if view.scope != "control":
                self._send_command_error(HTTPStatus.FORBIDDEN, "control_required")
                return

            origins = self.headers.get_all("Origin", failobj=[])
            if len(origins) != 1 or not str(origins[0]).strip() or str(origins[0]) == "null":
                self._send_command_error(HTTPStatus.FORBIDDEN, "origin_required")
                return
            if not _origin_allowed(str(origins[0]), host_header):
                self._send_command_error(HTTPStatus.FORBIDDEN, "origin_mismatch")
                return

            csrf_values = self.headers.get_all("X-Bomana-CSRF", failobj=[])
            if len(csrf_values) != 1 or not str(csrf_values[0]):
                self._send_command_error(HTTPStatus.FORBIDDEN, "csrf_required")
                return
            csrf = str(csrf_values[0])
            if not context.security.csrf_valid(view, csrf):
                self._send_command_error(HTTPStatus.FORBIDDEN, "csrf_invalid")
                return

            content_types = self.headers.get_all("Content-Type", failobj=[])
            if len(content_types) != 1 or str(content_types[0]).strip() != "application/json":
                self._discard_request_body()
                self._send_command_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "content_type_required")
                return
            if self.headers.get_all("Transfer-Encoding", failobj=[]):
                self.close_connection = True
                self._send_command_error(HTTPStatus.BAD_REQUEST, "chunked_not_allowed")
                return
            lengths = self.headers.get_all("Content-Length", failobj=[])
            if len(lengths) != 1 or not str(lengths[0]).isascii() or not str(lengths[0]).isdigit():
                self.close_connection = True
                self._send_command_error(HTTPStatus.LENGTH_REQUIRED, "content_length_required")
                return
            content_length = int(str(lengths[0]), 10)
            if content_length < 1:
                self.close_connection = True
                self._send_command_error(HTTPStatus.LENGTH_REQUIRED, "content_length_required")
                return
            if content_length > MAX_COMMAND_BODY_BYTES:
                self.close_connection = True
                self._send_command_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large")
                return
            body = self.rfile.read(content_length)
            if len(body) != content_length:
                self.close_connection = True
                self._send_command_error(HTTPStatus.BAD_REQUEST, "invalid_json")
                return
            try:
                decoded = _decode_single_json(body)
            except UnicodeError, ValueError, json.JSONDecodeError:
                self._send_command_error(HTTPStatus.BAD_REQUEST, "invalid_json")
                return
            try:
                command = validate_command_payload(decoded)
            except ControlValidationError:
                self._send_command_error(HTTPStatus.BAD_REQUEST, "schema_invalid")
                return

            key_values = self.headers.get_all("Idempotency-Key", failobj=[])
            if len(key_values) != 1 or not str(key_values[0]):
                self._send_command_error(HTTPStatus.BAD_REQUEST, "idempotency_required")
                return
            command_id = str(key_values[0])
            if _IDEMPOTENCY_KEY_RE.fullmatch(command_id) is None:
                self._send_command_error(HTTPStatus.BAD_REQUEST, "idempotency_invalid")
                return

            projection = context.control_store.read()
            capability_available = bool(
                projection is not None
                and command.name in projection.commands
                and (
                    command.name != "config.set_panel_visibility"
                    or command.target in projection.panel_targets
                )
            )
            submitted_revision = projection.revision if projection is not None else 0

            result = context.security.submit_command(
                view,
                csrf=csrf,
                command_id=command_id,
                command=command,
                submitted_revision=submitted_revision,
                capability_available=capability_available,
                bridge=context.bridge,
            )
            if result.kind in ("accepted", "replay") and result.response is not None:
                self._send_json(HTTPStatus.ACCEPTED, result.response)
            elif result.kind == "authorization_revoked":
                self._send_command_error(HTTPStatus.FORBIDDEN, "control_required")
            elif result.kind == "idempotency_conflict":
                self._send_command_error(
                    HTTPStatus.CONFLICT, "idempotency_conflict", command_id=command_id
                )
            elif result.kind == "idempotency_capacity":
                self._send_command_error(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "idempotency_capacity",
                    command_id=command_id,
                )
            elif result.kind == "capability_unavailable":
                self._send_command_error(
                    HTTPStatus.CONFLICT,
                    "capability_unavailable",
                    command_id=command_id,
                )
            else:
                self._send_command_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "queue_unavailable",
                    command_id=command_id,
                )

        def do_HEAD(self) -> None:
            self._method_not_allowed()

        def do_PUT(self) -> None:
            self._method_not_allowed()

        def do_PATCH(self) -> None:
            self._method_not_allowed()

        def do_DELETE(self) -> None:
            self._method_not_allowed()

        def do_OPTIONS(self) -> None:
            self._method_not_allowed()

        def _method_not_allowed(self) -> None:
            self._send_text(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "method not allowed",
                extra_headers=(("Allow", "GET"),),
            )

        def _handle_pairing(self, candidate: str) -> None:
            client = str(self.client_address[0] if self.client_address else "unknown")
            result, token = context.security.verify_pairing(
                client, candidate, _listener_transport(self)
            )
            if result == "rate_limited":
                self._send_text(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "too many attempts",
                    extra_headers=(("Retry-After", str(int(PAIRING_WINDOW_SEC))),),
                )
                return
            if result != "ok" or token is None:
                self._send_text(HTTPStatus.FORBIDDEN, "invalid pairing code")
                return
            cookie = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200"
            self._send_bytes(
                HTTPStatus.FOUND,
                b"",
                "text/plain; charset=utf-8",
                extra_headers=(("Location", "/"), ("Set-Cookie", cookie)),
            )

        def _discard_request_body(self) -> None:
            # Untrusted framing is not reused for another request on this connection.
            self.close_connection = True

        def _send_asset(self, name: str) -> None:
            asset = context.assets.get(name)
            if asset is None:
                self._send_text(HTTPStatus.NOT_FOUND, "not found")
                return
            content_type, body = asset
            self._send_bytes(HTTPStatus.OK, body, content_type)

        def _send_command_error(
            self,
            status: HTTPStatus,
            error: str,
            *,
            command_id: str | None = None,
        ) -> None:
            self.close_connection = True
            payload: dict[str, Any] = {
                "schema_version": 1,
                "status": "error",
                "error": error,
            }
            if command_id is not None:
                payload["command_id"] = command_id
            validate_command_response(payload)
            self._send_json(status, payload)

        def _send_json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
            body = json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8")

        def _send_text(
            self,
            status: HTTPStatus,
            text: str,
            *,
            extra_headers: tuple[tuple[str, str], ...] = (),
        ) -> None:
            self._send_bytes(
                status,
                str(text).encode("utf-8"),
                "text/plain; charset=utf-8",
                extra_headers=extra_headers,
            )

        def _send_bytes(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
            *,
            extra_headers: tuple[tuple[str, str], ...] = (),
        ) -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in _SECURITY_HEADERS:
                self.send_header(name, value)
            for name, value in extra_headers:
                self.send_header(name, value)
            self.end_headers()
            if body:
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(body)

    return DashboardRequestHandler


def _load_assets(asset_root: Path | None = None) -> dict[str, tuple[str, bytes]]:
    root = asset_root or Path(resource_path("bomana/assets/web"))
    definitions = {
        "index.html": (root / "index.html", "text/html; charset=utf-8"),
        "dashboard.css": (root / "dashboard.css", "text/css; charset=utf-8"),
        "dashboard.js": (root / "dashboard.js", "text/javascript; charset=utf-8"),
        "qrcode.js": (root / "qrcode.js", "text/javascript; charset=utf-8"),
        "favicon.svg": (root / "favicon.svg", "image/svg+xml"),
        "app.png": (root.parent / "branding" / "app.png", "image/png"),
    }
    assets: dict[str, tuple[str, bytes]] = {}
    for name, (path, content_type) in definitions.items():
        if not path.is_file():
            raise DashboardServerError(f"missing dashboard asset: {path}")
        assets[name] = (content_type, path.read_bytes())
    return assets


def discover_private_ipv4() -> list[str]:
    """Return RFC1918 addresses without probing the Internet or modifying routes."""

    found: set[str] = set()
    with contextlib.suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidate = str(info[4][0])
            with contextlib.suppress(ValueError):
                address = ipaddress.ip_address(candidate)
                if any(address in network for network in _RFC1918_NETWORKS):
                    found.add(candidate)

    def priority(value: str) -> tuple[int, str]:
        if value.startswith("192.168."):
            return (0, value)
        if value.startswith("10."):
            return (1, value)
        return (2, value)

    return sorted(found, key=priority)


def _is_rfc1918(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in _RFC1918_NETWORKS)


class WebDashboardRuntime:
    """Own loopback/LAN listeners and their process-local control authority."""

    def __init__(
        self,
        store: DashboardSnapshotStore,
        *,
        control_store: DashboardControlStore | None = None,
        command_sink: Callable[[WebCommandEnvelope], bool] | None = None,
        preferred_port: int = DEFAULT_PORT,
        port_search_count: int = PORT_SEARCH_COUNT,
        asset_root: Path | None = None,
        address_provider=discover_private_ipv4,
    ) -> None:
        self.store = store
        self.control_store = control_store or DashboardControlStore()
        self.preferred_port = int(preferred_port)
        self.port_search_count = max(1, int(port_search_count))
        self.address_provider = address_provider
        self.security = _SecurityState()
        self._bridge = _CommandBridge(command_sink)
        self.assets = _load_assets(asset_root)
        self._context = _RequestContext(
            snapshot_store=store,
            control_store=self.control_store,
            security=self.security,
            bridge=self._bridge,
            assets=self.assets,
        )
        self._handler = _make_handler(self._context)
        self._local: _Listener | None = None
        self._lan: dict[str, _Listener] = {}
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        return self._local is not None

    @property
    def lan_enabled(self) -> bool:
        return bool(self._lan)

    @property
    def lan_control_enabled(self) -> bool:
        return self.security.lan_control_enabled

    @property
    def authorization_epoch(self) -> int:
        return self.security.authorization_epoch

    @property
    def port(self) -> int | None:
        listener = self._local
        return int(listener.server.server_address[1]) if listener is not None else None

    @property
    def lan_address(self) -> str | None:
        return next(iter(self._lan), None)

    @property
    def lan_addresses(self) -> tuple[str, ...]:
        return tuple(self._lan)

    @property
    def pairing_code(self) -> str:
        return self.security.pairing_code

    @property
    def local_url(self) -> str | None:
        port = self.port
        return f"http://127.0.0.1:{port}/" if port is not None else None

    @property
    def local_pairing_url(self) -> str | None:
        url = self.local_url
        return f"{url}?pair={self.pairing_code}" if url else None

    @property
    def lan_url(self) -> str | None:
        address = self.lan_address
        if address is None:
            return None
        return f"http://{address}:{self._lan[address].server.server_address[1]}/"

    @property
    def lan_urls(self) -> tuple[str, ...]:
        return tuple(
            f"http://{address}:{listener.server.server_address[1]}/"
            for address, listener in self._lan.items()
        )

    @property
    def lan_pairing_url(self) -> str | None:
        url = self.lan_url
        return f"{url}?pair={self.pairing_code}" if url else None

    @property
    def lan_pairing_urls(self) -> tuple[str, ...]:
        return tuple(f"{url}?pair={self.pairing_code}" for url in self.lan_urls)

    def set_command_sink(self, sink: Callable[[WebCommandEnvelope], bool] | None) -> None:
        self._bridge.set_sink(sink)

    def publish_control_state(self, projection: ControlStateProjection) -> None:
        self.control_store.publish(projection)

    def reauthorize_command(self, envelope: WebCommandEnvelope) -> bool:
        return self.security.reauthorize_command(envelope)

    def publish_command_completion(
        self,
        envelope: WebCommandEnvelope,
        *,
        status: CompletionStatus,
        reason: CompletionReason,
        resulting_revision: int,
    ) -> bool:
        projection = self.control_store.read()
        if projection is None or projection.revision != resulting_revision:
            return False
        return self.security.publish_completion(
            envelope,
            status=status,
            reason=reason,
            resulting_revision=resulting_revision,
        )

    def start(self) -> None:
        with self._lock:
            if self._local is not None:
                return
            ports = (
                [0]
                if self.preferred_port == 0
                else range(self.preferred_port, self.preferred_port + self.port_search_count)
            )
            last_error: OSError | None = None
            for port in ports:
                try:
                    self._local = self._start_listener("127.0.0.1", int(port))
                    return
                except OSError as exc:
                    last_error = exc
            raise DashboardServerError(
                f"unable to bind loopback dashboard near port {self.preferred_port}: {last_error}"
            )

    def enable_lan(self) -> str:
        with self._lock:
            if self._local is None:
                self.start()
            if self._lan:
                self.security.enable_lan_control()
                if not self.security.lan_control_enabled:
                    self._disable_lan_locked()
                    raise DashboardServerError("unable to enable LAN control authority")
                return self.lan_address or ""
            port = self.port
            if port is None:
                raise DashboardServerError("loopback dashboard is not running")
            addresses = list(
                dict.fromkeys(
                    address for address in self.address_provider() if _is_rfc1918(address)
                )
            )
            if not addresses:
                raise DashboardServerError("no RFC1918 LAN address found")
            last_error: OSError | None = None
            for address in addresses:
                try:
                    listener = self._start_listener(address, port)
                except OSError as exc:
                    last_error = exc
                    continue
                self.security.add_host(address)
                self._lan[address] = listener
            if self._lan:
                try:
                    self.security.enable_lan_control()
                except Exception:
                    self._disable_lan_locked()
                    raise
                if not self.security.lan_control_enabled:
                    self._disable_lan_locked()
                    raise DashboardServerError("unable to enable LAN control authority")
                return self.lan_address or ""
            raise DashboardServerError(f"unable to bind a private LAN address: {last_error}")

    def _disable_lan_locked(self) -> None:
        listeners = tuple(self._lan.values())
        self._lan = {}
        self.security.disable_lan_access()
        for listener in listeners:
            self.security.remove_host(listener.address)
            self._stop_listener(listener)

    def disable_lan(self) -> None:
        with self._lock:
            self._disable_lan_locked()

    def stop(self) -> None:
        with self._lock:
            lan = tuple(self._lan.values())
            local = self._local
            self._lan = {}
            self._local = None
            self.security.invalidate_all()
            for listener in lan:
                self.security.remove_host(listener.address)
                self._stop_listener(listener)
            if local is not None:
                self._stop_listener(local)

    def _start_listener(self, address: str, port: int) -> _Listener:
        server = _DashboardHTTPServer((address, port), self._handler, bind_and_activate=True)
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name=f"BomanaWeb-{address}",
            daemon=True,
        )
        thread.start()
        return _Listener(server=server, thread=thread, address=address)

    @staticmethod
    def _stop_listener(listener: _Listener) -> None:
        listener.server.shutdown()
        listener.server.server_close()
        listener.thread.join(timeout=1.0)
