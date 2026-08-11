APP_STYLE = """
QWidget {
    background: transparent;
    color: #E8DFF0;
    font-family: "Segoe UI";
    font-size: 12px;
}
QDialog, QMainWindow, QWidget#Panel {
    background: #0B0710;
    border: 1px solid #8A2BE2;
    border-radius: 3px;
}
QFrame#TitleBar {
    background: #0E0814;
    border-bottom: 1px solid #321A42;
}
QLabel#PanelTitle {
    color: #DDB8F5;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox, QListWidget {
    background: #100817;
    border: 1px solid #452258;
    border-radius: 3px;
    padding: 7px;
    selection-background-color: #7130A0;
    font-family: "Cascadia Mono", "Consolas";
}
QLineEdit#SearchInput {
    min-height: 24px;
    padding: 7px 10px;
    border-color: #71389A;
    font-size: 13px;
}
QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus {
    border: 1px solid #E040FB;
}
QPushButton, QToolButton {
    background: #100817;
    border: 1px solid #653184;
    border-radius: 3px;
    padding: 6px 10px;
    color: #CDBAD8;
    font-size: 10px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover {
    background: #1A0C25;
    border-color: #E040FB;
    color: #FFFFFF;
}
QPushButton:pressed, QToolButton:pressed {
    background: #281036;
    border-color: #F08BFF;
}
QPushButton:disabled, QToolButton:disabled {
    color: #5F5365;
    border-color: #302038;
    background: #0C080F;
}
QPushButton#PrimaryButton {
    border-color: #B24BF3;
    color: #F1D9FF;
}
QPushButton#ToggleButton {
    text-align: left;
    padding: 7px 10px;
}
QPushButton#ToggleButton:checked {
    background: #24102F;
    border-color: #E040FB;
    color: #F4CDFF;
}
QPushButton#DangerButton {
    border-color: #753052;
    color: #E59ABF;
}
QPushButton#DangerButton:hover {
    border-color: #FF5FA2;
    color: #FFD3E8;
}
QToolButton#HeaderButton {
    min-height: 26px;
    padding: 6px 11px;
}
QToolButton#WindowControl {
    min-width: 24px;
    max-width: 24px;
    min-height: 22px;
    padding: 1px;
    border-color: #4B285C;
}
QToolButton#WindowControl:hover {
    border-color: #FF5FA2;
    color: #FFD3E8;
}
QToolButton#RowAction {
    min-height: 21px;
    padding: 2px 6px;
    background: transparent;
    border-color: #4C285F;
    color: #AA91B8;
    font-size: 9px;
}
QToolButton#RowAction:hover {
    background: #21102D;
    border-color: #CF5FFF;
    color: #FFFFFF;
}
QLabel#ModeBadge, QLabel#Tag {
    background: #160B20;
    border: 1px solid #63307E;
    border-radius: 3px;
    color: #B998C9;
    font-family: "Cascadia Mono", "Consolas";
    font-size: 9px;
    font-weight: 700;
    padding: 3px 7px;
}
QLabel#ModeBadge[semantic="true"] {
    background: #24102F;
    border-color: #E040FB;
    color: #F4CDFF;
}
QTabWidget::pane {
    background: #0B0710;
    border: 1px solid #321A42;
}
QTabBar::tab {
    background: transparent;
    color: #8F7A9B;
    border: none;
    border-bottom: 1px solid #3D204C;
    padding: 7px 11px;
    font-size: 10px;
}
QTabBar::tab:hover { color: #DFC5EC; }
QTabBar::tab:selected {
    color: #F0D8FF;
    border-bottom: 2px solid #B24BF3;
}
QListWidget#EntryList {
    background: #09050D;
    border: 1px solid #372044;
    padding: 4px;
    outline: none;
}
QListWidget#EntryList::item {
    background: transparent;
    border: 1px solid transparent;
    border-bottom-color: #25142D;
    border-radius: 3px;
    margin: 1px 2px;
    padding: 0;
}
QListWidget#EntryList::item:hover {
    background: #100817;
    border-color: #3C214A;
}
QListWidget#EntryList::item:selected {
    background: #1B0C26;
    border-color: #A445D7;
}
QWidget#EntryRow { background: transparent; border: none; }
QLabel#EntryText {
    background: transparent;
    color: #E8E0EC;
    border: none;
    font-family: "Cascadia Mono", "Consolas";
    font-size: 12px;
    font-weight: 500;
}
QLabel#Secondary {
    background: transparent;
    color: #84738E;
    border: none;
    font-size: 9px;
}
QLabel#ResizeHint {
    color: #6F5D79;
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 1px;
}
QTextBrowser#DiffBrowser {
    background: #09050D;
    border: 1px solid #5B2B73;
    padding: 0;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #653184;
    background: #100817;
}
QCheckBox::indicator:checked {
    background: #8A2BE2;
    border-color: #D966FF;
}
QScrollBar:vertical {
    background: #09050D;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #5C2A75;
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSizeGrip {
    width: 16px;
    height: 16px;
    background: #160B20;
    border: 1px solid #653184;
    border-radius: 2px;
}
QSizeGrip:hover {
    background: #281036;
    border-color: #E040FB;
}
"""
