"""暖纸陶浅色主题（参考 Claude 设计语言：暖米色纸感 + 珊瑚陶土色）。"""

BG = "#faf9f5"
CARD = "#f0ebe2"
LIST_BG = "#f5f1e9"
INPUT_BG = "#ffffff"
BORDER = "#e0d8ca"
BORDER_SOFT = "#e9e2d5"
BTN_BORDER = "#d8cfc0"
TEXT = "#141413"
SUBTLE = "#6c6a64"
SUBTLE_SOFT = "#8e8b82"
ACCENT = "#cc785c"
ACCENT_DEEP = "#a9583e"
DANGER = "#c64545"
OK = "#5db872"
WARN = "#d4a017"
BAR_BG = "#e6dfd4"

APP_QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QWidget {{
    background: {BG};
    color: {TEXT};
}}
QLabel#appTitle {{
    font-size: 19px;
    font-weight: 600;
    letter-spacing: 0.3px;
    color: {TEXT};
}}
QLabel#sectionTitle {{
    font-weight: 600;
    color: {TEXT};
}}
QLabel#subtle {{
    color: {SUBTLE};
}}
QLabel#statusLabel {{
    color: {SUBTLE};
}}
QLabel#statusLabel[state="done"] {{
    color: {OK};
}}
QLabel#statusLabel[state="failed"] {{
    color: {DANGER};
}}
QLabel#statusLabel[state="cancelled"] {{
    color: {WARN};
}}
QLabel#dropZone {{
    background: #f5f0e8;
    border: 2px dashed {BTN_BORDER};
    border-radius: 12px;
    color: {SUBTLE};
    font-size: 14px;
}}
QLabel#dropZone[hover="true"] {{
    border-color: {ACCENT};
    color: {ACCENT_DEEP};
}}
QFrame#brandMark {{
    background: {ACCENT};
    border-radius: 4px;
}}
QFrame#separator {{
    background: {BORDER_SOFT};
    border: none;
}}
QWidget#taskRow {{
    background: {CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
}}
QPushButton {{
    background: {BG};
    border: 1px solid {BTN_BORDER};
    border-radius: 6px;
    padding: 6px 16px;
    color: {TEXT};
}}
QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT_DEEP};
}}
QPushButton:pressed {{
    background: {CARD};
}}
QPushButton:disabled {{
    color: {SUBTLE_SOFT};
    border-color: {BORDER_SOFT};
}}
QLineEdit {{
    background: {INPUT_BG};
    border: 1px solid {BTN_BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {INPUT_BG};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QCheckBox {{
    color: {TEXT};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BTN_BORDER};
    border-radius: 4px;
    background: {INPUT_BG};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QComboBox {{
    background: {INPUT_BG};
    border: 1px solid {BTN_BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    color: {TEXT};
}}
QComboBox:hover {{
    border-color: {ACCENT};
}}
QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {SUBTLE};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {INPUT_BG};
    border: 1px solid {BTN_BORDER};
    border-radius: 4px;
    selection-background-color: {CARD};
    selection-color: {TEXT};
    outline: none;
}}
QListWidget {{
    background: {LIST_BG};
    border: 1px solid {BORDER_SOFT};
    border-radius: 10px;
    outline: none;
    padding: 4px;
}}
QListWidget::item {{
    border-radius: 8px;
    margin: 2px;
}}
QListWidget::item:selected {{
    background: {BORDER_SOFT};
}}
QProgressBar {{
    background: {BAR_BG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    text-align: center;
    color: {SUBTLE};
}}
QProgressBar::chunk {{
    border-radius: 4px;
    background: {ACCENT};
}}
QProgressBar[failed="true"]::chunk {{
    background: {DANGER};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BTN_BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {SUBTLE_SOFT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QToolTip {{
    background: {INPUT_BG};
    color: {TEXT};
    border: 1px solid {BTN_BORDER};
    border-radius: 4px;
    padding: 4px;
}}
QMessageBox {{
    background: {INPUT_BG};
}}
QMessageBox QLabel {{
    background: transparent;
}}
"""
