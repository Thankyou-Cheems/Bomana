# -*- coding: utf-8 -*-
"""WinUI bridge: expose GameLogic snapshots through local HTTP."""

import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from bomana.config import NetworkConfig, __version__
from bomana.core.logic import GameLogic
from bomana.core.state import UISnapshot


def _fmt_time(sec: Optional[float]) -> str:
    """Format seconds to MM:SS for frontend convenience."""
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


def _badge_to_dict(badge: Tuple[str, str, str]) -> Dict[str, str]:
    """Convert (text, fg, bg) badge tuple into JSON object."""
    text, fg, bg = badge
    return {"text": text, "fg": fg, "bg": bg}


def _zone_to_dict(zone: Any) -> Dict[str, Any]:
    """Serialize ZoneDisplayInfo."""
    return {
        "id": zone.id,
        "distance_km": float(zone.distance_km),
        "direction": zone.direction,
        "relative": float(zone.relative),
        "is_target": bool(zone.is_target),
        "ete_str": zone.ete_str,
        "cdi_indicator": zone.cdi_indicator,
        "cdi_color": zone.cdi_color,
    }


def _airfield_to_dict(airfield: Optional[Any]) -> Optional[Dict[str, Any]]:
    """Serialize AirfieldDisplayInfo."""
    if not airfield:
        return None
    return {
        "id": airfield.id,
        "side": airfield.side,
        "distance_km": float(airfield.distance_km),
        "direction": airfield.direction,
        "relative": float(airfield.relative),
        "is_target": bool(airfield.is_target),
        "ete_str": airfield.ete_str,
        "cdi_indicator": airfield.cdi_indicator,
        "cdi_color": airfield.cdi_color,
    }


class _BridgeHttpServer(ThreadingHTTPServer):
    """Threading HTTP server carrying a bridge reference."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: Tuple[str, int],
        request_handler_class,
        bridge: "WinUISnapshotBridge",
    ):
        self.bridge = bridge
        super().__init__(server_address, request_handler_class)


class _BridgeHandler(BaseHTTPRequestHandler):
    """HTTP handlers for WinUI snapshot bridge."""

    server: _BridgeHttpServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, self.server.bridge.get_health_payload())
            return
        if parsed.path == "/snapshot":
            self._send_json(200, self.server.bridge.get_snapshot_payload())
            return
        self._send_json(
            404,
            {
                "ok": False,
                "error": "not_found",
                "path": parsed.path,
            },
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Keep bridge quiet; polling is frequent.
        return

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class WinUISnapshotBridge:
    """Run GameLogic in background and publish snapshots for WinUI frontend."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = int(port)
        self._started_monotonic = 0.0
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._httpd: Optional[_BridgeHttpServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._last_error = ""
        self._last_snapshot_at = 0.0
        self._payload: Dict[str, Any] = self._empty_payload()
        self.game = GameLogic()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        """Start HTTP server thread and polling thread."""
        if self._httpd is not None:
            return

        self._stop_event.clear()
        self._started_monotonic = time.monotonic()

        self._httpd = _BridgeHttpServer((self.host, self.port), _BridgeHandler, self)
        addr_host, addr_port = self._httpd.server_address
        self.host = str(addr_host)
        self.port = int(addr_port)

        self._http_thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="WinUIBridgeHTTP",
            daemon=True,
        )
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="WinUIBridgePoll",
            daemon=True,
        )
        self._http_thread.start()
        self._poll_thread.start()

    def stop(self) -> None:
        """Stop all bridge threads and persist timer state."""
        self._stop_event.set()

        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None

        if self._http_thread and self._http_thread.is_alive():
            self._http_thread.join(timeout=2.0)
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2.0)

        self._http_thread = None
        self._poll_thread = None

        try:
            self.game.save_timer_state()
        except Exception:
            pass

    def get_health_payload(self) -> Dict[str, Any]:
        """Return bridge health details."""
        with self._lock:
            return {
                "ok": True,
                "service": "bomana-winui-bridge",
                "version": __version__,
                "schema_version": int(self._payload.get("schema_version", 1)),
                "uptime_sec": max(0.0, round(time.monotonic() - self._started_monotonic, 3)),
                "last_snapshot_at": float(self._last_snapshot_at),
                "api_down": bool(self._payload.get("api_down", False)),
                "last_error": self._last_error,
            }

    def get_snapshot_payload(self) -> Dict[str, Any]:
        """Return latest snapshot payload for frontend polling."""
        with self._lock:
            return copy.deepcopy(self._payload)

    def _poll_loop(self) -> None:
        """Background polling loop mirroring Tk app cadence."""
        while not self._stop_event.is_set():
            tick_started = time.time()
            try:
                self.game.tick()
                snap = self.game.snapshot()
                payload = self._snapshot_to_payload(snap, tick_started)
                with self._lock:
                    self._payload = payload
                    self._last_snapshot_at = tick_started
                    self._last_error = ""
            except Exception as e:
                with self._lock:
                    self._last_error = str(e)

            interval = (
                NetworkConfig.BACKOFF_MAX
                if self.game.is_api_down
                else NetworkConfig.POLL_INTERVAL
            )
            wait_sec = max(0.02, float(interval))
            self._stop_event.wait(wait_sec)

    def _snapshot_to_payload(self, snap: UISnapshot, now: float) -> Dict[str, Any]:
        """Flatten UISnapshot into WinUI-friendly JSON."""
        zones = [_zone_to_dict(z) for z in snap.zones]
        enemies = [_airfield_to_dict(a) for a in snap.enemy_airfields]
        target_zone = next((z for z in zones if z.get("is_target")), None)

        return {
            "ok": True,
            "schema_version": 1,
            "version": __version__,
            "ts": float(now),
            "phase": snap.phase.name,
            "sortie_id": int(snap.sortie_id),
            "life_index": snap.life_index,
            "cycle": snap.cycle,
            "remaining_sec": snap.remaining_sec,
            "remaining_text": _fmt_time(snap.remaining_sec),
            "progress": float(snap.progress),
            "status_text": snap.status_text,
            "main_badge": _badge_to_dict(snap.main_badge),
            "flight_badge": _badge_to_dict(snap.flight_badge),
            "api_down": bool(snap.api_down),
            "api_down_pending": bool(snap.api_down_pending),
            "on_ground": bool(snap.on_ground),
            "landed_flash": bool(snap.landed_flash),
            "player_heading": float(snap.player_heading),
            "zones": zones,
            "target_zone": target_zone,
            "friendly_airfield": _airfield_to_dict(snap.friendly_airfield),
            "enemy_airfields": [x for x in enemies if x is not None],
            "has_target": bool(snap.has_target),
            "has_airfield_target": bool(snap.has_airfield_target),
            "fuel_kg": float(snap.fuel_kg),
            "fuel_percent": float(snap.fuel_percent),
            "fuel_time_remaining_str": snap.fuel_time_remaining_str,
            "attitude_pitch_deg": float(snap.attitude_pitch_deg),
            "attitude_roll_deg": float(snap.attitude_roll_deg),
            "attitude_reliable": bool(snap.attitude_reliable),
            "hud_attitude_fallback": bool(snap.hud_attitude_fallback),
            "hud_attitude_fallback_reason": snap.hud_attitude_fallback_reason,
            "diag_text": snap.diag_text,
        }

    @staticmethod
    def _empty_payload() -> Dict[str, Any]:
        """Return initial payload before first polling tick."""
        return {
            "ok": True,
            "schema_version": 1,
            "version": __version__,
            "ts": 0.0,
            "phase": "IDLE",
            "sortie_id": -1,
            "life_index": None,
            "cycle": None,
            "remaining_sec": None,
            "remaining_text": "--:--",
            "progress": 0.0,
            "status_text": "初始化中",
            "main_badge": {"text": "IDLE", "fg": "", "bg": ""},
            "flight_badge": {"text": "—", "fg": "", "bg": ""},
            "api_down": True,
            "api_down_pending": False,
            "on_ground": False,
            "landed_flash": False,
            "player_heading": 0.0,
            "zones": [],
            "target_zone": None,
            "friendly_airfield": None,
            "enemy_airfields": [],
            "has_target": False,
            "has_airfield_target": False,
            "fuel_kg": 0.0,
            "fuel_percent": 0.0,
            "fuel_time_remaining_str": "",
            "attitude_pitch_deg": 0.0,
            "attitude_roll_deg": 0.0,
            "attitude_reliable": False,
            "hud_attitude_fallback": True,
            "hud_attitude_fallback_reason": "missing",
            "diag_text": "",
        }
