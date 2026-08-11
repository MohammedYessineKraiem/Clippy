from __future__ import annotations

import difflib
import html
import re

from PySide6.QtCore import Qt, Signal
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


class ClippyDialog(QDialog):
    """Base dialog with deterministic close behavior.

    Dialog rejection must complete synchronously. Delaying it behind an animation can
    leave a modal event loop alive after its parent has been hidden.
    """

    def reject(self) -> None:
        QDialog.reject(self)


class SectionEditor(ClippyDialog):
    def __init__(self, section: Section, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.section = section
        permanent_risk = section.slug == "malicious"
        self.setWindowTitle(f"Section - {section.name}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(section.name)
        self.name.setEnabled(not permanent_risk)
        self.kind = QComboBox()
        self.kind.addItems(["structural", "syntax", "semantic"])
        self.kind.setCurrentText(
            section.kind.value if section.kind is not SectionKind.VAULT else "semantic"
        )
        self.kind.setEnabled(not section.system)
        self.visible = QCheckBox("Show section tab")
        self.visible.setChecked(section.visible)
        self.visible.setEnabled(not permanent_risk)
        self.expiry = QSpinBox()
        self.expiry.setRange(0, 24 * 3650)
        self.expiry.setSuffix(" hours (0 = never)")
        self.expiry.setValue((section.expiry_seconds or 0) // 3600)
        form.addRow("Name", self.name)
        form.addRow("Kind", self.kind)
        form.addRow("Visibility", self.visible)
        form.addRow("Expiry", self.expiry)
        layout.addLayout(form)
        if permanent_risk:
            risk_note = QLabel(
                "Built-in local risk rules are always active. Add custom risky domains, URLs, "
                "or source markers below; this is a warning system, not a malware verdict."
            )
            risk_note.setWordWrap(True)
            risk_note.setObjectName("RiskNotice")
            layout.addWidget(risk_note)
            patterns_label = QLabel(
                "Custom risk list - one per line (domain:, url:, source:, keyword:, or re:)"
            )
        else:
            patterns_label = QLabel("Patterns - one per line (re: or keyword: prefixes supported)")
        layout.addWidget(patterns_label)
        from PySide6.QtWidgets import QPlainTextEdit

        self.patterns = QPlainTextEdit("\n".join(section.patterns))
        if permanent_risk:
            self.patterns.setPlaceholderText(
                "domain:bad.example\nurl:https://example.test/download\nsource:Unknown Publisher"
            )
        layout.addWidget(self.patterns)
        examples_label = QLabel("Semantic prototype examples - one per line")
        layout.addWidget(examples_label)
        self.examples = QPlainTextEdit("\n".join(section.examples))
        layout.addWidget(self.examples)
        examples_label.setVisible(not permanent_risk)
        self.examples.setVisible(not permanent_risk)
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
        self.section.visible = (
            True if self.section.slug == "malicious" else self.visible.isChecked()
        )
        self.section.expiry_seconds = self.expiry.value() * 3600 or None
        self.section.patterns = [
            line.strip() for line in self.patterns.toPlainText().splitlines() if line.strip()
        ]
        self.section.examples = [
            line.strip() for line in self.examples.toPlainText().splitlines() if line.strip()
        ]
        self.accept()


class DiffDialog(ClippyDialog):
    def __init__(self, left: str, right: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DiffDialog")
        self.setWindowTitle("Clippy diff")
        self.setMinimumSize(660, 420)
        self.resize(980, 640)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel("DIFF // TWO CLIPS")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)
        rows, changed, added, removed = self._build_rows(left, right)
        summary = QLabel(f"{changed} changed   /   {added} added   /   {removed} removed")
        summary.setObjectName("Secondary")
        layout.addWidget(summary)
        browser = QTextBrowser()
        browser.setObjectName("DiffBrowser")
        browser.setHtml(self._render_html(rows))
        layout.addWidget(browser)
        close = QPushButton("Close")
        close.setObjectName("PrimaryButton")
        close.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("Purple = changed   Cyan = added   Magenta = removed"))
        footer.addStretch()
        footer.addWidget(close)
        layout.addLayout(footer)

    @staticmethod
    def _build_rows(
        left: str, right: str
    ) -> tuple[list[tuple[int | None, str, int | None, str, str]], int, int, int]:
        left_lines = left.splitlines() or [""]
        right_lines = right.splitlines() or [""]
        matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
        rows: list[tuple[int | None, str, int | None, str, str]] = []
        changed = added = removed = 0
        for operation, left_start, left_end, right_start, right_end in matcher.get_opcodes():
            if operation == "equal":
                for offset in range(left_end - left_start):
                    rows.append(
                        (
                            left_start + offset + 1,
                            left_lines[left_start + offset],
                            right_start + offset + 1,
                            right_lines[right_start + offset],
                            "equal",
                        )
                    )
                continue
            count = max(left_end - left_start, right_end - right_start)
            for offset in range(count):
                has_left = left_start + offset < left_end
                has_right = right_start + offset < right_end
                left_number = left_start + offset + 1 if has_left else None
                right_number = right_start + offset + 1 if has_right else None
                left_text = left_lines[left_start + offset] if has_left else ""
                right_text = right_lines[right_start + offset] if has_right else ""
                state = operation
                if operation == "replace":
                    if has_left and has_right:
                        changed += 1
                    elif has_right:
                        state = "insert"
                        added += 1
                    else:
                        state = "delete"
                        removed += 1
                elif operation == "insert":
                    added += 1
                else:
                    removed += 1
                rows.append((left_number, left_text, right_number, right_text, state))
        return rows, changed, added, removed

    @staticmethod
    def _render_html(rows: list[tuple[int | None, str, int | None, str, str]]) -> str:
        rendered: list[str] = []
        for left_number, left_text, right_number, right_text, state in rows:
            left_style = right_style = ""
            if state == "replace":
                left_style = right_style = "background:#291238;color:#F1D6FF;"
            elif state == "insert":
                right_style = "background:#082B2E;color:#94F4EB;"
            elif state == "delete":
                left_style = "background:#321028;color:#FF9DD8;"
            rendered.append(
                f'<tr class="{state}">'
                f'<td class="num">{left_number or ""}</td>'
                f'<td class="code" style="{left_style}">'
                f"{html.escape(left_text) or '&nbsp;'}</td>"
                f'<td class="num">{right_number or ""}</td>'
                f'<td class="code" style="{right_style}">'
                f"{html.escape(right_text) or '&nbsp;'}</td>"
                "</tr>"
            )
        return (
            """<!doctype html><html><head><style>
            body { background:#0B0710; color:#E8DFF0; margin:0; }
            table { width:100%; border-collapse:collapse; font-family:Consolas,monospace; }
            th { color:#D7A8F5; background:#120A1C; border:1px solid #4A2860;
                 padding:10px; text-align:left; font-size:13px; }
            td { border-bottom:1px solid #281431; padding:6px 8px; vertical-align:top; }
            td.num { width:34px; color:#73627E; text-align:right; background:#0D0812; }
            td.code { white-space:pre-wrap; color:#DCCFE5; }
        </style></head><body><table width="100%" cellspacing="0" cellpadding="0">
        <tr><th width="50%" colspan="2">CLIP A // ORIGINAL</th>
        <th width="50%" colspan="2">CLIP B // COMPARE</th></tr>
        """
            + "".join(rendered)
            + "</table></body></html>"
        )


class ConfigDialog(ClippyDialog):
    settings_changed = Signal()
    sections_changed = Signal()
    quit_requested = Signal()

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
        self._section_editor: SectionEditor | None = None
        self.setWindowTitle("Clippy configuration")
        self.resize(620, 520)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._sections_tab(), "Sections")
        tabs.addTab(self._vault_tab(), "Vault")
        root.addWidget(tabs)
        footer = QHBoxLayout()
        quit_button = QPushButton("Quit Clippy")
        quit_button.setObjectName("DangerButton")
        quit_button.clicked.connect(self.quit_requested.emit)
        close = QPushButton("Close panel")
        close.clicked.connect(self.reject)
        footer.addWidget(quit_button)
        footer.addStretch()
        footer.addWidget(close)
        root.addLayout(footer)

    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.hotkey = QLineEdit(self.settings.hotkey)
        self.pin_open = QCheckBox("Keep popup open when it loses focus")
        self.pin_open.setChecked(self.settings.pin_open)
        self.semantic_search = QPushButton()
        self.semantic_search.setObjectName("ToggleButton")
        self.semantic_search.setCheckable(True)
        self.semantic_search.setChecked(self.settings.semantic_search_enabled)
        self.semantic_search.setToolTip(
            "Enabled: rank by meaning only. Disabled: substring and typo-tolerant search."
        )
        self.semantic_search.toggled.connect(self._update_semantic_button)
        self._update_semantic_button(self.semantic_search.isChecked())
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
        form.addRow("Search mode", self.semantic_search)
        form.addRow("Audio", self.sounds)
        form.addRow("Volume", self.volume)
        form.addRow(save)
        form.addRow(cleanup)
        return page

    def _update_semantic_button(self, enabled: bool) -> None:
        self.semantic_search.setText("SEMANTIC SEARCH: ON" if enabled else "SEMANTIC SEARCH: OFF")

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
        self.settings.semantic_search_enabled = self.semantic_search.isChecked()
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
            if section.slug == "malicious":
                suffix = " (permanent)"
            else:
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
        self._open_section_editor(section)

    def _edit_section(self) -> None:
        section = self._selected_section()
        if not section:
            return
        self._open_section_editor(section)

    def _open_section_editor(self, section: Section) -> None:
        if self._section_editor is not None and self._section_editor.isVisible():
            self._section_editor.raise_()
            self._section_editor.activateWindow()
            return
        editor = SectionEditor(section, self)
        editor.setWindowModality(Qt.WindowModality.WindowModal)
        editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        editor.accepted.connect(lambda: self._save_section(section))
        editor.finished.connect(self._section_editor_closed)
        self._section_editor = editor
        editor.open()

    def _save_section(self, section: Section) -> None:
        try:
            self.storage.save_section(section)
        except Exception as exc:
            QMessageBox.warning(self, "Section", str(exc))
            return
        if section.slug == "malicious":
            self.storage.flag_existing_risks()
        self.classifier.clear_prototype_cache()
        self._refresh_sections()
        self.sections_changed.emit()

    def _section_editor_closed(self) -> None:
        self._section_editor = None

    def _delete_section(self) -> None:
        section = self._selected_section()
        if not section:
            return
        if section.slug == "malicious":
            QMessageBox.information(
                self, "Malicious section", "The local risk section is permanent."
            )
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
        if left.slug == "malicious" or right.slug == "malicious":
            return
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
