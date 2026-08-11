from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from .audio import AudioService
from .capture import CaptureService
from .classification import Classifier
from .config import SettingsStore, app_data_dir, bundled_logo_path, bundled_model_dir
from .embeddings import LocalSentenceEmbedder, UnavailableEmbedder
from .hotkey import HotkeyService
from .search import SearchService
from .security import VaultManager
from .storage import Storage
from .ui.dialogs import ConfigDialog
from .ui.popup import PopupWindow
from .ui.theme import APP_STYLE

LOGGER = logging.getLogger(__name__)


class EventBridge(QObject):
    hotkey_pressed = Signal()
    captured = Signal()


class ClippyRuntime:
    def __init__(self, application: QApplication) -> None:
        self.application = application
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.vault = VaultManager(self.settings.vault_auto_lock_seconds)
        self.storage = Storage(vault=self.vault)
        self.embedder, self.model_warning = self._load_embedder()
        self.classifier = Classifier(self.embedder)
        self.search = SearchService(self.storage, self.embedder)
        self.audio = AudioService(self.settings.sounds_enabled, self.settings.sound_volume)
        self.bridge = EventBridge()
        self.capture = CaptureService(
            self.storage, self.classifier, on_capture=self.bridge.captured.emit
        )
        self.popup = PopupWindow(
            self.storage,
            self.search,
            self.capture,
            self.audio,
            self.settings,
            self._make_config,
        )
        self.hotkey = HotkeyService(self.settings.hotkey, self.bridge.hotkey_pressed.emit)
        self.bridge.hotkey_pressed.connect(self.popup.show_popup)
        self.bridge.captured.connect(lambda: self.audio.play("capture"))
        self.expiry_timer = QTimer()
        self.expiry_timer.setInterval(60_000)
        self.expiry_timer.timeout.connect(self._sweep_expired)
        self.vault_timer = QTimer()
        self.vault_timer.setInterval(1_000)
        self._vault_was_unlocked = self.vault.is_unlocked
        self.vault_timer.timeout.connect(self._watch_vault_lock)

    def start(self) -> None:
        try:
            self.hotkey.start()
        except Exception as exc:
            QMessageBox.critical(
                None, "Clippy hotkey", f"Could not register {self.settings.hotkey}:\n{exc}"
            )
            raise
        self.capture.start()
        self.expiry_timer.start()
        self.vault_timer.start()
        self._sweep_expired()
        if self.model_warning:
            QTimer.singleShot(
                0, lambda: QMessageBox.warning(None, "Local model unavailable", self.model_warning)
            )

    def stop(self) -> None:
        self.hotkey.stop()
        self.capture.stop()
        self.vault.lock()
        self.storage.close()

    def _load_embedder(self):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        model_path = bundled_model_dir()
        try:
            return LocalSentenceEmbedder(model_path), None
        except Exception as exc:
            LOGGER.warning("Semantic model unavailable: %s", exc)
            warning = (
                f"The bundled local model was not found at:\n{model_path}\n\n"
                "Clippy will capture and rule-classify text, but semantic "
                "classification and ranking are unavailable in this development "
                "checkout. The packaged release must include the model."
            )
            return UnavailableEmbedder(), warning

    def _make_config(self, parent: QWidget) -> ConfigDialog:
        dialog = ConfigDialog(
            self.storage, self.settings, self.settings_store, self.classifier, parent
        )
        dialog.settings_changed.connect(self._apply_settings)
        return dialog

    def _apply_settings(self) -> None:
        self.audio.configure(self.settings.sounds_enabled, self.settings.sound_volume)
        self.vault.auto_lock_seconds = self.settings.vault_auto_lock_seconds
        if self.hotkey.hotkey != self.settings.hotkey:
            try:
                self.hotkey.rebind(self.settings.hotkey)
            except Exception as exc:
                self.settings.hotkey = self.hotkey.hotkey
                self.settings_store.save(self.settings)
                QMessageBox.warning(
                    self.popup, "Global hotkey", f"Could not register hotkey:\n{exc}"
                )

    def _sweep_expired(self) -> None:
        if self.storage.sweep_expired() and self.popup.isVisible():
            self.popup.refresh()

    def _watch_vault_lock(self) -> None:
        unlocked = self.vault.is_unlocked
        if self._vault_was_unlocked and not unlocked and self.popup.isVisible():
            self.popup.refresh()
        self._vault_was_unlocked = unlocked


def main() -> int:
    if sys.platform != "win32":
        print("Clippy v0 supports Windows 11 only.", file=sys.stderr)
        return 1
    data_directory = app_data_dir()
    data_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(data_directory / "clippy.log", encoding="utf-8")],
    )
    application = QApplication(sys.argv)
    application.setApplicationName("Clippy")
    application.setOrganizationName("Clippy")
    logo = bundled_logo_path()
    if logo.is_file():
        application.setWindowIcon(QIcon(str(logo)))
    application.setQuitOnLastWindowClosed(False)
    application.setStyleSheet(APP_STYLE)
    runtime = ClippyRuntime(application)
    application.aboutToQuit.connect(runtime.stop)
    try:
        runtime.start()
    except Exception:
        runtime.stop()
        return 1
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
