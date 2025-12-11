"""
In-memory master state flags.
"""

from __future__ import annotations

import threading


class MasterState:
    def __init__(self):
        self._lock = threading.Lock()
        self._paused = False

    def set_paused(self, paused: bool):
        with self._lock:
            self._paused = paused

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused


state = MasterState()
