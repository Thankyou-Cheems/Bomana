"""Runtime threading helpers for the Tk app."""

import contextlib
import threading
import time
import tkinter as tk
from collections.abc import Callable
from typing import Any

from bomana.config import NetworkConfig
from bomana.core.logic import GameLogic


class TkEventDispatcher:
    """Post callbacks back to the Tk main thread from runtime workers."""

    def __init__(self, root: tk.Tk):
        self.root = root

    def post(self, callback: Callable[..., Any], *args: Any) -> None:
        with contextlib.suppress(tk.TclError):
            self.root.after(0, callback, *args)


class LogicPoller:
    """Own the background GameLogic.tick loop."""

    def __init__(self, game: GameLogic, should_stop: Callable[[], bool]):
        self.game = game
        self.should_stop = should_stop
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = start_daemon_thread("BomanaLogicPoller", self._run)

    def _run(self) -> None:
        while not self.should_stop():
            loop_start = time.monotonic()
            try:
                self.game.tick()
            except Exception:
                time.sleep(NetworkConfig.BACKOFF_MAX)
                continue

            interval = (
                NetworkConfig.BACKOFF_MAX if self.game.is_api_down else NetworkConfig.POLL_INTERVAL
            )
            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.0, interval - elapsed))


def start_daemon_thread(name: str, target: Callable[[], Any]) -> threading.Thread:
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread
