import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from bomana.core.telemetry import MapImageFetchResult
from bomana.ui.runtime import LogicPoller, MapImagePoller, TkEventDispatcher
from bomana.web.snapshot import DashboardSnapshotStore


class FakeRoot:
    def __init__(self) -> None:
        self.calls = []

    def after(self, delay_ms, callback, *args):
        self.calls.append((delay_ms, callback, args))
        return "after-id"


class FakeGame:
    def __init__(self) -> None:
        self.is_api_down = False
        self.ticks = 0

    def tick(self) -> None:
        self.ticks += 1


class ExplodingGame(FakeGame):
    def tick(self) -> None:
        self.ticks += 1
        raise RuntimeError("tick failed")


class FakeMapImageFetcher:
    def __init__(self) -> None:
        self.fetched = threading.Event()
        self.closed = False

    def fetch(self) -> MapImageFetchResult:
        self.fetched.set()
        return MapImageFetchResult(
            ok=True,
            body=b"\x89PNG\r\n\x1a\nmap",
            content_type="image/png",
        )

    def close(self) -> None:
        self.closed = True


class RuntimeThreadingTests(unittest.TestCase):
    def test_dispatcher_posts_callback_to_tk_poller_queue(self) -> None:
        root = FakeRoot()
        dispatcher = TkEventDispatcher(root)
        called: list[str] = []

        dispatcher.post(lambda value: called.append(value), "value")

        self.assertEqual(len(root.calls), 1)
        self.assertEqual(root.calls[0][0], 25)
        self.assertEqual(called, [])

        _delay_ms, drain, args = root.calls.pop(0)
        drain(*args)

        self.assertEqual(called, ["value"])
        self.assertEqual(len(root.calls), 1)

    def test_dispatcher_ignores_destroyed_root(self) -> None:
        class ClosedRoot:
            def after(self, delay_ms, callback, *args):
                raise tk.TclError("closed")

        TkEventDispatcher(ClosedRoot()).post(lambda: None)

    def test_dispatcher_ignores_shutdown_runtime_error(self) -> None:
        class ClosedRoot:
            def after(self, delay_ms, callback, *args):
                raise RuntimeError("main thread is not in main loop")

        TkEventDispatcher(ClosedRoot()).post(lambda: None)

    def test_logic_poller_ticks_until_stop_callback(self) -> None:
        game = FakeGame()
        poller = LogicPoller(game, lambda: game.ticks >= 1)

        with patch("bomana.ui.runtime.time.sleep"):
            poller._run()

        self.assertEqual(game.ticks, 1)

    def test_logic_poller_logs_tick_exception_once_until_throttle_elapsed(self) -> None:
        game = ExplodingGame()
        poller = LogicPoller(game, lambda: game.ticks >= 3)

        with (
            patch("bomana.ui.runtime.log_exception") as log_exception,
            patch("bomana.ui.runtime.time.monotonic", return_value=100.0),
            patch("bomana.ui.runtime.time.sleep"),
        ):
            poller._run()

        self.assertEqual(game.ticks, 3)
        self.assertEqual(log_exception.call_count, 1)
        self.assertEqual(log_exception.call_args.args[0], "logic_poller_tick_failed")

    def test_logic_poller_logs_tick_exception_after_throttle_elapsed(self) -> None:
        game = ExplodingGame()
        poller = LogicPoller(game, lambda: game.ticks >= 2)

        with (
            patch("bomana.ui.runtime.log_exception") as log_exception,
            patch("bomana.ui.runtime.time.monotonic", side_effect=[100.0, 161.0]),
            patch("bomana.ui.runtime.time.sleep"),
        ):
            poller._run()

        self.assertEqual(game.ticks, 2)
        self.assertEqual(log_exception.call_count, 2)

    def test_map_image_poller_publishes_off_tk_and_stops_bounded(self) -> None:
        store = DashboardSnapshotStore()
        fetcher = FakeMapImageFetcher()
        poller = MapImagePoller(store, fetcher_factory=lambda: fetcher, interval_sec=60.0)

        poller.start()
        self.assertTrue(fetcher.fetched.wait(1.0))
        poller.stop()

        image = store.read_map_image()
        self.assertIsNotNone(image)
        self.assertEqual(image.body, b"\x89PNG\r\n\x1a\nmap")
        self.assertTrue(fetcher.closed)
        self.assertIsNone(poller._thread)


if __name__ == "__main__":
    unittest.main()
