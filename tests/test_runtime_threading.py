import tkinter as tk
import unittest
from unittest.mock import patch

from bomana.ui.runtime import LogicPoller, TkEventDispatcher


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


class RuntimeThreadingTests(unittest.TestCase):
    def test_dispatcher_posts_callback_to_tk_after(self) -> None:
        root = FakeRoot()
        dispatcher = TkEventDispatcher(root)
        callback = object()

        dispatcher.post(callback, "value")

        self.assertEqual(root.calls, [(0, callback, ("value",))])

    def test_dispatcher_ignores_destroyed_root(self) -> None:
        class ClosedRoot:
            def after(self, delay_ms, callback, *args):
                raise tk.TclError("closed")

        TkEventDispatcher(ClosedRoot()).post(lambda: None)

    def test_logic_poller_ticks_until_stop_callback(self) -> None:
        game = FakeGame()
        poller = LogicPoller(game, lambda: game.ticks >= 1)

        with patch("bomana.ui.runtime.time.sleep"):
            poller._run()

        self.assertEqual(game.ticks, 1)


if __name__ == "__main__":
    unittest.main()
