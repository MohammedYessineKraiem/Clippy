from __future__ import annotations

import logging
from collections.abc import Callable

from pynput import keyboard

LOGGER = logging.getLogger(__name__)


class HotkeyService:
    def __init__(self, hotkey: str, callback: Callable[[], None]) -> None:
        self.hotkey = hotkey
        self.callback = callback
        self._listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> None:
        self.stop()
        try:
            self._listener = keyboard.GlobalHotKeys({self.hotkey: self.callback})
            self._listener.start()
        except (ValueError, OSError):
            LOGGER.exception("Could not register global hotkey %s", self.hotkey)
            raise

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    def rebind(self, hotkey: str) -> None:
        old = self.hotkey
        self.hotkey = hotkey
        try:
            self.start()
        except Exception:
            self.hotkey = old
            self.start()
            raise
