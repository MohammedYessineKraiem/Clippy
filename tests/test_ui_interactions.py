from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QToolButton

from clippy.audio import AudioService
from clippy.capture import CaptureService
from clippy.classification import Classifier
from clippy.config import AppSettings, SettingsStore
from clippy.embeddings import UnavailableEmbedder
from clippy.models import Classification
from clippy.search import SearchService
from clippy.security import VaultManager
from clippy.storage import Storage
from clippy.ui.dialogs import ConfigDialog, DiffDialog
from clippy.ui.popup import EntryRow, PopupWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_single_select_stays_open_and_activation_copies(tmp_path, monkeypatch):
    application = _application()
    storage = Storage(tmp_path / "ui.db", VaultManager())
    entry_id = storage.add_entry("copy me", Classification(None, "test"), None)
    embedder = UnavailableEmbedder()
    capture = CaptureService(storage, Classifier(embedder))
    popup = PopupWindow(
        storage,
        SearchService(storage, embedder),
        capture,
        AudioService(),
        AppSettings(),
        lambda _parent: None,
    )
    popup.rebuild_tabs()
    popup.refresh()
    popup.show()
    application.processEvents()

    popup._select_entry(entry_id, Qt.KeyboardModifier.NoModifier)
    assert popup.isVisible()
    assert len(popup.list.selectedItems()) == 1
    row = popup.list.itemWidget(popup.list.item(0))
    assert isinstance(row, EntryRow)
    assert "VAULT" in {button.text() for button in row.findChildren(QToolButton)}
    popup.resize(520, 380)
    application.processEvents()
    assert not row.time_label.isVisible()

    copied: list[str] = []
    monkeypatch.setattr("clippy.ui.popup.pyperclip.copy", copied.append)
    popup._activate_entry(entry_id)
    assert copied == ["copy me"]
    assert popup._closing
    popup.hide()
    storage.close()


def test_hotkey_method_toggles_visible_popup(tmp_path):
    application = _application()
    storage = Storage(tmp_path / "toggle.db", VaultManager())
    embedder = UnavailableEmbedder()
    capture = CaptureService(storage, Classifier(embedder))
    popup = PopupWindow(
        storage,
        SearchService(storage, embedder),
        capture,
        AudioService(),
        AppSettings(),
        lambda _parent: None,
    )
    popup.show_popup()
    application.processEvents()
    assert popup.isVisible()
    popup.show_popup()
    assert popup._closing
    popup.hide()
    storage.close()


def test_neon_diff_rows_are_aligned_and_classified():
    rows, changed, added, removed = DiffDialog._build_rows(
        "same\nold value\nremoved", "same\nnew value\nadded\nextra"
    )
    rendered = DiffDialog._render_html(rows)

    assert changed == 2
    assert added == 1
    assert removed == 0
    assert "CLIP A // ORIGINAL" in rendered
    assert "#291238" in rendered
    assert "diff_header" not in rendered


def test_config_semantic_toggle_persists_exclusive_mode(tmp_path):
    _application()
    storage = Storage(tmp_path / "config.db", VaultManager())
    settings = AppSettings()
    dialog = ConfigDialog(
        storage,
        settings,
        SettingsStore(tmp_path / "config.json"),
        Classifier(UnavailableEmbedder()),
    )

    dialog.semantic_search.click()
    dialog._save_general()

    assert settings.semantic_search_enabled
    assert dialog.semantic_search.text() == "SEMANTIC SEARCH: ON"
    storage.close()


def test_section_editor_cancel_returns_control_to_config(tmp_path):
    application = _application()
    storage = Storage(tmp_path / "section-dialog.db", VaultManager())
    dialog = ConfigDialog(
        storage,
        AppSettings(),
        SettingsStore(tmp_path / "section-config.json"),
        Classifier(UnavailableEmbedder()),
    )
    dialog.show()

    dialog._add_section()
    application.processEvents()

    editor = dialog._section_editor
    assert editor is not None
    assert editor.isVisible()
    editor.reject()
    application.processEvents()

    assert dialog._section_editor is None
    assert dialog.isVisible()

    dialog._add_section()
    application.processEvents()
    editor = dialog._section_editor
    assert editor is not None
    editor.name.setText("Project notes")
    editor._save()
    application.processEvents()

    assert dialog._section_editor is None
    assert any(section.slug == "project-notes" for section in storage.list_sections())
    dialog.reject()
    storage.close()


def test_hotkey_close_rejects_all_owned_dialogs(tmp_path):
    application = _application()
    storage = Storage(tmp_path / "nested-dialog.db", VaultManager())
    embedder = UnavailableEmbedder()
    settings = AppSettings(pin_open=True)

    def config_factory(parent):
        return ConfigDialog(
            storage,
            settings,
            SettingsStore(tmp_path / "nested-config.json"),
            Classifier(embedder),
            parent,
        )

    popup = PopupWindow(
        storage,
        SearchService(storage, embedder),
        CaptureService(storage, Classifier(embedder)),
        AudioService(),
        settings,
        config_factory,
    )
    popup.show_popup()
    application.processEvents()
    popup._open_config()
    assert popup._config_dialog is not None
    popup._config_dialog._add_section()
    application.processEvents()
    editor = popup._config_dialog._section_editor
    assert editor is not None and editor.isVisible()

    popup.show_popup()
    application.processEvents()

    assert popup._closing
    assert popup._config_dialog is None
    assert not any(
        widget is not popup and popup._owns_widget(widget) and widget.isVisible()
        for widget in application.topLevelWidgets()
    )
    popup.hide()
    storage.close()
