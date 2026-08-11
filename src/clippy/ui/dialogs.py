from __future__ import annotations

import difflib
import re

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..classification import Classifier
from ..config import AppSettings, SettingsStore
from ..models import Section, SectionKind
from ..security import InvalidPassphraseError
from ..storage import Storage


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


class AnimatedDialog(QDialog):
    def reject(self) -> None:
        current = self.geometry()
        end = QRect(current.left(), current.center().y(), current.width(), 2)
        geometry = QPropertyAnimation(self, b"geometry", self)
        geometry.setDuration(170)
        geometry.setStartValue(current)
        geometry.setEndValue(end)
        geometry.setEasingCurve(QEasingCurve.Type.InOutCubic)
        opacity = QPropertyAnimation(self, b"windowOpacity", self)
        opacity.setDuration(90)
        opacity.setStartValue(self.windowOpacity())
        opacity.setEndValue(0.0)
        group = QParallelAnimationGroup(self)
        group.addAnimation(geometry)
        group.addAnimation(opacity)
        group.finished.connect(super().reject)
        self._close_animation = group
        group.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


class SectionEditor(AnimatedDialog):
    def __init__(self, section: Section, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.section = section
        self.setWindowTitle("Section")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(section.name)
        self.kind = QComboBox()
        self.kind.addItems(["structural", "syntax", "semantic"])
        self.kind.setCurrentText(
            section.kind.value if section.kind is not SectionKind.VAULT else "semantic"
        )
        self.kind.setEnabled(not section.system)
        self.visible = QCheckBox("Show section tab")
        self.visible.setChecked(section.visible)
        self.expiry = QSpinBox()
        self.expiry.setRange(0, 24 * 3650)
        self.expiry.setSuffix(" hours (0 = never)")
        self.expiry.setValue((section.expiry_seconds or 0) // 3600)
        form.addRow("Name", self.name)
        form.addRow("Kind", self.kind)
        form.addRow("Visibility", self.visible)
        form.addRow("Expiry", self.expiry)
        layout.addLayout(form)
        layout.addWidget(QLabel("Patterns — one per line (`re:` or `keyword:` prefixes supported)"))
        from PySide6.QtWidgets import QPlainTextEdit

        self.patterns = QPlainTextEdit("\n".join(section.patterns))
        layout.addWidget(self.patterns)
        layout.addWidget(QLabel("Semantic prototype examples — one per line"))
        self.examples = QPlainTextEdit("\n".join(section.examples))
        layout.addWidget(self.examples)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Section", "Section name is required.")
            return
        self.section.name = name
        if not self.section.system:
            self.section.slug = slugify(name)
            self.section.kind = SectionKind(self.kind.currentText())
        self.section.visible = self.visible.isChecked()
        self.section.expiry_seconds = self.expiry.value() * 3600 or None
        self.section.patterns = [
            line.strip() for line in self.patterns.toPlainText().splitlines() if line.strip()
        ]
        self.section.examples = [
            line.strip() for line in self.examples.toPlainText().splitlines() if line.strip()
        ]
        self.accept()


class DiffDialog(AnimatedDialog):
    def __init__(self, left: str, right: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare entries")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(
            difflib.HtmlDiff(wrapcolumn=80).make_file(
                left.splitlines(), right.splitlines(), "First", "Second", context=True, numlines=3
            )
        )
        layout.addWidget(browser)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        layout.addWidget(close)


class ConfigDialog(AnimatedDialog):
    settings_changed = Signal()
    sections_changed = Signal()

    def __init__(
        self,
        storage: Storage,
        settings: AppSettings,
        settings_store: SettingsStore,
        classifier: Classifier,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.settings = settings
        self.settings_store = settings_store
        self.classifier = classifier
        self.setWindowTitle("Clippy configuration")
        self.resize(620, 520)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._sections_tab(), "Sections")
        tabs.addTab(self._vault_tab(), "Vault")
        root.addWidget(tabs)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        root.addWidget(close)

    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.hotkey = QLineEdit(self.settings.hotkey)
        self.pin_open = QCheckBox("Keep popup open when it loses focus")
        self.pin_open.setChecked(self.settings.pin_open)
        self.sounds = QCheckBox("Enable sound cues")
        self.sounds.setChecked(self.settings.sounds_enabled)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(round(self.settings.sound_volume * 100))
        save = QPushButton("Save general settings")
        save.clicked.connect(self._save_general)
        cleanup = QPushButton("Merge exact duplicates")
        cleanup.clicked.connect(self._cleanup)
        form.addRow("Global hotkey", self.hotkey)
        form.addRow("Popup", self.pin_open)
        form.addRow("Audio", self.sounds)
        form.addRow("Volume", self.volume)
        form.addRow(save)
        form.addRow(cleanup)
        return page

    def _sections_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel("Priority is top to bottom. The first confident classifier match wins.")
        )
        self.section_list = QListWidget()
        layout.addWidget(self.section_list)
        buttons = QHBoxLayout()
        for label, callback in (
            ("Add", self._add_section),
            ("Edit", self._edit_section),
            ("Delete", self._delete_section),
            ("Up", lambda: self._move_section(-1)),
            ("Down", lambda: self._move_section(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._refresh_sections()
        return page

    def _vault_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.vault_status = QLabel()
        layout.addWidget(self.vault_status)
        self.lock_timeout = QSpinBox()
        self.lock_timeout.setRange(0, 3600)
        self.lock_timeout.setSuffix(" seconds (0 = never)")
        self.lock_timeout.setValue(self.settings.vault_auto_lock_seconds)
        self.lock_timeout.valueChanged.connect(self._save_vault_timeout)
        layout.addWidget(QLabel("Auto-lock after last vault activity"))
        layout.addWidget(self.lock_timeout)
        controls = QHBoxLayout()
        configure = QPushButton("Create vault")
        configure.clicked.connect(self._configure_vault)
        unlock = QPushButton("Unlock")
        unlock.clicked.connect(self._unlock_vault)
        lock = QPushButton("Lock")
        lock.clicked.connect(self._lock_vault)
        controls.addWidget(configure)
        controls.addWidget(unlock)
        controls.addWidget(lock)
        layout.addLayout(controls)
        layout.addStretch()
        self._refresh_vault_status()
        return page

    def _save_general(self) -> None:
        self.settings.hotkey = self.hotkey.text().strip() or "<ctrl>+<alt>+v"
        self.settings.pin_open = self.pin_open.isChecked()
        self.settings.sounds_enabled = self.sounds.isChecked()
        self.settings.sound_volume = self.volume.value() / 100
        self.settings_store.save(self.settings)
        self.settings_changed.emit()

    def _cleanup(self) -> None:
        removed = self.storage.merge_exact_duplicates()
        QMessageBox.information(self, "Duplicate cleanup", f"Removed {removed} exact duplicate(s).")
        self.sections_changed.emit()

    def _refresh_sections(self) -> None:
        self.section_list.clear()
        for section in self.storage.list_sections():
            if section.kind is SectionKind.VAULT:
                continue
            suffix = "" if section.visible else " (hidden)"
            self.section_list.addItem(f"{section.name} · {section.kind.value}{suffix}")
            self.section_list.item(self.section_list.count() - 1).setData(
                Qt.ItemDataRole.UserRole, section.id
            )

    def _selected_section(self) -> Section | None:
        item = self.section_list.currentItem()
        if not item:
            return None
        section_id = item.data(Qt.ItemDataRole.UserRole)
        return next((s for s in self.storage.list_sections() if s.id == section_id), None)

    def _add_section(self) -> None:
        priority = (
            max(
                (
                    s.priority
                    for s in self.storage.list_sections()
                    if s.kind is not SectionKind.VAULT
                ),
                default=0,
            )
            + 10
        )
        section = Section(0, "New section", "new-section", SectionKind.SEMANTIC, priority)
        editor = SectionEditor(section, self)
        if editor.exec():
            try:
                self.storage.save_section(section)
            except Exception as exc:
                QMessageBox.warning(self, "Section", str(exc))
                return
            self.classifier.clear_prototype_cache()
            self._refresh_sections()
            self.sections_changed.emit()

    def _edit_section(self) -> None:
        section = self._selected_section()
        if not section:
            return
        if SectionEditor(section, self).exec():
            self.storage.save_section(section)
            self.classifier.clear_prototype_cache()
            self._refresh_sections()
            self.sections_changed.emit()

    def _delete_section(self) -> None:
        section = self._selected_section()
        if not section:
            return
        try:
            self.storage.delete_section(section.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Section", str(exc))
            return
        self._refresh_sections()
        self.sections_changed.emit()

    def _move_section(self, offset: int) -> None:
        row = self.section_list.currentRow()
        other_row = row + offset
        if row < 0 or other_row < 0 or other_row >= self.section_list.count():
            return
        sections = [s for s in self.storage.list_sections() if s.kind is not SectionKind.VAULT]
        left, right = sections[row], sections[other_row]
        left.priority, right.priority = right.priority, left.priority
        self.storage.save_section(left)
        self.storage.save_section(right)
        self._refresh_sections()
        self.section_list.setCurrentRow(other_row)
        self.sections_changed.emit()

    def _save_vault_timeout(self, value: int) -> None:
        self.settings.vault_auto_lock_seconds = value
        self.storage.vault.auto_lock_seconds = value
        self.settings_store.save(self.settings)

    def _configure_vault(self) -> None:
        if self.storage.vault_is_configured():
            QMessageBox.information(self, "Vault", "The vault is already configured.")
            return
        first, ok = QInputDialog.getText(
            self, "Create vault", "Passphrase", QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        second, ok = QInputDialog.getText(
            self, "Create vault", "Confirm passphrase", QLineEdit.EchoMode.Password
        )
        if not ok or first != second:
            QMessageBox.warning(self, "Vault", "Passphrases do not match.")
            return
        try:
            self.storage.configure_vault(first)
        except ValueError as exc:
            QMessageBox.warning(self, "Vault", str(exc))
        self._refresh_vault_status()

    def _unlock_vault(self) -> None:
        password, ok = QInputDialog.getText(
            self, "Unlock vault", "Passphrase", QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        try:
            self.storage.unlock_vault(password)
        except (InvalidPassphraseError, ValueError) as exc:
            QMessageBox.warning(self, "Vault", str(exc))
        self._refresh_vault_status()
        self.sections_changed.emit()

    def _lock_vault(self) -> None:
        self.storage.vault.lock()
        self._refresh_vault_status()
        self.sections_changed.emit()

    def _refresh_vault_status(self) -> None:
        configured = self.storage.vault_is_configured()
        state = "unlocked" if self.storage.vault.is_unlocked else "locked"
        self.vault_status.setText(f"Vault: {state}" if configured else "Vault: not configured")
