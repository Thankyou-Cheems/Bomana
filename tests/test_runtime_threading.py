import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from bomana.core.telemetry import MapIconFontFetchResult, MapImageFetchResult
from bomana.ui.runtime import LogicPoller, MapIconFontPoller, MapImagePoller, TkEventDispatcher
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


class FakeMapIconFontFetcher:
    def __init__(self) -> None:
        self.fetched = threading.Event()
        self.closed = False

    def fetch(self) -> MapIconFontFetchResult:
        self.fetched.set()
        return MapIconFontFetchResult(ok=True, body=b"\x00\x01\x00\x00official")

    def close(self) -> None:
        self.closed = True


class RetryMapIconFontFetcher(FakeMapIconFontFetcher):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def fetch(self) -> MapIconFontFetchResult:
        self.calls += 1
        if self.calls == 1:
            return MapIconFontFetchResult(ok=False, error_kind="status")
        return super().fetch()


class BlockingMapIconFontFetcher(FakeMapIconFontFetcher):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def fetch(self) -> MapIconFontFetchResult:
        self.started.set()
        self.release.wait(5.0)
        self.finished.set()
        return MapIconFontFetchResult(ok=True, body=b"\x00\x01\x00\x00old")


class FailingMapIconFontFetcher(FakeMapIconFontFetcher):
    def fetch(self) -> MapIconFontFetchResult:
        self.fetched.set()
        return MapIconFontFetchResult(ok=False, error_kind="status")


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

    def test_map_icon_font_poller_fetches_once_off_tk_and_stops_bounded(self) -> None:
        store = DashboardSnapshotStore()
        fetcher = FakeMapIconFontFetcher()
        poller = MapIconFontPoller(store, fetcher_factory=lambda: fetcher)

        poller.start()
        self.assertTrue(fetcher.fetched.wait(1.0))
        poller.stop()

        font = store.read_map_icon_font()
        self.assertIsNotNone(font)
        self.assertEqual(font.body, b"\x00\x01\x00\x00official")
        self.assertTrue(fetcher.closed)
        self.assertIsNone(poller._thread)

    def test_map_icon_font_poller_retries_until_first_valid_font(self) -> None:
        store = DashboardSnapshotStore()
        fetcher = RetryMapIconFontFetcher()
        poller = MapIconFontPoller(
            store,
            fetcher_factory=lambda: fetcher,
            interval_sec=0.1,
        )

        poller.start()
        self.assertTrue(fetcher.fetched.wait(1.0))
        poller.stop()

        self.assertEqual(fetcher.calls, 2)
        self.assertIsNotNone(store.read_map_icon_font())

    def test_stopped_font_generation_cannot_publish_into_restarted_poller(self) -> None:
        store = DashboardSnapshotStore()
        old_fetcher = BlockingMapIconFontFetcher()
        new_fetcher = FailingMapIconFontFetcher()
        fetchers = iter((old_fetcher, new_fetcher))
        poller = MapIconFontPoller(
            store,
            fetcher_factory=lambda: next(fetchers),
            interval_sec=60.0,
        )

        poller.start()
        self.assertTrue(old_fetcher.started.wait(1.0))
        poller.stop()
        poller.start()
        self.assertTrue(new_fetcher.fetched.wait(1.0))
        old_fetcher.release.set()
        self.assertTrue(old_fetcher.finished.wait(1.0))
        poller.stop()

        self.assertIsNone(store.read_map_icon_font())


if __name__ == "__main__":
    unittest.main()
