"""Wall-clock abstraction for deterministic core replay."""

from __future__ import annotations

import time
from typing import Protocol


class WallClock(Protocol):
    """Clock used for gameplay timestamps and state-machine deadlines."""

    def time(self) -> float: ...


class SystemClock:
    """Production wall clock."""

    @staticmethod
    def time() -> float:
        return time.time()
