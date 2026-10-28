"""Single visual theme for every window: colour tokens and the shared Qt stylesheet.

gui.py adds the pedal-panel rules on top; dialogs only set objectNames (card, primary,
secondary, chip, seg, …) and never their own colours.
"""
from __future__ import annotations

BG = "#15191d"          # window background
SURFACE = "#1d2228"     # cards, toolbars
SURFACE_2 = "#262d35"   # buttons, chips
FIELD = "#10161a"       # inputs, tables
BORDER = "#2a323b"
BORDER_2 = "#333c46"
TEXT = "#e6e6e6"
TEXT_DIM = "#8a96a3"
TEXT_MUTED = "#6b7480"
ACCENT = "#1f9e6e"      # primary action
ACCENT_HOVER = "#23b37d"
TEAL = "#1f6f6d"        # selection / checked
LINK = "#5dd3ff"
OK = "#5dff9e"
WARN = "#ffd36b"
ERROR = "#ff7d8f"

QSS = f"""
QMainWindow, QDialog, QWidget#root, QWidget#body {{ background: {BG}; color: {TEXT}; }}
QLabel {{ color: {TEXT}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_2}; padding: 4px 6px; }}

/* toolbar, status bar, menus */
QToolBar {{ background: {SURFACE}; border: none; padding: 4px; spacing: 4px; }}
QToolBar QToolButton {{ color: {TEXT}; padding: 6px 10px; border-radius: 6px; }}
QToolBar QToolButton:hover {{ background: #2a3139; }}
QToolBar QToolButton:checked {{ background: {TEAL}; }}
QToolBar QToolButton:disabled {{ color: {TEXT_MUTED}; }}
QToolBar#main {{ padding: 6px 10px; spacing: 6px; border-bottom: 1px solid {BORDER}; }}
QToolBar#main QToolButton {{ padding: 7px 14px; font-weight: bold; }}
QToolBar QToolButton#toolPrimary {{ background: {ACCENT}; color: white; }}
QToolBar QToolButton#toolPrimary:hover {{ background: {ACCENT_HOVER}; }}
QToolBar QToolButton#toolPrimary:disabled {{ background: {SURFACE_2}; color: {TEXT_MUTED}; }}
QToolBar QToolButton#toolAccent {{ border: 1px solid {ACCENT}; color: #bff5dd; }}
QToolBar QToolButton#toolAccent:hover {{ background: #16332b; }}
QStatusBar {{ background: {SURFACE}; color: #aab; }}
QMenuBar {{ background: {SURFACE}; color: {TEXT}; }}
QMenuBar::item:selected {{ background: #2a3139; }}
QMenu {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_2}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {TEAL}; }}
QMenu::separator {{ height: 1px; background: {BORDER_2}; margin: 4px 8px; }}

/* dialog header and cards */
QLabel#dlgTitle {{ font-size: 21px; font-weight: bold; color: #ffffff; }}
QLabel#dlgSub {{ color: {TEXT_DIM}; }}
QLabel#target {{ background: #1f3b46; color: #9fe8ff; border-radius: 10px; padding: 4px 12px; font-weight: bold; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QLabel#cardTitle {{ color: #ffffff; font-weight: bold; font-size: 14px; }}
QLabel#step {{ background: {ACCENT}; color: white; border-radius: 11px; font-weight: bold;
              min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }}
QLabel#hint {{ color: {TEXT_DIM}; font-size: 12px; }}

/* inputs */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {FIELD}; color: #f0f0f0; border: 1px solid {BORDER_2}; border-radius: 8px; padding: 6px;
    selection-background-color: {TEAL};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QPlainTextEdit#log {{ font-family: monospace; font-size: 12px; }}
QComboBox {{ background: {FIELD}; color: #f0f0f0; border: 1px solid {BORDER_2}; border-radius: 8px; padding: 5px 8px; }}
QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {FIELD}; color: #f0f0f0; selection-background-color: {TEAL};
                               border: 1px solid {BORDER_2}; }}
QCheckBox, QRadioButton {{ color: #c8d0d8; spacing: 8px; }}

/* buttons */
QPushButton {{ background: {SURFACE_2}; color: {TEXT}; border: none; border-radius: 8px; padding: 8px 16px; }}
QPushButton:hover {{ background: #2f3842; }}
QPushButton:disabled {{ background: #22282f; color: {TEXT_MUTED}; }}
QPushButton#primary, QPushButton#bigPrimary {{
    background: {ACCENT}; color: white; font-weight: bold; padding: 9px 18px;
}}
QPushButton#bigPrimary {{ font-size: 14px; padding: 11px 18px; }}
QPushButton#primary:hover, QPushButton#bigPrimary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled, QPushButton#bigPrimary:disabled {{ background: #2a3139; color: {TEXT_MUTED}; }}
QPushButton#secondary, QPushButton#action {{ background: #2a3139; color: {TEXT}; padding: 8px 16px; }}
QPushButton#secondary:hover, QPushButton#action:hover {{ background: #343d47; }}
QPushButton#link {{ background: transparent; color: {LINK}; padding: 2px; text-decoration: underline; }}
QPushButton#chip {{ background: {SURFACE_2}; color: #cfd6dd; border: 1px solid {BORDER_2}; border-radius: 13px;
                    padding: 4px 12px; }}
QPushButton#chip:hover {{ background: #2f3842; color: #ffffff; border-color: {ACCENT}; }}
QPushButton#seg {{ background: #1a1f25; color: #cfd6dd; border: 1px solid {BORDER_2}; border-radius: 0;
                   padding: 7px 18px; font-weight: bold; }}
QPushButton#seg:checked {{ background: {TEAL}; color: white; border-color: {ACCENT}; }}
QToolButton#modeCard {{ background: #1a1f25; color: #cfd6dd; border: 2px solid {BORDER}; border-radius: 12px;
                        padding: 10px; font-size: 13px; }}
QToolButton#modeCard:hover {{ border-color: #3a4a58; }}
QToolButton#modeCard:checked {{ background: #16332b; border-color: {ACCENT}; color: #ffffff; }}

/* tables */
QTableWidget, QTableView {{ background: {FIELD}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px;
                            gridline-color: {BORDER}; selection-background-color: {TEAL};
                            alternate-background-color: #141b20; }}
QHeaderView::section {{ background: {SURFACE_2}; color: #c8d0d8; border: none; padding: 6px; font-weight: bold; }}

/* result panels */
QFrame#result {{ background: {FIELD}; border: 1px dashed {BORDER_2}; border-radius: 10px; }}
QLabel#resName {{ font-size: 18px; font-weight: bold; color: #ffffff; }}
QLabel#resText {{ color: #c8d0d8; }}
QLabel#module {{ background: {SURFACE}; border-radius: 8px; padding: 6px 10px; color: {TEXT}; }}
QLabel#status_ok {{ color: {OK}; }}
QLabel#status_err {{ color: {ERROR}; }}

/* lists */
QListWidget {{ background: {FIELD}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 4px; }}
QListWidget::item:disabled {{ color: {TEXT_DIM}; font-weight: bold; }}
QListWidget::item:selected {{ background: {TEAL}; color: white; }}

/* progress bars */
QProgressBar {{ background: {FIELD}; border: 1px solid {BORDER_2}; border-radius: 6px; max-height: 12px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

/* scroll bars */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a4450; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a5663; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #3a4450; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* message boxes and input dialogs */
/* command menu (dialogs.CommandMenu): a panel over the editor with a shade, search, quick tiles, groups */
QWidget#menuShade {{ background: rgba(0, 0, 0, 115); }}
QFrame#menuPanel {{ background: {BG}; border-right: 1px solid {BORDER_2}; }}
QWidget#menuInner {{ background: {BG}; }}
QLabel#menuKey {{ color: {TEXT_MUTED}; font-size: 11px; }}
QLineEdit#menuSearch {{ font-size: 15px; padding: 10px 12px; border-radius: 10px; }}
QToolButton#quickTile {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 12px;
    padding: 10px 6px; font-weight: bold; }}
QToolButton#quickTile:hover {{ border-color: {ACCENT}; }}
QToolButton#quickTile:checked {{ background: #12402c; border-color: {ACCENT}; }}
QToolButton#quickTile:disabled {{ color: {TEXT_MUTED}; }}
QLabel#menuGroup {{ color: {TEXT_DIM}; font-size: 11px; font-weight: bold; letter-spacing: 1px; }}
QPushButton#menuItem {{ background: transparent; border: none; border-top: 1px solid {BORDER}; border-radius: 0;
    text-align: left; padding: 0; }}
QPushButton#menuItem:hover {{ background: #232a31; }}
QPushButton#menuItem:focus {{ background: #232a31; outline: none; }}
QLabel#menuTitle {{ font-weight: bold; }}
QLabel#menuDesc {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#menuTitle:disabled, QLabel#menuDesc:disabled {{ color: {TEXT_MUTED}; }}
QLabel#menuState {{ color: {TEXT_MUTED}; font-size: 11px; font-weight: bold; border: 1px solid {BORDER_2};
    border-radius: 9px; padding: 1px 8px; }}
QLabel#menuState[on="true"] {{ color: {OK}; border-color: {ACCENT}; }}

QMessageBox, QInputDialog {{ background: {SURFACE}; }}
QMessageBox QLabel, QInputDialog QLabel {{ color: {TEXT}; }}
QMessageBox QPushButton, QInputDialog QPushButton, QDialogButtonBox QPushButton {{ min-width: 84px; }}
QColorDialog {{ background: {SURFACE}; }}
"""
