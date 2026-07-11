"""Hardened standard-library HTTP runtime for the Bomana Web Cockpit."""

from __future__ import annotations

import contextlib
import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bomana.utils.file_utils import resource_path
from bomana.web.snapshot import DashboardSnapshotStore, build_dashboard_payload

DEFAULT_PORT = 8777
PORT_SEARCH_COUNT = 11
PAIRING_ATTEMPT_LIMIT = 8
PAIRING_WINDOW_SEC = 60.0
COOKIE_NAME = "bomana_session"

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


class DashboardServerError(RuntimeError):
    """Raised when a requested dashboard listener cannot be started."""


@dataclass
class _Listener:
    server: ThreadingHTTPServer
    thread: threading.Thread
    address: str


class _DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows SO_REUSEADDR allows two unrelated processes to share one listener,
    # which would make the pairing session nondeterministic. Shutdown closes the
    # socket cleanly, so exclusive bind semantics are the safer default.
    allow_reuse_address = False

    def handle_error(self, _request: Any, _client_address: Any) -> None:
        # socketserver's default handler prints the client address to stderr.
        # Dashboard request metadata is intentionally never logged.
        return


class _SecurityState:
    def __init__(self, *, monotonic=time.monotonic) -> None:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        raw_code = "".join(secrets.choice(alphabet) for _ in range(8))
        self.pairing_code = f"{raw_code[:4]}-{raw_code[4:]}"
        self.session_token = secrets.token_urlsafe(32)
        self._allowed_hosts = {"127.0.0.1", "localhost"}
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._monotonic = monotonic

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

    def verify_pairing(self, client: str, candidate: str) -> str:
        normalized = str(candidate or "").strip().upper().replace(" ", "")
        expected = self.pairing_code.replace("-", "")
        normalized = normalized.replace("-", "")
        now = float(self._monotonic())
        with self._lock:
            recent = [
                seen for seen in self._failures.get(client, []) if now - seen < PAIRING_WINDOW_SEC
            ]
            if len(recent) >= PAIRING_ATTEMPT_LIMIT:
                self._failures[client] = recent
                return "rate_limited"
            if hmac.compare_digest(normalized, expected):
                self._failures.pop(client, None)
                return "ok"
            recent.append(now)
            self._failures[client] = recent
            return "invalid"

    def session_valid(self, cookie_header: str) -> bool:
        if not cookie_header:
            return False
        cookie = SimpleCookie()
        with contextlib.suppress(Exception):
            cookie.load(cookie_header)
        morsel = cookie.get(COOKIE_NAME)
        return bool(
            morsel is not None and hmac.compare_digest(str(morsel.value), str(self.session_token))
        )


@dataclass(frozen=True)
class _RequestContext:
    store: DashboardSnapshotStore
    security: _SecurityState
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
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme == "http" and parsed.netloc.lower() == host_header.strip().lower()


def _make_handler(context: _RequestContext) -> type[BaseHTTPRequestHandler]:
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "BomanaWebCockpit"
        sys_version = ""

        def log_message(self, _format: str, *_args: Any) -> None:
            # Request URLs, IPs, pairing codes, and telemetry must never enter logs.
            return

        def do_GET(self) -> None:
            host_header = str(self.headers.get("Host") or "")
            if not context.security.host_allowed(host_header):
                self._send_text(HTTPStatus.MISDIRECTED_REQUEST, "invalid host")
                return
            if not _origin_allowed(str(self.headers.get("Origin") or ""), host_header):
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
                if not context.security.session_valid(str(self.headers.get("Cookie") or "")):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "pairing_required"})
                    return
                published = context.store.read()
                if published is None:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "snapshot_unavailable"}
                    )
                    return
                self._send_json(HTTPStatus.OK, build_dashboard_payload(published))
                return
            asset_name = {
                "/assets/dashboard.css": "dashboard.css",
                "/assets/dashboard.js": "dashboard.js",
                "/favicon.svg": "favicon.svg",
            }.get(path)
            if asset_name:
                self._send_asset(asset_name)
                return
            self._send_text(HTTPStatus.NOT_FOUND, "not found")

        def do_HEAD(self) -> None:
            self._method_not_allowed()

        def do_POST(self) -> None:
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
            result = context.security.verify_pairing(client, candidate)
            if result == "rate_limited":
                self._send_text(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "too many attempts",
                    extra_headers=(("Retry-After", str(int(PAIRING_WINDOW_SEC))),),
                )
                return
            if result != "ok":
                self._send_text(HTTPStatus.FORBIDDEN, "invalid pairing code")
                return
            cookie = (
                f"{COOKIE_NAME}={context.security.session_token}; Path=/; "
                "HttpOnly; SameSite=Strict; Max-Age=43200"
            )
            self._send_bytes(
                HTTPStatus.FOUND,
                b"",
                "text/plain; charset=utf-8",
                extra_headers=(("Location", "/"), ("Set-Cookie", cookie)),
            )

        def _send_asset(self, name: str) -> None:
            asset = context.assets.get(name)
            if asset is None:
                self._send_text(HTTPStatus.NOT_FOUND, "not found")
                return
            content_type, body = asset
            self._send_bytes(HTTPStatus.OK, body, content_type)

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(
                payload,
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
        "index.html": "text/html; charset=utf-8",
        "dashboard.css": "text/css; charset=utf-8",
        "dashboard.js": "text/javascript; charset=utf-8",
        "favicon.svg": "image/svg+xml",
    }
    assets: dict[str, tuple[str, bytes]] = {}
    for name, content_type in definitions.items():
        path = root / name
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
    """Own loopback and optional current-run LAN listeners."""

    def __init__(
        self,
        store: DashboardSnapshotStore,
        *,
        preferred_port: int = DEFAULT_PORT,
        port_search_count: int = PORT_SEARCH_COUNT,
        asset_root: Path | None = None,
        address_provider=discover_private_ipv4,
    ) -> None:
        self.store = store
        self.preferred_port = int(preferred_port)
        self.port_search_count = max(1, int(port_search_count))
        self.address_provider = address_provider
        self.security = _SecurityState()
        self.assets = _load_assets(asset_root)
        self._context = _RequestContext(store=store, security=self.security, assets=self.assets)
        self._handler = _make_handler(self._context)
        self._local: _Listener | None = None
        self._lan: _Listener | None = None
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        return self._local is not None

    @property
    def lan_enabled(self) -> bool:
        return self._lan is not None

    @property
    def port(self) -> int | None:
        listener = self._local
        return int(listener.server.server_address[1]) if listener is not None else None

    @property
    def lan_address(self) -> str | None:
        return self._lan.address if self._lan is not None else None

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
        if self._lan is None:
            return None
        return f"http://{self._lan.address}:{self._lan.server.server_address[1]}/"

    @property
    def lan_pairing_url(self) -> str | None:
        url = self.lan_url
        return f"{url}?pair={self.pairing_code}" if url else None

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
            if self._lan is not None:
                return self._lan.address
            port = self.port
            if port is None:
                raise DashboardServerError("loopback dashboard is not running")
            addresses = [address for address in self.address_provider() if _is_rfc1918(address)]
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
                self._lan = listener
                return address
            raise DashboardServerError(f"unable to bind a private LAN address: {last_error}")

    def disable_lan(self) -> None:
        with self._lock:
            listener = self._lan
            self._lan = None
            if listener is None:
                return
            self.security.remove_host(listener.address)
            self._stop_listener(listener)

    def stop(self) -> None:
        with self._lock:
            lan = self._lan
            local = self._local
            self._lan = None
            self._local = None
            if lan is not None:
                self.security.remove_host(lan.address)
                self._stop_listener(lan)
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
