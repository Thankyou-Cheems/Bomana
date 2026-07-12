"""Runtime threading helpers for the Tk app."""

import contextlib
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from typing import Any

from bomana.config.settings import NetworkConfig
from bomana.core.logic import GameLogic
from bomana.core.telemetry import MapIconFontFetcher, MapImageFetcher
from bomana.utils.diagnostics import log_exception
from bomana.web.snapshot import DashboardSnapshotStore

_LOGIC_POLLER_EXCEPTION_LOG_INTERVAL_SEC = 60.0
# Terrain thumbnail only; marker positions still ride the high-rate snapshot path.
MAP_IMAGE_POLL_INTERVAL_SEC = 2.0


class TkEventDispatcher:
    """Queue callbacks for execution on the Tk main thread."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self._pending: queue.SimpleQueue[tuple[Callable[..., Any], tuple[Any, ...]]] = (
            queue.SimpleQueue()
        )
        self._after_id: str | None = None
        self._poll_interval_ms = 25
        self._polling = True
        self._schedule()

    def post(self, callback: Callable[..., Any], *args: Any) -> None:
        self._pending.put((callback, args))

    def _schedule(self) -> None:
        if not self._polling or self._after_id is not None:
            return
        with contextlib.suppress(tk.TclError, RuntimeError):
            self._after_id = self.root.after(self._poll_interval_ms, self._drain)

    def _drain(self) -> None:
        self._after_id = None
        try:
            while True:
                callback, args = self._pending.get_nowait()
                try:
                    callback(*args)
                except Exception as exc:
                    log_exception("tk_dispatcher_callback_failed", exc)
        except queue.Empty:
            pass
        finally:
            self._schedule()


class LogicPoller:
    """Own the background GameLogic.tick loop."""

    def __init__(self, game: GameLogic, should_stop: Callable[[], bool]):
        self.game = game
        self.should_stop = should_stop
        self._thread: threading.Thread | None = None
        self._last_exception_log_at: float | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = start_daemon_thread("BomanaLogicPoller", self._run)

    def _run(self) -> None:
        while not self.should_stop():
            loop_start = time.monotonic()
            try:
                self.game.tick()
            except Exception as exc:
                self._log_tick_exception(exc, loop_start)
                time.sleep(NetworkConfig.BACKOFF_MAX)
                continue

            interval = (
                NetworkConfig.BACKOFF_MAX if self.game.is_api_down else NetworkConfig.POLL_INTERVAL
            )
            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.0, interval - elapsed))

    def _log_tick_exception(self, exc: Exception, now: float) -> None:
        if (
            self._last_exception_log_at is not None
            and now - self._last_exception_log_at < _LOGIC_POLLER_EXCEPTION_LOG_INTERVAL_SEC
        ):
            return
        self._last_exception_log_at = now
        log_exception(
            "logic_poller_tick_failed",
            exc,
            backoff_sec=NetworkConfig.BACKOFF_MAX,
        )


class MapImagePoller:
    """Low-cadence non-Tk worker for the official tactical-map image."""

    def __init__(
        self,
        store: DashboardSnapshotStore,
        *,
        fetcher_factory=MapImageFetcher,
        interval_sec: float = MAP_IMAGE_POLL_INTERVAL_SEC,
    ) -> None:
        self.store = store
        self.fetcher_factory = fetcher_factory
        self.interval_sec = max(0.1, float(interval_sec))
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._fetcher: MapImageFetcher | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event = threading.Event()
        self._fetcher = self.fetcher_factory()
        self._thread = start_daemon_thread("BomanaMapImagePoller", self._run)

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.25)
        self._thread = None
        fetcher = self._fetcher
        self._fetcher = None
        if fetcher is not None:
            fetcher.close()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            fetcher = self._fetcher
            if fetcher is None:
                return
            result = fetcher.fetch()
            if result.ok:
                self.store.publish_map_image(result.body, result.content_type)
            if self._stop_event.wait(self.interval_sec):
                return


class MapIconFontPoller:
    """Low-cadence non-Tk worker that stops after the first valid official font."""

    def __init__(
        self,
        store: DashboardSnapshotStore,
        *,
        fetcher_factory=MapIconFontFetcher,
        interval_sec: float = MAP_IMAGE_POLL_INTERVAL_SEC,
    ):
        self.store = store
        self.fetcher_factory = fetcher_factory
        self.interval_sec = max(0.1, float(interval_sec))
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._fetcher: MapIconFontFetcher | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self.store.read_map_icon_font() is not None:
            return
        stop_event = threading.Event()
        fetcher = self.fetcher_factory()
        self._stop_event = stop_event
        self._fetcher = fetcher
        self._thread = start_daemon_thread(
            "BomanaMapIconFontPoller",
            lambda: self._run(stop_event, fetcher),
        )

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.25)
        self._thread = None
        fetcher = self._fetcher
        self._fetcher = None
        if fetcher is not None:
            fetcher.close()

    def _run(self, stop_event: threading.Event, fetcher: MapIconFontFetcher) -> None:
        while not stop_event.is_set():
            result = fetcher.fetch()
            if result.ok and not stop_event.is_set():
                self.store.publish_map_icon_font(result.body)
                return
            if stop_event.wait(self.interval_sec):
                return


def start_daemon_thread(name: str, target: Callable[[], Any]) -> threading.Thread:
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread
