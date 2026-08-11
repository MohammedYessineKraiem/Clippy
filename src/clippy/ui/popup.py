from __future__ import annotations

from collections.abc import Callable

import pyperclip
from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..audio import AudioService
from ..capture import CaptureService
from ..config import AppSettings, bundled_logo_path
from ..models import Entry
from ..platform_actions import extract_path, extract_url, open_url, reveal_path
from ..search import SearchService
from ..security import InvalidPassphraseError
from ..storage import Storage
from .dialogs import ConfigDialog, DiffDialog


class DragBar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self._drag_offset: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class EntryRow(QWidget):
    activated = Signal(int)
    selection_requested = Signal(int, object)
    pin_requested = Signal(int, bool)
    preview_requested = Signal(int)
    url_requested = Signal(int)
    path_requested = Signal(int)
    vault_requested = Signal(int)

    def __init__(self, entry: Entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("EntryRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 7, 8, 7)
        layout.setSpacing(7)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        self.text_label = QLabel(entry.text.replace("\n", "  /  "))
        self.text_label.setObjectName("EntryText")
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content.addWidget(self.text_label)

        metadata = QHBoxLayout()
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(7)
        tag = QLabel((entry.section_name or "All").upper())
        tag.setObjectName("Tag")
        metadata.addWidget(tag)
        self.time_label = QLabel(entry.created_at.astimezone().strftime("%H:%M  /  %d %b"))
        self.time_label.setObjectName("Secondary")
        metadata.addWidget(self.time_label)
        metadata.addStretch()
        content.addLayout(metadata)
        layout.addLayout(content, 1)

        if extract_url(entry.text):
            button = self._action_button("URL", "Open in the default browser")
            button.clicked.connect(lambda: self.url_requested.emit(entry.id))
            layout.addWidget(button)
        if extract_path(entry.text):
            button = self._action_button("FILE", "Reveal in Explorer")
            button.clicked.connect(lambda: self.path_requested.emit(entry.id))
            layout.addWidget(button)
        if not entry.vault:
            button = self._action_button("VAULT", "Encrypt and move to Vault")
            button.clicked.connect(lambda: self.vault_requested.emit(entry.id))
            layout.addWidget(button)
        preview = self._action_button("VIEW", "Preview full text")
        preview.clicked.connect(lambda: self.preview_requested.emit(entry.id))
        layout.addWidget(preview)
        pin = self._action_button("UNPIN" if entry.pinned else "PIN", "Toggle pin")
        pin.clicked.connect(lambda: self.pin_requested.emit(entry.id, not entry.pinned))
        layout.addWidget(pin)
        self.setToolTip(f"{entry.created_at.astimezone():%Y-%m-%d %H:%M:%S}\n{entry.reason or ''}")

    @staticmethod
    def _action_button(text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("RowAction")
        button.setText(text)
        button.setToolTip(tooltip)
        return button

    def set_compact(self, compact: bool) -> None:
        self.time_label.setVisible(not compact)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selection_requested.emit(self.entry.id, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.entry.id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class PopupWindow(QWidget):
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
        self._opening = False
        self._preferred_size = QSize(760, 540)
        self.setObjectName("Panel")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMinimumSize(500, 350)
        self.resize(self._preferred_size)
        self._build_ui()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(110)
        self._search_timer.timeout.connect(self.refresh)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(11, 9, 9, 8)
        root.setSpacing(8)

        title_bar = DragBar()
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(4, 1, 2, 1)
        logo_path = bundled_logo_path()
        if logo_path.is_file():
            logo = QLabel()
            logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            logo.setPixmap(
                QPixmap(str(logo_path)).scaledToHeight(
                    28, Qt.TransformationMode.SmoothTransformation
                )
            )
            title_layout.addWidget(logo)
        title = QLabel("CLIPPY  //  LOCAL CLIPBOARD")
        title.setObjectName("PanelTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout.addWidget(title)
        title_layout.addStretch()
        drag_hint = QLabel("DRAG")
        drag_hint.setObjectName("Secondary")
        drag_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout.addWidget(drag_hint)
        close_button = QToolButton()
        close_button.setObjectName("WindowControl")
        close_button.setText("X")
        close_button.setToolTip("Close popup")
        close_button.clicked.connect(self.close_animated)
        title_layout.addWidget(close_button)
        root.addWidget(title_bar)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("SearchInput")
        self.search.setPlaceholderText("Search clipboard history")
        self.search.textChanged.connect(lambda: self._search_timer.start())
        search_row.addWidget(self.search, 1)
        self.mode_badge = QLabel()
        self.mode_badge.setObjectName("ModeBadge")
        search_row.addWidget(self.mode_badge)
        config_button = QToolButton()
        config_button.setObjectName("HeaderButton")
        config_button.setText("CONFIG")
        config_button.clicked.connect(self._open_config)
        search_row.addWidget(config_button)
        root.addLayout(search_row)

        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        root.addWidget(self.tabs)

        self.stack = QStackedWidget()
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(7)
        self.list = QListWidget()
        self.list.setObjectName("EntryList")
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self._item_double_clicked)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        list_layout.addWidget(self.list)

        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 0, 0)
        self.selected_label = QLabel("Double-click a row to copy")
        self.selected_label.setObjectName("Secondary")
        self.copy_merged = QPushButton("COPY MERGED")
        self.copy_merged.clicked.connect(self._copy_merged)
        self.diff = QPushButton("COMPARE 2")
        self.diff.clicked.connect(self._show_diff)
        footer.addWidget(self.selected_label)
        footer.addStretch()
        footer.addWidget(self.copy_merged)
        footer.addWidget(self.diff)
        footer.addWidget(QSizeGrip(self))
        list_layout.addLayout(footer)
        self.stack.addWidget(list_page)

        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        preview_header = QHBoxLayout()
        back = QPushButton("BACK")
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
        self._update_mode_badge()
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
        self._update_mode_badge()
        try:
            found = self.search_service.search(
                self.search.text(),
                self.current_section,
                semantic_only=self.settings.semantic_search_enabled,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Search", str(exc))
            return
        self.entries = {entry.id: entry for entry in found}
        self.list.clear()
        compact = self.width() < 650
        for entry in found:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setSizeHint(QSize(0, 62))
            self.list.addItem(item)
            row = EntryRow(entry)
            row.set_compact(compact)
            row.activated.connect(self._activate_entry)
            row.selection_requested.connect(self._select_entry)
            row.pin_requested.connect(self._pin)
            row.preview_requested.connect(self._preview)
            row.url_requested.connect(self._open_url)
            row.path_requested.connect(self._open_path)
            row.vault_requested.connect(self._move_to_vault)
            self.list.setItemWidget(item, row)
        self._selection_changed()

    def show_popup(self) -> None:
        if self.isVisible() and not self._closing:
            self.close_animated()
            return
        if self._closing:
            return
        self._opening = True
        self.rebuild_tabs()
        self.refresh()
        cursor = QCursor.pos()
        screen = (
            QGuiApplication.screenAt(cursor) or self.screen() or QGuiApplication.primaryScreen()
        )
        if screen is None:
            self._opening = False
            return
        available = screen.availableGeometry()
        size = self._preferred_size.expandedTo(self.minimumSize())
        target = QRect(cursor.x() - 55, cursor.y() - 30, size.width(), size.height())
        target.moveLeft(
            max(available.left(), min(target.left(), available.right() - target.width()))
        )
        target.moveTop(
            max(available.top(), min(target.top(), available.bottom() - target.height()))
        )
        start = QRect(cursor.x(), cursor.y(), 2, 2)
        self.setGeometry(start)
        self.setWindowOpacity(0.12)
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
        opacity.setStartValue(0.12)
        opacity.setEndValue(1.0)
        group = QParallelAnimationGroup(self)
        group.addAnimation(geometry)
        group.addAnimation(opacity)
        group.finished.connect(self._finish_open)
        self._animation = group
        group.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
        self.search.setFocus()
        self.audio.play("open")

    def _finish_open(self) -> None:
        self._opening = False

    def close_animated(self) -> None:
        if self._closing or not self.isVisible():
            return
        self._opening = False
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
        self.stack.setCurrentIndex(0)
        self._closing = False

    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if event.type() == QEvent.Type.WindowDeactivate:
            QTimer.singleShot(60, self._dismiss_if_inactive)
        return result

    def focusOutEvent(self, event: QEvent) -> None:
        super().focusOutEvent(event)
        QTimer.singleShot(60, self._dismiss_if_inactive)

    def _dismiss_if_inactive(self) -> None:
        if self.settings.pin_open or not self.isVisible() or self.isActiveWindow():
            return
        child_panels = (
            getattr(self, "_config_dialog", None),
            getattr(self, "_diff_dialog", None),
        )
        if any(panel is not None and panel.isVisible() for panel in child_panels):
            return
        self.close_animated()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isVisible() and not self._opening and not self._closing:
            self._preferred_size = event.size()
        compact = event.size().width() < 650
        for index in range(self.list.count()):
            row = self.list.itemWidget(self.list.item(index))
            if isinstance(row, EntryRow):
                row.set_compact(compact)

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

    def _update_mode_badge(self) -> None:
        semantic = self.settings.semantic_search_enabled
        self.mode_badge.setText("SEMANTIC" if semantic else "FAST")
        self.mode_badge.setProperty("semantic", semantic)
        self.mode_badge.style().unpolish(self.mode_badge)
        self.mode_badge.style().polish(self.mode_badge)

    def _tab_changed(self, index: int) -> None:
        if index >= 0:
            self.current_section = str(self.tabs.tabData(index))
            self.refresh()

    def _item_double_clicked(self, item: QListWidgetItem) -> None:
        entry = self.entries.get(item.data(Qt.ItemDataRole.UserRole))
        if entry:
            self._copy_entry(entry)

    def _activate_entry(self, entry_id: int) -> None:
        entry = self.entries.get(entry_id)
        if entry:
            self._copy_entry(entry)

    def _select_entry(self, entry_id: int, modifiers: object) -> None:
        target_row = -1
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == entry_id:
                target_row = index
                break
        if target_row < 0:
            return
        item = self.list.item(target_row)
        keyboard_modifiers = modifiers
        if keyboard_modifiers & Qt.KeyboardModifier.ControlModifier:
            item.setSelected(not item.isSelected())
        elif keyboard_modifiers & Qt.KeyboardModifier.ShiftModifier and self.list.currentRow() >= 0:
            start, end = sorted((self.list.currentRow(), target_row))
            for index in range(start, end + 1):
                self.list.item(index).setSelected(True)
        else:
            self.list.clearSelection()
            item.setSelected(True)
        self.list.setCurrentItem(item)

    def _selected_entries(self) -> list[Entry]:
        return [
            self.entries[item.data(Qt.ItemDataRole.UserRole)]
            for item in self.list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole) in self.entries
        ]

    def _selection_changed(self) -> None:
        count = len(self.list.selectedItems())
        if count > 1:
            self.selected_label.setText(f"{count} SELECTED")
        elif count == 1:
            self.selected_label.setText("Selected  /  double-click to copy")
        else:
            self.selected_label.setText("Double-click a row to copy")
        self.copy_merged.setEnabled(count > 1)
        self.diff.setEnabled(count == 2)

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
            f"{entry.section_name or 'All'}  /  {entry.created_at.astimezone():%Y-%m-%d %H:%M:%S}"
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

    def _move_to_vault(self, entry_id: int) -> None:
        if not self.storage.vault_is_configured():
            passphrase, ok = QInputDialog.getText(
                self, "Create vault", "New passphrase", QLineEdit.EchoMode.Password
            )
            if not ok:
                return
            confirmation, ok = QInputDialog.getText(
                self, "Create vault", "Confirm passphrase", QLineEdit.EchoMode.Password
            )
            if not ok or confirmation != passphrase:
                QMessageBox.warning(self, "Vault", "Passphrases do not match.")
                return
            try:
                self.storage.configure_vault(passphrase)
            except ValueError as exc:
                QMessageBox.warning(self, "Vault", str(exc))
                return
            self.rebuild_tabs()
        elif not self.storage.vault.is_unlocked:
            passphrase, ok = QInputDialog.getText(
                self, "Unlock vault", "Passphrase", QLineEdit.EchoMode.Password
            )
            if not ok:
                return
            try:
                self.storage.unlock_vault(passphrase)
            except (InvalidPassphraseError, ValueError) as exc:
                QMessageBox.warning(self, "Vault", str(exc))
                return
        self.storage.move_to_vault(entry_id)
        self.refresh()

    def _open_config(self) -> None:
        self._config_dialog = self.config_factory(self)
        self._config_dialog.sections_changed.connect(self._config_updated)
        self._config_dialog.settings_changed.connect(self._config_updated)
        self._config_dialog.show()

    def _config_updated(self) -> None:
        self.rebuild_tabs()
        self.refresh()
