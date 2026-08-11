from __future__ import annotations

from collections.abc import Callable

import pyperclip
from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..audio import AudioService
from ..capture import CaptureService
from ..config import AppSettings
from ..models import Entry
from ..platform_actions import extract_path, extract_url, open_url, reveal_path
from ..search import SearchService
from ..storage import Storage
from .dialogs import ConfigDialog, DiffDialog


class EntryRow(QWidget):
    pin_requested = Signal(int, bool)
    preview_requested = Signal(int)
    url_requested = Signal(int)
    path_requested = Signal(int)

    def __init__(self, entry: Entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 5, 4)
        pin_mark = "◆" if entry.pinned else "◇"
        self.pin = QToolButton()
        self.pin.setText(pin_mark)
        self.pin.setToolTip("Unpin" if entry.pinned else "Pin")
        self.pin.clicked.connect(lambda: self.pin_requested.emit(entry.id, not entry.pinned))
        layout.addWidget(self.pin)
        text = QLabel(entry.text.replace("\n", " ↵ "))
        text.setObjectName("Mono")
        text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(text, 1)
        section = QLabel(entry.section_name or "All")
        section.setObjectName("Secondary")
        layout.addWidget(section)
        if extract_url(entry.text):
            button = QToolButton()
            button.setText("↗")
            button.setToolTip("Open URL")
            button.clicked.connect(lambda: self.url_requested.emit(entry.id))
            layout.addWidget(button)
        if extract_path(entry.text):
            button = QToolButton()
            button.setText("▣")
            button.setToolTip("Reveal in Explorer")
            button.clicked.connect(lambda: self.path_requested.emit(entry.id))
            layout.addWidget(button)
        preview = QToolButton()
        preview.setText("/")
        preview.setToolTip("Preview full text")
        preview.clicked.connect(lambda: self.preview_requested.emit(entry.id))
        layout.addWidget(preview)
        self.setToolTip(f"{entry.created_at.astimezone():%Y-%m-%d %H:%M:%S}\n{entry.reason or ''}")


class PopupWindow(QWidget):
    settings_requested = Signal()

    def __init__(
        self,
        storage: Storage,
        search: SearchService,
        capture: CaptureService,
        audio: AudioService,
        settings: AppSettings,
        config_factory: Callable[[QWidget], ConfigDialog],
    ) -> None:
        super().__init__()
        self.storage = storage
        self.search_service = search
        self.capture = capture
        self.audio = audio
        self.settings = settings
        self.config_factory = config_factory
        self.current_section = "all"
        self.entries: dict[int, Entry] = {}
        self._closing = False
        self.setObjectName("Panel")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumSize(560, 400)
        self.resize(680, 520)
        self._build_ui()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(100)
        self._search_timer.timeout.connect(self.refresh)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        header = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search clipboard history…")
        self.search.textChanged.connect(lambda: self._search_timer.start())
        header.addWidget(self.search, 1)
        gear = QToolButton()
        gear.setText("⚙")
        gear.clicked.connect(self._open_config)
        header.addWidget(gear)
        root.addLayout(header)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        root.addWidget(self.tabs)

        self.stack = QStackedWidget()
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemClicked.connect(self._item_clicked)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        list_layout.addWidget(self.list)
        actions = QHBoxLayout()
        self.selected_label = QLabel("")
        self.selected_label.setObjectName("Secondary")
        self.copy_merged = QPushButton("Copy Merged")
        self.copy_merged.clicked.connect(self._copy_merged)
        self.diff = QPushButton("Diff")
        self.diff.clicked.connect(self._show_diff)
        self.move_vault = QPushButton("Move to Vault")
        self.move_vault.clicked.connect(self._move_to_vault)
        actions.addWidget(self.selected_label)
        actions.addStretch()
        actions.addWidget(self.copy_merged)
        actions.addWidget(self.diff)
        actions.addWidget(self.move_vault)
        list_layout.addLayout(actions)
        self.stack.addWidget(list_page)

        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        preview_header = QHBoxLayout()
        back = QPushButton("← Back")
        back.clicked.connect(self._close_preview)
        self.preview_meta = QLabel()
        self.preview_meta.setObjectName("Secondary")
        preview_header.addWidget(back)
        preview_header.addWidget(self.preview_meta, 1)
        preview_layout.addLayout(preview_header)
        from PySide6.QtWidgets import QPlainTextEdit

        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(self.preview_text)
        self.stack.addWidget(preview_page)
        root.addWidget(self.stack, 1)
        self._selection_changed()

    def rebuild_tabs(self) -> None:
        active = self.current_section
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        self.tabs.addTab("All")
        self.tabs.setTabData(0, "all")
        target = 0
        for section in self.storage.list_sections(visible_only=True):
            self.tabs.addTab(section.name)
            index = self.tabs.count() - 1
            self.tabs.setTabData(index, section.slug)
            if section.slug == active:
                target = index
        self.tabs.setCurrentIndex(target)
        self.tabs.blockSignals(False)
        self.current_section = str(self.tabs.tabData(target))

    def refresh(self) -> None:
        try:
            found = self.search_service.search(self.search.text(), self.current_section)
        except Exception as exc:
            QMessageBox.warning(self, "Search", str(exc))
            return
        self.entries = {entry.id: entry for entry in found}
        self.list.clear()
        for entry in found:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setSizeHint(QSize(0, 46))
            self.list.addItem(item)
            row = EntryRow(entry)
            row.pin_requested.connect(self._pin)
            row.preview_requested.connect(self._preview)
            row.url_requested.connect(self._open_url)
            row.path_requested.connect(self._open_path)
            self.list.setItemWidget(item, row)
        self._selection_changed()

    def show_popup(self) -> None:
        self._closing = False
        self.rebuild_tabs()
        self.refresh()
        cursor = QCursor.pos()
        screen = (
            self.screen() or QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return
        available = screen.availableGeometry()
        target = QRect(cursor.x() - 55, cursor.y() - 30, 680, 520)
        target.moveLeft(
            max(available.left(), min(target.left(), available.right() - target.width()))
        )
        target.moveTop(
            max(available.top(), min(target.top(), available.bottom() - target.height()))
        )
        start = QRect(cursor.x(), cursor.y(), 2, 2)
        self.setGeometry(start)
        self.setWindowOpacity(0.15)
        self.show()
        self.raise_()
        self.activateWindow()
        geometry = QPropertyAnimation(self, b"geometry", self)
        geometry.setDuration(190)
        geometry.setStartValue(start)
        geometry.setEndValue(target)
        geometry.setEasingCurve(QEasingCurve.Type.InOutCubic)
        opacity = QPropertyAnimation(self, b"windowOpacity", self)
        opacity.setDuration(170)
        opacity.setStartValue(0.15)
        opacity.setEndValue(1.0)
        group = QParallelAnimationGroup(self)
        group.addAnimation(geometry)
        group.addAnimation(opacity)
        self._animation = group
        group.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
        self.search.setFocus()
        self.audio.play("open")

    def close_animated(self) -> None:
        if self._closing or not self.isVisible():
            return
        self._closing = True
        current = self.geometry()
        end = QRect(current.center().x(), current.center().y(), 2, 2)
        geometry = QPropertyAnimation(self, b"geometry", self)
        geometry.setDuration(180)
        geometry.setStartValue(current)
        geometry.setEndValue(end)
        geometry.setEasingCurve(QEasingCurve.Type.InOutCubic)
        opacity = QPropertyAnimation(self, b"windowOpacity", self)
        opacity.setDuration(80)
        opacity.setStartValue(1.0)
        opacity.setEndValue(0.0)
        group = QParallelAnimationGroup(self)
        group.addAnimation(geometry)
        group.addAnimation(opacity)
        group.finished.connect(self._finish_close)
        self._animation = group
        group.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
        self.audio.play("close")

    def _finish_close(self) -> None:
        self.hide()
        self.setWindowOpacity(1.0)
        self._closing = False

    def focusOutEvent(self, event: QEvent) -> None:
        super().focusOutEvent(event)
        QTimer.singleShot(30, self._dismiss_if_inactive)

    def _dismiss_if_inactive(self) -> None:
        if not self.settings.pin_open and self.isVisible() and not self.isActiveWindow():
            if not any(dialog.isVisible() for dialog in self.findChildren(ConfigDialog)):
                self.close_animated()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self.stack.currentIndex() == 1:
                self._close_preview()
            else:
                self.close_animated()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            entries = self._selected_entries()
            if len(entries) == 1:
                self._copy_entry(entries[0])
                return
        super().keyPressEvent(event)

    def paintEvent(self, event: QEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor("transparent" if self._closing else "#B24BF3"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _tab_changed(self, index: int) -> None:
        if index >= 0:
            self.current_section = str(self.tabs.tabData(index))
            self.refresh()

    def _item_clicked(self, item: QListWidgetItem) -> None:
        if QApplication.keyboardModifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            return
        entry = self.entries.get(item.data(Qt.ItemDataRole.UserRole))
        if entry:
            self._copy_entry(entry)

    def _selected_entries(self) -> list[Entry]:
        return [
            self.entries[item.data(Qt.ItemDataRole.UserRole)]
            for item in self.list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole) in self.entries
        ]

    def _selection_changed(self) -> None:
        count = len(self.list.selectedItems())
        self.selected_label.setText(f"{count} selected" if count > 1 else "")
        self.copy_merged.setEnabled(count > 1)
        self.diff.setEnabled(count == 2)
        self.move_vault.setEnabled(count == 1)

    def _copy_entry(self, entry: Entry) -> None:
        self.capture.suppress_next(entry.text)
        pyperclip.copy(entry.text)
        self.audio.play("confirm")
        self.close_animated()

    def _copy_merged(self) -> None:
        entries = self._selected_entries()
        if len(entries) < 2:
            return
        text = "\n".join(entry.text for entry in entries)
        self.capture.suppress_next(text)
        pyperclip.copy(text)
        self.audio.play("confirm")
        self.close_animated()

    def _show_diff(self) -> None:
        entries = self._selected_entries()
        if len(entries) == 2:
            self._diff_dialog = DiffDialog(entries[0].text, entries[1].text, self)
            self._diff_dialog.show()

    def _pin(self, entry_id: int, pinned: bool) -> None:
        self.storage.set_pinned(entry_id, pinned)
        self.refresh()

    def _preview(self, entry_id: int) -> None:
        entry = self.entries.get(entry_id)
        if not entry:
            return
        self.preview_text.setPlainText(entry.text)
        self.preview_meta.setText(
            f"{entry.section_name or 'All'} · {entry.created_at.astimezone():%Y-%m-%d %H:%M:%S}"
        )
        self.stack.setCurrentIndex(1)

    def _close_preview(self) -> None:
        page = self.stack.currentWidget()
        animation = QPropertyAnimation(page, b"maximumHeight", self)
        animation.setDuration(150)
        animation.setStartValue(page.height())
        animation.setEndValue(1)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def finish() -> None:
            page.setMaximumHeight(16_777_215)
            self.stack.setCurrentIndex(0)
            self.list.setFocus()

        animation.finished.connect(finish)
        self._preview_animation = animation
        animation.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    def _open_url(self, entry_id: int) -> None:
        entry = self.entries.get(entry_id)
        if entry and not open_url(entry.text):
            QMessageBox.warning(self, "Open URL", "The URL could not be opened.")

    def _open_path(self, entry_id: int) -> None:
        entry = self.entries.get(entry_id)
        if entry and not reveal_path(entry.text):
            QMessageBox.warning(self, "Explorer", "The path does not exist or could not be opened.")

    def _move_to_vault(self) -> None:
        entries = self._selected_entries()
        if len(entries) != 1:
            return
        if not self.storage.vault_is_configured() or not self.storage.vault.is_unlocked:
            QMessageBox.information(
                self, "Vault", "Create or unlock the vault in configuration first."
            )
            return
        self.storage.move_to_vault(entries[0].id)
        self.refresh()

    def _open_config(self) -> None:
        self._config_dialog = self.config_factory(self)
        self._config_dialog.sections_changed.connect(self._config_updated)
        self._config_dialog.settings_changed.connect(self._config_updated)
        self._config_dialog.show()

    def _config_updated(self) -> None:
        self.rebuild_tabs()
        self.refresh()
