from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import pyperclip

from .classification import Classifier
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class CaptureService:
    def __init__(
        self,
        storage: Storage,
        classifier: Classifier,
        on_capture: Callable[[], None] | None = None,
        poll_seconds: float = 0.35,
    ) -> None:
        self.storage = storage
        self.classifier = classifier
        self.on_capture = on_capture
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_observed: str | None = None
        self._suppressed: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        try:
            initial = pyperclip.paste()
            self._last_observed = initial if isinstance(initial, str) else None
        except pyperclip.PyperclipException:
            self._last_observed = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="clipboard-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def suppress_next(self, text: str) -> None:
        self._suppressed = text

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                value = pyperclip.paste()
                if not isinstance(value, str) or not value or value == self._last_observed:
                    continue
                self._last_observed = value
                if value == self._suppressed:
                    self._suppressed = None
                    continue
                classification, embedding = self.classifier.classify(
                    value, self.storage.list_sections()
                )
                if self.storage.add_entry(value, classification, embedding) and self.on_capture:
                    self.on_capture()
            except Exception:
                LOGGER.exception("Clipboard capture failed")
