APP_STYLE = """
QWidget {
    background: #0B0710;
    color: #E8DFF0;
    font-family: "Segoe UI";
    font-size: 12px;
}
QDialog, QMainWindow, #Panel {
    border: 1px solid #8A2BE2;
    border-radius: 3px;
}
QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox, QListWidget {
    background: #120A1C;
    border: 1px solid #4A2860;
    border-radius: 2px;
    padding: 7px;
    selection-background-color: #8A2BE2;
    font-family: "Cascadia Mono", "Consolas";
}
QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus {
    border: 1px solid #E040FB;
}
QPushButton, QToolButton {
    background: transparent;
    border: 1px solid #6D348F;
    border-radius: 2px;
    padding: 6px 10px;
}
QPushButton:hover, QToolButton:hover {
    border-color: #E040FB;
    color: #FFFFFF;
}
QPushButton:disabled, QToolButton:disabled { color: #615568; border-color: #34233D; }
QTabBar::tab {
    background: transparent;
    color: #9C8AA6;
    border-bottom: 1px solid #4A2860;
    padding: 8px 12px;
}
QTabBar::tab:selected { color: #F0D8FF; border-bottom: 2px solid #B24BF3; }
QListWidget::item { border-bottom: 1px solid #2B1935; padding: 2px; }
QListWidget::item:selected { background: rgba(138, 43, 226, 50); border: 1px solid #B24BF3; }
QLabel#Secondary { color: #9C8AA6; }
QLabel#Mono { font-family: "Cascadia Mono", "Consolas"; }
QScrollBar:vertical { background: #0B0710; width: 8px; }
QScrollBar::handle:vertical { background: #6D348F; min-height: 24px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #6D348F; }
QCheckBox::indicator:checked { background: #8A2BE2; }
"""
