"""Secondary windows. All share StyledDialog: header (title + subtitle + optional badge),
numbered cards in the body and a footer with secondary/primary buttons; colours come from
theme.QSS through objectNames only."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QByteArray, QEasingCurve, QObject, QPoint, QPropertyAnimation, QRect, QRectF, QRunnable, QSize,
                            Qt, QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGraphicsOpacityEffect,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QVBoxLayout,
    QWidget,
)

from . import ai, artists, chatapps, device, library, menu, pack, setlist
from .model import AMP_MODELS, CAB_MODELS, FIELD_BY_KEY, FIELDS, OFF_COLOR, REC_LEN, SLOTS, Bank, slot_name, zone_of
from .theme import ACCENT_HOVER, BORDER_2, ERROR, FIELD, OK, SURFACE_2, TEAL, TEXT, TEXT_DIM, WARN

BYTE_NAMES = {f.offset: f.label for f in FIELDS}
BYTE_NAMES.update({OFF_COLOR: "LED rojo", OFF_COLOR + 1: "LED verde", OFF_COLOR + 2: "LED azul"})
_NAME_RE = re.compile(r"bank-(\d{8})-(\d{6})-(.+)\.tgbank$")


def byte_name(offset: int) -> str:
    return BYTE_NAMES.get(offset, f"byte {offset}")


class StyledDialog(QDialog):
    """Common frame for every secondary window."""

    def __init__(self, main, title: str, subtitle: str, width: int = 760, height: int = 560,
                 scroll: bool = False):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(title.lstrip("✨ ").strip())
        screen = self.screen().availableGeometry() if self.screen() else None
        self.resize(width, min(height, screen.height() - 60) if screen else height)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QWidget()
        body.setObjectName("body")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(20, 18, 20, 8)
        self.body.setSpacing(12)
        self.scroll = None
        if scroll:
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QFrame.NoFrame)
            self.scroll.setWidget(body)
            outer.addWidget(self.scroll, 1)
        else:
            outer.addWidget(body, 1)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("dlgTitle")
        sub = QLabel(subtitle)
        sub.setObjectName("dlgSub")
        sub.setWordWrap(True)
        titles.addWidget(t)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        self._head = head
        self.body.addLayout(head)
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 8, 20, 16)
        self.footer_left = QHBoxLayout()
        self.footer_right = QHBoxLayout()
        foot.addLayout(self.footer_left)
        foot.addStretch()
        foot.addLayout(self.footer_right)
        outer.addLayout(foot)

    def header_badge(self, text: str = "") -> QLabel:
        badge = QLabel(text)
        badge.setObjectName("target")
        self._head.addWidget(badge, 0, Qt.AlignTop)
        return badge

    def card(self, number: str, title: str, stretch: int = 0) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        if number:
            n = QLabel(number)
            n.setObjectName("step")
            n.setAlignment(Qt.AlignCenter)
            head.addWidget(n)
        t = QLabel(title)
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)
        self.body.addWidget(card, stretch)
        return card, lay

    @staticmethod
    def mode_card(text: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("modeCard")
        b.setText(text)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        b.setMinimumHeight(58)
        return b

    @staticmethod
    def segmented(labels: list[str], parent) -> tuple[QHBoxLayout, list[QPushButton]]:
        row = QHBoxLayout()
        row.setSpacing(0)
        group = QButtonGroup(parent)
        buttons = []
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            radius = []
            if i == 0:
                radius.append("border-top-left-radius: 8px; border-bottom-left-radius: 8px;")
            if i == len(labels) - 1:
                radius.append("border-top-right-radius: 8px; border-bottom-right-radius: 8px;")
            if radius:
                b.setStyleSheet("QPushButton#seg { " + " ".join(radius) + " }")
            group.addButton(b)
            row.addWidget(b)
            buttons.append(b)
        row.addStretch()
        return row, buttons

    def button(self, text: str, slot, role: str = "secondary", left: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(role)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        (self.footer_left if left else self.footer_right).addWidget(b)
        return b

    @staticmethod
    def status(label: QLabel, text: str, ok: bool | None = None) -> None:
        color = OK if ok else ERROR if ok is False else TEXT_DIM
        mark = "✓  " if ok else "✗  " if ok is False else ""
        label.setText(f'<span style="color:{color}">{mark}{text}</span>')


def ask(parent, title: str, text: str) -> bool:
    """Yes/No question with the app's button texts."""
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Question, title, text, parent=parent)
    yes = box.addButton("Sí", QMessageBox.AcceptRole)
    no = box.addButton("Cancelar", QMessageBox.RejectRole)
    for button, role in ((yes, "primary"), (no, "secondary")):
        button.setObjectName(role)
        button.style().unpolish(button)   # objectName changed after creation: re-apply the stylesheet
        button.style().polish(button)
    box.setDefaultButton(yes)
    box.exec()
    return box.clickedButton() is yes


def choose(parent, title: str, text: str, first: str, second: str) -> bool:
    """Two-way question with named answers (no cancel); True = `first`."""
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Question, title, text, parent=parent)
    a = box.addButton(first, QMessageBox.AcceptRole)
    b = box.addButton(second, QMessageBox.RejectRole)
    for button, role in ((a, "primary"), (b, "secondary")):
        button.setObjectName(role)
        button.style().unpolish(button)
        button.style().polish(button)
    box.setDefaultButton(a)
    box.exec()
    return box.clickedButton() is a


def menu_icon(name: str, color: str = "#8fe0be", size: int = 20) -> QPixmap:
    """A line icon of menu.ICONS drawn in `color` (sharp on high-DPI screens)."""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{menu.ICONS[name]}</svg>')
    scale = 3
    pix = QPixmap(size * scale, size * scale)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pix.setDevicePixelRatio(scale)
    return pix


class CommandMenu(QWidget):
    """Every command of the app, searchable, like the APK menu (same groups, texts and icons from
    tankg/menu.py): a panel that slides in from the left over the editor, below the toolbar, with a
    shade over the rest. Quick actions on top, then the groups; type to filter, Enter runs the first
    match, Esc or a click outside closes it. Commands that can't run now are dimmed
    (MainWindow.command_state) and show their keyboard shortcut (MainWindow.command_shortcuts)."""

    WIDTH = 460

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setObjectName("menuShade")
        self.setAttribute(Qt.WA_StyledBackground)
        self.panel = QFrame(self)
        self.panel.setObjectName("menuPanel")
        outer = QVBoxLayout(self.panel)
        outer.setContentsMargins(16, 14, 12, 12)
        outer.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("Menú")
        title.setObjectName("dlgTitle")
        close = QPushButton("✕")
        close.setObjectName("secondary")
        close.setToolTip("Cerrar (Esc)")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close_menu)
        head.addWidget(title, 1)
        head.addWidget(close)
        outer.addLayout(head)
        self.search = QLineEdit()
        self.search.setObjectName("menuSearch")
        self.search.setPlaceholderText("Buscar: guardar, nube, fábrica, AMP…")
        self.search.addAction(QIcon(menu_icon("search", "#8a96a3")), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_first)
        outer.addWidget(self.search)
        state, keys = main.command_state(), main.command_shortcuts()
        labels = {cmd: (label, icon) for _, cmd, label, _, icon, _ in menu.items()}
        self.quick = QWidget()
        grid = QGridLayout(self.quick)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        for n, cmd in enumerate(menu.QUICK):
            b = QToolButton()
            b.setObjectName("quickTile")
            b.setText(menu.QUICK_LABEL[cmd])
            b.setIcon(QIcon(menu_icon(labels[cmd][1], size=24)))
            b.setIconSize(QSize(24, 24))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumHeight(66)
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(bool(state.get(cmd, True)))
            if cmd == "live":
                b.setCheckable(True)
                b.setChecked(main.live_action.isChecked())
            b.clicked.connect(lambda _=False, c=cmd: self._run(c))
            grid.addWidget(b, n // 3, n % 3)
        outer.addWidget(self.quick)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("menuInner")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(6)
        self.groups: list[tuple[QWidget, list]] = []
        self.rows: list[tuple[QPushButton, str, str]] = []
        for title_text, icon, _ in menu.MENU:
            entries = [i for i in menu.items() if i[0] == title_text]
            if not entries:
                continue
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 8, 0, 0)
            v.setSpacing(6)
            group_head = QHBoxLayout()
            pic = QLabel()
            pic.setPixmap(menu_icon(icon, "#8a96a3", 15))
            name = QLabel(title_text.upper())
            name.setObjectName("menuGroup")
            group_head.addWidget(pic)
            group_head.addWidget(name, 1)
            v.addLayout(group_head)
            card = QFrame()
            card.setObjectName("card")
            c = QVBoxLayout(card)
            c.setContentsMargins(0, 0, 0, 0)
            c.setSpacing(0)
            rows = []
            for _, cmd, label, desc, ic, find in entries:
                row = self._row(cmd, label, desc, ic, bool(state.get(cmd, True)),
                                cmd == "live" and main.live_action.isChecked(), keys.get(cmd, ""))
                row.setProperty("find", find)
                row.setProperty("available", not (cmd in state and state[cmd] is None))   # None: doesn't apply now
                row.setHidden(not row.property("available"))
                c.addWidget(row)
                rows.append(row)
                self.rows.append((row, cmd, find))
            v.addWidget(card)
            lay.addWidget(box)
            self.groups.append((box, rows))
        self.empty = QLabel("Nada coincide. Prueba con otra palabra.")
        self.empty.setObjectName("hint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()
        lay.addWidget(self.empty)
        lay.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.place()
        self.show()
        self.raise_()
        self._slide()
        self.search.setFocus()

    def place(self) -> None:
        """Cover the window between the toolbar and the status bar; the panel on the left."""
        bars = [w for w in self.main.findChildren(QToolBar) if w.isVisible()]
        top = max((b.geometry().bottom() + 1 for b in bars), default=0)
        bottom = self.main.statusBar().geometry().top() if self.main.statusBar().isVisible() else self.main.height()
        self.setGeometry(0, top, self.main.width(), max(0, bottom - top))
        self.panel.setGeometry(0, 0, min(self.WIDTH, self.width() - 40), self.height())

    def _slide(self) -> None:
        anim = QPropertyAnimation(self.panel, b"pos", self)
        anim.setDuration(160)
        anim.setStartValue(QPoint(-self.panel.width(), 0))
        anim.setEndValue(QPoint(0, 0))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self.panel.geometry().contains(event.position().toPoint()):   # click on the shade
            self.close_menu()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key_Escape:
            self.close_menu()
        else:
            super().keyPressEvent(event)

    def close_menu(self) -> None:
        if self.main.command_menu is self:
            self.main.command_menu = None
        self.hide()
        self.deleteLater()

    def _row(self, cmd: str, label: str, desc: str, icon: str, enabled: bool, on: bool, key: str = "") -> QPushButton:
        b = QPushButton()
        b.setObjectName("menuItem")
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(56)
        h = QHBoxLayout(b)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(14)
        pic = QLabel()
        pic.setPixmap(menu_icon(icon))
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(label)
        title.setObjectName("menuTitle")
        sub = QLabel(desc)
        sub.setObjectName("menuDesc")
        text.addWidget(title)
        text.addWidget(sub)
        h.addWidget(pic)
        h.addLayout(text, 1)
        if key:
            k = QLabel(key)
            k.setObjectName("menuKey")
            k.setAttribute(Qt.WA_TransparentForMouseEvents)
            h.addWidget(k, 0, Qt.AlignVCenter)
        if cmd == "live":
            st = QLabel("ON" if on else "OFF")
            st.setObjectName("menuState")
            st.setProperty("on", on)
            h.addWidget(st, 0, Qt.AlignVCenter)
        for w in (pic, title, sub):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        b.setEnabled(enabled)
        if not enabled:
            pic.setPixmap(menu_icon(icon, "#4a5560"))
        b.clicked.connect(lambda: self._run(cmd))
        return b

    def _filter(self, text: str) -> None:
        q = text.strip()
        self.quick.setHidden(bool(q))
        shown_any = False
        for box, rows in self.groups:
            shown = 0
            for row in rows:
                visible = bool(row.property("available")) and menu.matches(q, row.property("find"))
                row.setVisible(visible)
                shown += visible
            box.setVisible(shown > 0)
            shown_any = shown_any or shown > 0
        self.empty.setVisible(not shown_any)

    def _run_first(self) -> None:
        for row, cmd, _ in self.rows:
            if not row.isHidden() and not row.parentWidget().parentWidget().isHidden() and row.isEnabled():
                self._run(cmd)
                return

    def _run(self, cmd: str) -> None:
        self.close_menu()
        QTimer.singleShot(0, lambda: self.main.run_command(cmd))


class CloudSignIn(StyledDialog):
    """Google sign-in with a code (device flow). The code can be entered on any device at
    google.com/device; opening the browser here is optional. The main window polls Google in the
    background and closes this window when access is allowed."""

    def __init__(self, main, code: dict):
        super().__init__(main, "Conectar con Google Drive",
                         "Tus presets y nombres se guardarán en tu Drive, en la carpeta «Tank-G Control Center».",
                         width=560, height=400)
        self.code = code
        _, lay = self.card("1", "Tu código")
        big = QLabel(code["user_code"])
        big.setObjectName("dlgTitle")
        big.setStyleSheet("font-size: 34px; letter-spacing: 4px;")
        big.setAlignment(Qt.AlignCenter)
        big.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(big)
        _, lay = self.card("2", "Ingrésalo en Google desde cualquier dispositivo")
        hint = QLabel(f"En el teléfono, la tablet o este equipo abre <b>{code['url'].replace('https://', '')}</b>, "
                      "escribe el código, elige tu cuenta y pulsa «Permitir». Esta ventana se cerrará sola.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.body.addStretch()
        self.button("Cancelar", self.reject)
        self.button("Copiar código", self.copy)
        self.button("Abrir Google en este equipo", self.open_google, "primary")
        self.copy()

    def copy(self) -> None:
        QApplication.clipboard().setText(self.code["user_code"])

    def open_google(self) -> None:
        QDesktopServices.openUrl(QUrl(self.code["url"]))


class UploadDialog(StyledDialog):
    """Progress of a write to the pedal: one row per preset, a bar and the current step.
    Closes by itself a moment after a verified write; stays open on errors."""

    def __init__(self, main, slots: list[int], names: list[str]):
        super().__init__(main, "Subiendo a la pedalera",
                         "Se guarda cada preset, se confirma y se relee la pedalera para verificar.", 520, 200)
        self.setModal(True)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.running = True   # Esc / window close are ignored until the job reports back
        self.slots = slots
        self.done_count = 0
        self.badge = self.header_badge(f"0 de {len(slots)}")
        _, lay = self.card("", "Progreso")
        self.bar = QProgressBar()
        self.bar.setRange(0, len(slots) + 1)   # +1: read-back verification
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.step = QLabel()
        lay.addWidget(self.step)
        self.rows: list[QLabel] = []
        for slot, name in zip(slots, names):
            row = QLabel()
            row.setObjectName("hint")
            row.setProperty("text_", f"{slot_name(slot)} {name}".rstrip())
            lay.addWidget(row)
            self.rows.append(row)
        self._mark(0)
        self.status(self.step, "Conectando con la pedalera…")
        self.close_btn = self.button("Cerrar", self.accept)
        self.close_btn.setEnabled(False)
        self.adjustSize()

    def _mark(self, done: int, failed: bool = False) -> None:
        for i, row in enumerate(self.rows):
            text = row.property("text_")
            if i < done:
                row.setText(f'<span style="color:{OK}">✓</span>  {text}')
            elif i == done:
                row.setText(f'<span style="color:{ERROR if failed else TEXT}">{"✗" if failed else "●"}</span>  '
                            f'<b>{text}</b>')
            else:
                row.setText(f"○  {text}")

    def progress(self, text: str, n: int, total: int) -> None:
        if n < 0:
            self.status(self.step, text)
            return
        self.done_count = n
        self.bar.setValue(n)
        self.badge.setText(f"{min(n + 1, total)} de {total}" if n < total else f"{total} de {total}")
        self._mark(n)
        self.status(self.step, text)

    def reject(self) -> None:
        if not self.running:
            super().reject()

    def finished(self, text: str) -> None:
        self.running = False
        self.bar.setValue(self.bar.maximum())
        self.badge.setText(f"{len(self.slots)} de {len(self.slots)}")
        self._mark(len(self.slots))
        self.status(self.step, text, True)
        self.close_btn.setEnabled(True)
        self.close_btn.setObjectName("primary")
        self.close_btn.style().unpolish(self.close_btn)
        self.close_btn.style().polish(self.close_btn)
        timer = QTimer(self)   # child timer: dies with the dialog if the user closes it first
        timer.setSingleShot(True)
        timer.timeout.connect(self.accept)
        timer.start(1500)

    def failed(self, text: str) -> None:
        self.running = False
        self._mark(self.done_count, failed=True)
        self.status(self.step, text, False)
        self.step.setWordWrap(True)
        self.close_btn.setEnabled(True)
        self.adjustSize()


class _ModelJobDialog(StyledDialog):
    """Progress, close and error handling shared by the AMP/CAB dialogs: the window can't be closed
    while the job runs; after an error the inputs in `self.inputs` are enabled again."""

    inputs: list = []

    def progress(self, text: str, n: int, total: int) -> None:
        if n >= 0:
            self.bar.setRange(0, total)
            self.bar.setValue(n)
        self.status(self.step, text)

    def reject(self) -> None:
        if not self.running:
            super().reject()

    def finished(self, text: str) -> None:
        self.running = False
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.status(self.step, text, True)
        self.go.hide()
        self.close_btn.setText("Cerrar")
        self.close_btn.setEnabled(True)

    def failed(self, text: str) -> None:
        self.running = False
        self.status(self.step, text, False)
        for w in (self.go, self.close_btn, *self.inputs):
            w.setEnabled(True)

    def _running(self, text: str) -> None:
        self.running = True
        for w in (self.go, self.close_btn, *self.inputs):
            w.setEnabled(False)
        self.status(self.step, text)


class AmpUploadDialog(_ModelJobDialog):
    """Replace one of the 9 AMP models of the pedal with an .am4data file (Bluetooth only)."""

    def __init__(self, main, data: bytes, name: str, slot: int | None = None, source: dict | None = None):
        self.source = source
        super().__init__(main, "Subir modelo de AMP",
                         "Reemplaza uno de los 9 modelos de AMP (perilla TYPE) por un archivo .am4data de M-EFCS. "
                         "Se envía por Bluetooth, igual que la app oficial.", 560, 360)
        self.data = data
        self.running = False
        _, lay = self.card("1", "Modelo")
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("Nombre que mostrará la app")
        lay.addWidget(self.name)
        _, lay = self.card("2", "Espacio de AMP que se reemplaza")
        self.slot = QComboBox()
        self.slot.addItems([main.amp_label(i) for i in range(len(AMP_MODELS))])
        current = main.local.presets[main.current].amp if main.local else 0
        self.slot.setCurrentIndex(current if slot is None else slot)
        lay.addWidget(self.slot)
        note = QLabel("Todos los presets que usan ese TYPE sonarán con el modelo nuevo. Para volver al original: "
                      "☰ Menú → Restaurar AMP/CAB de fábrica.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        _, lay = self.card("", "Progreso")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        lay.addWidget(self.bar)
        self.step = QLabel()
        self.step.setWordWrap(True)
        lay.addWidget(self.step)
        self.status(self.step, "Requiere la pedalera encendida con Bluetooth y libre (sin la app del teléfono).")
        self.close_btn = self.button("Cancelar", self.reject)
        self.go = self.button("Subir a la pedalera", self._start, "primary")
        self.inputs = [self.slot, self.name]

    def _start(self) -> None:
        slot = self.slot.currentIndex()
        if not ask(self, "Subir modelo de AMP",
                   f"Se reemplazará el AMP {slot + 1} de la pedalera por «{self.name.text().strip() or 'el modelo'}»."
                   + self.main.replace_warning([slot]) + "\n¿Continuar?"):
            return
        if self.main.start_amp_upload(slot, self.data, self.name.text().strip() or f"AMP {slot + 1}", self, self.source):
            self._running("Conectando por Bluetooth…")


class PackImportDialog(_ModelJobDialog):
    """Import a .tgpack: shows what it brings, where each AMP model goes (the pack's slot by default;
    another one remaps the presets that use it) and where the presets go. With models, they and then
    the presets are written to the pedal (Bluetooth); without, the presets go to the editor."""

    def __init__(self, main, loaded):
        self.pack = loaded
        n = len(loaded.presets)
        what = {"preset": "1 preset", "bank": "un banco de 4 presets", "all": "los 36 presets"}.get(loaded.kind, f"{n} presets")
        amps = f" y {len(loaded.amps)} modelo{'s' if len(loaded.amps) > 1 else ''} de AMP" if loaded.amps else ""
        super().__init__(main, f"Importar pack{f' «{loaded.title}»' if loaded.title else ''}",
                         f"Trae {what}{amps}.", 600, 520)
        self.running = False
        _, lay = self.card("1", "Presets")
        names = [f"{slot_name(o)}  {name or p.amp_name}" for o, p, name in loaded.presets]
        listing = QLabel("\n".join(names[:8] + ([f"… y {n - 8} más"] if n > 8 else [])))
        listing.setObjectName("hint")
        lay.addWidget(listing)
        self.dest = QComboBox()
        if loaded.kind == "preset":
            self.dest.addItems([f"{slot_name(s)}  {main.aliases.preset(s)}".rstrip() for s in range(36)])
            self.dest.setCurrentIndex(main.current)
        elif loaded.kind == "bank":
            self.dest.addItems([f"Banco {b + 1}" + (f" · {main.aliases.bank(b)}" if main.aliases.bank(b) else "") for b in range(9)])
            self.dest.setCurrentIndex(loaded.presets[0][0] // 4)
        if self.dest.count():
            row = QHBoxLayout()
            row.addWidget(QLabel("Destino:"))
            row.addWidget(self.dest, 1)
            lay.addLayout(row)
        self.amp_slots: list[QComboBox] = []
        if loaded.amps:
            _, lay = self.card("2", "Modelos de AMP (perilla TYPE)")
            for amp in loaded.amps:
                row = QHBoxLayout()
                row.addWidget(QLabel(f"«{amp.name}» →"), 1)
                combo = QComboBox()
                combo.addItems([main.amp_label(i) for i in range(len(AMP_MODELS))])
                combo.setCurrentIndex(amp.slot)
                row.addWidget(combo)
                lay.addLayout(row)
                self.amp_slots.append(combo)
            credits = [f"• {amp.name}: {amp.credit_text()}" for amp in loaded.amps if amp.credit_text()]
            if credits:
                who = QLabel("Modelos de sus autores (comunidad de M-VAVE" + (", se descargan al importar" if any(
                    a.data is None for a in loaded.amps) else "") + "):\n" + "\n".join(credits))
                who.setObjectName("hint")
                who.setWordWrap(True)
                lay.addWidget(who)
            note = QLabel("Reemplaza ese TYPE en la pedalera; si eliges otro espacio, los presets del pack se ajustan solos. "
                          "Se suben los AMP y luego los presets, por Bluetooth (antes se hace un backup del banco).")
        else:
            note = QLabel("Se cargan en el editor: «Guardar cambios» los pasa a la pedalera.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        _, lay = self.card("", "Progreso")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        lay.addWidget(self.bar)
        self.step = QLabel()
        self.step.setWordWrap(True)
        lay.addWidget(self.step)
        self.close_btn = self.button("Cancelar", self.reject)
        self.go = self.button("Importar a la pedalera" if loaded.amps else "Cargar en el editor", self._start, "primary")
        self.inputs = [self.dest, *self.amp_slots]

    def destination(self) -> list[int]:
        """Slot of each preset of the pack (the chosen one, bank, or where they were)."""
        if self.pack.kind == "preset":
            return [self.dest.currentIndex()]
        if self.pack.kind == "bank":
            return [self.dest.currentIndex() * 4 + i for i in range(4)]
        return [o for o, _, _ in self.pack.presets]

    def _start(self) -> None:
        dest = self.destination()
        if not self.pack.amps:
            self.main.load_pack_in_editor(self.pack, dest)
            self.accept()
            return
        moves = {amp.slot: combo.currentIndex() for amp, combo in zip(self.pack.amps, self.amp_slots)}
        if len(set(moves.values())) < len(moves):
            self.status(self.step, "Dos modelos no pueden ir al mismo espacio de AMP.", False)
            return
        todo = pack.missing([self.pack])
        if todo and not ask(self, "Importar pack", f"Faltan en este equipo {len(todo)} modelo{'s' if len(todo) > 1 else ''} de AMP "
                            f"de este pack ({', '.join(a.name for a in todo)}).\n¿Descargarlos ahora de la comunidad de M-VAVE?"):
            return
        amps = ", ".join(f"AMP {s + 1}" for s in sorted(moves.values()))
        if not ask(self, "Importar pack", f"Se reemplazarán en la pedalera {amps} y los presets "
                   f"{', '.join(slot_name(s) for s in dest) if len(dest) <= 4 else 'de los 36 slots'}."
                   + self.main.replace_warning(moves.values(), dest) + "\n¿Continuar?"):
            return
        if self.main.start_pack_import(self.pack, dest, moves, self):
            self._running("Conectando por Bluetooth…")


class FactoryAmpCabDialog(_ModelJobDialog):
    """Put back the factory AMP and CAB models (and optionally the 36 presets) of set AM4 or AM3,
    like "restore" in M-EFCS (Bluetooth only)."""

    def __init__(self, main):
        super().__init__(main, "Restaurar AMP/CAB de fábrica",
                         "Vuelve a escribir los 9 modelos de AMP y los 8 CAB que trae la pedalera, igual que M-EFCS. "
                         "Borra los modelos subidos. Se envía por Bluetooth y tarda unos 40 segundos.", 560, 420)
        self.running = False
        _, lay = self.card("1", "Juego de fábrica")
        row, self.kinds = self.segmented(list(library.FACTORY_SETS.values()), self)
        self.keys = list(library.FACTORY_SETS)
        self.kinds[self.keys.index(library.Settings().factory_set)].setChecked(True)
        lay.addLayout(row)
        self.presets = QCheckBox("También los 36 presets de fábrica de ese juego")
        self.presets.setChecked(True)
        lay.addWidget(self.presets)
        note = QLabel("Antes se hace un backup del banco de presets. Los cambios sin guardar del editor se pierden "
                      "si restauras también los presets.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        _, lay = self.card("", "Progreso")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        lay.addWidget(self.bar)
        self.step = QLabel()
        self.step.setWordWrap(True)
        lay.addWidget(self.step)
        self.status(self.step, "Requiere la pedalera encendida con Bluetooth y libre (sin la app del teléfono).")
        self.close_btn = self.button("Cancelar", self.reject)
        self.go = self.button("Restaurar", self._start, "primary")
        self.inputs = [self.presets, *self.kinds]

    def kind(self) -> str:
        return next(k for k, b in zip(self.keys, self.kinds) if b.isChecked())

    def _start(self) -> None:
        kind, presets = self.kind(), self.presets.isChecked()
        what = "los AMP/CAB" + (" y los 36 presets" if presets else "")
        if not ask(self, "Restaurar de fábrica", f"Se reemplazarán {what} de la pedalera por los de fábrica "
                   f"{library.FACTORY_SETS[kind]}.\n¿Continuar?"):
            return
        if self.main.start_factory_ampcab(kind, presets, self):
            self._running("Conectando por Bluetooth…")


class ArtistLibrary(StyledDialog):
    """Ready-made presets inspired by bands, in banks of four. Load one preset into the selected
    slot or the whole bank into a pedal bank; optionally upload it straight away."""

    def __init__(self, main):
        total = sum(len(b.presets) for b in artists.BANKS)
        super().__init__(main, "Biblioteca de sonidos",
                         f"{len(artists.BANKS)} bancos y {total} presets inspirados en bandas y estilos, sin usar IA. "
                         "Cada banda trae Limpio (o Crunch), Rítmica, Variante y Solo. Son aproximaciones: ajusta "
                         "gain y volumen a tu guitarra.", 960, 660)
        self.target = self.header_badge()
        cols = QHBoxLayout()
        cols.setSpacing(12)
        self.body.addLayout(cols, 1)

        left, llay = self._card("1", "Banda o estilo")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar banda, canción o estilo: metallica, death, solo…")
        self.search.textChanged.connect(self.populate)
        llay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("cards")
        self.list.setItemDelegate(CardDelegate(self.list, tall=True))
        self.list.currentRowChanged.connect(self._bank_changed)
        self.list.itemDoubleClicked.connect(lambda _: self.apply_bank())
        self.list.setToolTip("Doble clic: cargar los 4 presets en el banco elegido")
        llay.addWidget(self.list, 1)
        cols.addWidget(left, 2)

        right, rlay = self._card("2", "Presets del banco")
        self.presets = QListWidget()
        self.presets.setObjectName("cards")
        self.presets.setItemDelegate(CardDelegate(self.presets, tall=True))
        self.presets.setSpacing(2)
        self.presets.currentRowChanged.connect(lambda _: self._update_buttons())
        self.presets.itemDoubleClicked.connect(lambda _: self.apply_one())
        self.presets.setToolTip("Doble clic: aplicar al preset seleccionado")
        self.presets.setMinimumHeight(4 * 66 + 12)
        rlay.addWidget(self.presets, 1)
        self.detail = QLabel()
        self.detail.setObjectName("hint")
        self.detail.setWordWrap(True)
        rlay.addWidget(self.detail)
        dest = QHBoxLayout()
        dest.addWidget(QLabel("Cargar los 4 en:"))
        self.dest = QComboBox()
        for b in range(9):
            alias = main.aliases.bank(b)
            self.dest.addItem(f"Banco {b + 1}" + (f" · {alias}" if alias else ""), b)
        self.dest.setCurrentIndex(main.current // 4)
        self.dest.currentIndexChanged.connect(self._update_buttons)
        dest.addWidget(self.dest, 1)
        rlay.addLayout(dest)
        self.upload = QCheckBox("Subir a la pedalera al aplicar")
        self.upload.setChecked(main.connected and main.device is not None)
        self.upload.setEnabled(main.connected and main.device is not None)
        if not self.upload.isEnabled():
            self.upload.setToolTip("Pedalera no conectada: los cambios quedan en el editor.")
        rlay.addWidget(self.upload)
        cols.addWidget(right, 3)

        self.button("Cerrar", self.reject)
        self.bank_btn = self.button("", self.apply_bank)
        self.one_btn = self.button("", self.apply_one, "primary")
        self.banks: list[artists.StyleBank] = []
        self.populate()

    def _card(self, number: str, title: str) -> tuple[QFrame, QVBoxLayout]:
        card, lay = self.card(number, title)
        self.body.removeWidget(card)   # card() adds to the body; here it goes into a column
        return card, lay

    def populate(self) -> None:
        query = self.search.text().strip().lower()
        self.list.blockSignals(True)
        self.list.clear()
        self.banks = []
        for genre in artists.GENRES:
            banks = [b for b in artists.BANKS if b.genre == genre and (
                not query or query in f"{b.genre} {b.name} ".lower()
                + " ".join(f"{p.name} {p.desc}" for p in b.presets).lower())]
            if not banks:
                continue
            head = QListWidgetItem(genre.upper())
            head.setFlags(Qt.NoItemFlags)
            head.setData(CARD_ROLE, {"header": genre.upper()})
            self.list.addItem(head)
            self.banks.append(None)
            for b in banks:
                item = QListWidgetItem(b.name)
                item.setData(CARD_ROLE, {"badge": initials(b.name), "title": b.name, "color": led_color(b.presets[1].color),
                                         "sub": " · ".join(p.role for p in b.presets), "sub_color": QColor(TEXT_DIM),
                                         "pips": [led_color(p.color) for p in b.presets], "chip": AMP_MODELS[b.presets[1].amp]})
                self.list.addItem(item)
                self.banks.append(b)
        # band packs with captured amps (references to the M-VAVE community), after the factory-AMP banks
        packs = [p for _, p in pack.builtin() if not query or query in (
            f"{p.title} " + " ".join(a.name for a in p.amps) + " " + " ".join(n or "" for _, _, n in p.presets)).lower()]
        if packs:
            head = QListWidgetItem("★ CON AMP IMPORTADO (comunidad M-VAVE)")
            head.setFlags(Qt.NoItemFlags)
            head.setData(CARD_ROLE, {"header": "★ CON AMP IMPORTADO (COMUNIDAD M-VAVE)"})
            self.list.addItem(head)
            self.banks.append(None)
            for p in packs:
                item = QListWidgetItem(f"★ {p.title}")
                item.setData(CARD_ROLE, {"badge": "★", "title": p.title, "color": QColor(WARN),
                                         "sub": "AMP: " + " · ".join(a.name for a in p.amps), "sub_color": QColor(TEXT_DIM),
                                         "pips": [led_color(pr.color) for _, pr, _ in p.presets],
                                         "chip": "⬇ descarga" if pack.missing([p]) else "AMP listo"})
                self.list.addItem(item)
                self.banks.append(p)
        self.list.blockSignals(False)
        first = next((i for i, b in enumerate(self.banks) if b is not None), -1)
        self.list.setCurrentRow(first)
        self._bank_changed(first)

    def _bank(self) -> artists.StyleBank | None:
        row = self.list.currentRow()
        return self.banks[row] if 0 <= row < len(self.banks) else None

    def _bank_changed(self, _row: int) -> None:
        bank = self._bank()
        keep = max(0, self.presets.currentRow())
        self.presets.blockSignals(True)
        self.presets.clear()
        if isinstance(bank, pack.Pack):
            models = {a.slot: a for a in bank.amps}
            for i, (_, p, name) in enumerate(bank.presets):
                amp = models.get(p.amp)
                item = QListWidgetItem(name or f"Preset {'ABCD'[i]}")
                item.setToolTip(f"AMP importado: «{amp.name}» ({amp.credit_text()})" if amp else f"AMP de fábrica: {p.amp_name}")
                item.setData(CARD_ROLE, {"badge": "ABCD"[i], "title": name or f"Preset {'ABCD'[i]}", "color": led_color(p.color),
                                         "sub": f"★ {amp.name}" if amp else f"AMP de fábrica · {p.cab_name}",
                                         "chip": p.amp_name if not amp else "AMP importado"})
                self.presets.addItem(item)
        elif bank is not None:
            for i, p in enumerate(bank.presets):
                item = QListWidgetItem(p.name)
                item.setToolTip(p.summary())
                item.setData(CARD_ROLE, {"badge": "ABCD"[i], "title": f"{p.role.upper()} · {p.name}", "color": led_color(p.color),
                                         "sub": p.desc, "sub_color": QColor(TEXT_DIM), "chip": AMP_MODELS[p.amp]})
                self.presets.addItem(item)
        self.presets.blockSignals(False)
        if self.presets.count():
            self.presets.setCurrentRow(min(keep, self.presets.count() - 1))
        self._update_buttons()

    def _update_buttons(self) -> None:
        bank = self._bank()
        dest = self.dest.currentData() + 1
        self.one_btn.setText(f"Aplicar a {slot_name(self.main.current)}")
        self.bank_btn.setText(f"Cargar los 4 en banco {dest}")
        self.one_btn.setEnabled(bank is not None and not isinstance(bank, pack.Pack))
        self.bank_btn.setEnabled(bank is not None)
        if isinstance(bank, pack.Pack):
            self.bank_btn.setText(f"Importar con sus AMP en banco {dest}…" + (" (descarga)" if pack.missing([bank]) else ""))
        self.target.setText(f"Seleccionado: {slot_name(self.main.current)}")
        row = self.presets.currentRow()
        self.detail.setText(self.presets.item(row).toolTip() if row >= 0 else "")

    def apply_one(self) -> None:
        bank = self._bank()
        if bank is None or isinstance(bank, pack.Pack):   # packs go in whole, with their AMP models
            return
        p = bank.presets[max(0, self.presets.currentRow())]
        like = self.main.local.presets[self.main.current]
        self.main.apply_presets(self.main.current, [(p.build(like), p.name)], upload=self.upload.isChecked(),
                                what=f"«{p.name}»")
        self.accept()

    def apply_bank(self) -> None:
        bank = self._bank()
        if bank is None:
            return
        if isinstance(bank, pack.Pack):   # its AMP models are uploaded first (downloaded if missing)
            self.accept()
            d = PackImportDialog(self.main, bank)
            d.dest.setCurrentIndex(self.dest.currentData())
            d.exec()
            return
        first = self.dest.currentData() * 4
        if not ask(self, "Cargar banco", f"Se reemplazarán los 4 presets del banco {first // 4 + 1} "
                                         f"por «{bank.name}».\n¿Continuar?"):
            return
        items = [(p.build(self.main.local.presets[first + i]), p.name) for i, p in enumerate(bank.presets)]
        self.main.apply_presets(first, items, bank.name, upload=self.upload.isChecked(), what=f"«{bank.name}»")
        self.accept()


class BackupManager(StyledDialog):
    """Lists automatic and manual backups; load one into the editor or compare it."""

    def __init__(self, main):
        super().__init__(main, "Backups", "Copias del banco completo guardadas antes de cada escritura y las "
                         "que hiciste a mano. Puedes cargarlas en el editor o compararlas.", 820, 560)
        self.header_badge(f"{len(library.list_backups())} copias")
        _, lay = self.card("", "Copias guardadas", stretch=1)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Fecha", "Motivo", "Distintos al editor", "Archivo"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _: self.load())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        lay.addWidget(self.table, 1)
        self.info = QLabel()
        self.info.setObjectName("hint")
        lay.addWidget(self.info)
        folder = self.button("Abrir carpeta", self.open_folder, "link", left=True)
        folder.setToolTip(str(library.BACKUP_DIR))
        self.button("Cerrar", self.accept)
        self.compare_btn = self.button("Comparar", self.compare)
        self.load_btn = self.button("Cargar en el editor", self.load, "primary")
        self.paths: list[Path] = []
        self.populate()
        self._selection_changed()

    def populate(self) -> None:
        self.paths = library.list_backups()
        self.table.setRowCount(len(self.paths))
        for r, path in enumerate(self.paths):
            m = _NAME_RE.search(path.name)
            when = datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S") if m else "?"
            reason = m[3] if m else ""
            try:
                bank = library.load_bank(path)
                diff = len(bank.diff_slots(self.main.local)) if self.main.local else "—"
            except (OSError, ValueError):
                diff = "ilegible"
            for c, v in enumerate([when, reason, str(diff), path.name]):
                item = QTableWidgetItem(v)
                if c == 2:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)
        if not self.paths:
            self.status(self.info, "Todavía no hay backups.")

    def _selection_changed(self) -> None:
        has = bool(self.table.selectionModel().selectedRows())
        self.load_btn.setEnabled(has)
        self.compare_btn.setEnabled(has and self.main.local is not None)
        if self.paths:
            self.status(self.info, "Doble clic o «Cargar en el editor»; después «Guardar todo» lo pasa a la "
                                   "pedalera." if has else "Selecciona una copia.")

    def _selected(self) -> Path | None:
        rows = self.table.selectionModel().selectedRows()
        return self.paths[rows[0].row()] if rows else None

    def load(self) -> None:
        path = self._selected()
        if path is None:
            return
        try:
            bank = library.load_bank(path)
        except (OSError, ValueError) as e:
            self.status(self.info, str(e), False)
            return
        self.main.load_local_bank(bank, f"Backup {path.name} cargado. «Guardar todo» lo pasa a la pedalera.")
        self.accept()

    def compare(self) -> None:
        path = self._selected()
        if path is not None and self.main.local is not None:
            self.main.show_diff(library.load_bank(path), f"{path.name} → editor")

    def open_folder(self) -> None:
        library.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(library.BACKUP_DIR)))


CARD_ROLE = Qt.UserRole + 1   # {"badge", "title", "sub", "chip", "color", "pips", "lost"} or {"header"}: CardDelegate


def initials(name: str) -> str:
    """Two letters for a band's circle: «Blind Guardian» -> BG, «AC/DC» -> AC (same as initials() in app.js)."""
    words = [w for w in name.replace("★", "").split() if w[:1].isalnum()]
    return ("".join(w[0] for w in words[:2]) if len(words) > 1 else (words[0][:2] if words else "?")).upper()


def scaled_font(base: QFont, factor: float, bold: bool = False) -> QFont:
    """`base` resized by `factor`, whether its size is in points or (from a stylesheet) in pixels."""
    f = QFont(base)
    if base.pointSizeF() > 0:
        f.setPointSizeF(base.pointSizeF() * factor)
    else:
        f.setPixelSize(max(6, round(base.pixelSize() * factor)))
    f.setBold(bold)
    return f


def led_color(rgb: tuple[int, int, int]) -> QColor:
    """A preset's footswitch colour for the interface; too dark to see (LED off) = the accent."""
    return QColor(*rgb) if sum(rgb) > 90 else QColor(ACCENT_HOVER)


class CardDelegate(QStyledItemDelegate):
    """List rows drawn as cards: a circle in the preset's LED colour with its slot (or a band's
    initials), the name, an optional second line (song note, description) after small colour dots,
    and a chip (the AMP model); {"header": text} rows are group titles. Setlist and library lists."""

    def __init__(self, parent, tall: bool):
        super().__init__(parent)
        self.tall = tall

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt API
        if (index.data(CARD_ROLE) or {}).get("header"):
            return QSize(0, 32)
        return QSize(0, 58 if self.tall else 42)

    def paint(self, painter: QPainter, option, index) -> None:
        card = index.data(CARD_ROLE) or {}
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if card.get("header"):
            font = scaled_font(option.font, 0.82, True)
            font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
            painter.setFont(font)
            painter.setPen(QColor(TEXT_DIM))
            painter.drawText(option.rect.adjusted(8, 0, -8, -4), Qt.AlignLeft | Qt.AlignBottom, card["header"])
            painter.restore()
            return
        r = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.State_Selected)
        painter.setPen(QColor(ACCENT_HOVER) if selected else QColor(BORDER_2))
        painter.setBrush(QColor(TEAL) if selected else QColor(SURFACE_2))
        painter.drawRoundedRect(r, 9, 9)
        color = QColor(ERROR) if card.get("lost") else card.get("color", QColor(ACCENT_HOVER))
        d = r.height() - 12
        circle = QRectF(r.left() + 8, r.top() + 6, d, d)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(circle)
        painter.setFont(scaled_font(option.font, 0.95 if self.tall else 0.8, True))
        painter.setPen(QColor("#10161a") if color.lightness() > 120 else QColor("#ffffff"))
        painter.drawText(circle, Qt.AlignCenter, card.get("badge", ""))
        left = int(circle.right()) + 12
        chip = card.get("chip", "")
        chip_w = 0
        if chip:
            painter.setFont(scaled_font(option.font, 0.8))
            chip_w = painter.fontMetrics().horizontalAdvance(chip) + 16
            chip_r = QRectF(r.right() - chip_w - 8, r.center().y() - 11, chip_w, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(FIELD))
            painter.drawRoundedRect(chip_r, 11, 11)
            painter.setPen(QColor(TEXT_DIM))
            painter.drawText(chip_r, Qt.AlignCenter, chip)
        width = r.right() - left - chip_w - 16
        painter.setFont(scaled_font(option.font, 1.08 if self.tall else 1.0, True))
        painter.setPen(QColor(TEXT))
        sub = card.get("sub", "")
        top = QRect(left, r.top() + 7, width, r.height() // 2 - 5) if sub else QRect(left, r.top(), width, r.height())
        painter.drawText(top, Qt.AlignLeft | (Qt.AlignBottom if sub else Qt.AlignVCenter),
                         painter.fontMetrics().elidedText(card.get("title", ""), Qt.ElideRight, width))
        if sub:
            painter.setFont(scaled_font(option.font, 0.88))
            x = left
            for c in card.get("pips", []):   # the LED colours of a bank's four presets
                painter.setPen(Qt.NoPen)
                painter.setBrush(c)
                painter.drawEllipse(QRectF(x, r.center().y() + 5, 9, 9))
                x += 12
            x += 4 if card.get("pips") else 0
            painter.setPen(QColor(ERROR) if card.get("lost") else card.get("sub_color", QColor(WARN)))
            painter.drawText(QRect(x, r.center().y() + 2, width - (x - left), r.height() // 2 - 6), Qt.AlignLeft | Qt.AlignTop,
                             painter.fontMetrics().elidedText(sub, Qt.ElideRight, width - (x - left)))
        painter.restore()


class SetlistDialog(StyledDialog):
    """Saved setlists (tankg/setlist.py, in Aliases.setlists and the cloud): songs with notes, stage
    mode, and optionally the songs put in footswitch order; same as the APK setlist sheet."""

    def __init__(self, main):
        super().__init__(main, "Setlists", "Arma tus shows con los presets en el orden en que los vas a tocar y "
                         "una nota por canción. «Modo escenario» los muestra en grande y cambia el preset con las "
                         "flechas o la barra espaciadora; «Ordenar» los deja seguidos en la pedalera (1A, 1B, 1C, "
                         "1D, 2A…) para pasarlos con los footswitches.", 900, 720)
        self.lists = main.aliases.setlists
        if not self.lists:
            self.lists.append({"title": "Mi show", "songs": []})
        self.index = 0
        _, lay = self.card("1", "Setlist")
        row = QHBoxLayout()
        self.pick = QComboBox()
        self.pick.setMinimumWidth(260)
        self.pick.currentIndexChanged.connect(self._picked)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Nombre del show (p. ej. «Bar El Sótano, sábado»)")
        self.title.textEdited.connect(self._renamed)
        row.addWidget(self.pick)
        row.addWidget(self.title, 1)
        for text, fn in (("Nuevo", self.new), ("Borrar", self.delete)):
            row.addWidget(self._small(text, fn))
        lay.addLayout(row)
        _, lay = self.card("2", "Canciones, en orden", stretch=1)
        row = QHBoxLayout()
        self.pool = QListWidget()
        self.pool.itemDoubleClicked.connect(lambda _: self.add())
        self.songs = QListWidget()
        self.songs.setDragDropMode(QAbstractItemView.InternalMove)
        self.songs.itemDoubleClicked.connect(lambda _: self.remove())
        self.songs.model().rowsMoved.connect(lambda *_: self._reordered())
        self.songs.currentRowChanged.connect(self._song_selected)
        buttons = QVBoxLayout()
        buttons.addStretch()
        for text, fn in (("Agregar →", self.add), ("← Quitar", self.remove), ("Subir ↑", lambda: self.move(-1)),
                         ("Bajar ↓", lambda: self.move(1))):
            buttons.addWidget(self._small(text, fn))
        buttons.addStretch()
        for title, widget in (("Presets del editor", self.pool), (None, buttons), ("Orden del show (arrastra para mover)", self.songs)):
            if title is None:
                row.addLayout(widget)
                continue
            col = QVBoxLayout()
            label = QLabel(title)
            label.setObjectName("hint")
            col.addWidget(label)
            col.addWidget(widget, 1)
            row.addLayout(col, 1)
        lay.addLayout(row, 1)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Nota de la canción seleccionada: afinación, capo, tempo, «entra con fade»…")
        self.note.textEdited.connect(self._note_edited)
        lay.addWidget(self.note)
        _, lay = self.card("3", "Ordenar en la pedalera (opcional)")
        row = QHBoxLayout()
        row.addWidget(QLabel("Desde el slot:"))
        self.start = QComboBox()
        self.start.currentIndexChanged.connect(lambda _: self.update_info())
        row.addWidget(self.start)
        row.addStretch()
        self.order_btn = self._small("Ordenar en el editor", self.apply)
        row.addWidget(self.order_btn)
        lay.addLayout(row)
        self.info = QLabel()
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.button("Copiar lista", self.copy_text, "link", left=True)
        self.button("Cerrar", self.accept)
        self.stage_btn = self.button("▶  Modo escenario", self.stage, "primary")
        self.pool.setItemDelegate(CardDelegate(self.pool, tall=False))
        self.songs.setItemDelegate(CardDelegate(self.songs, tall=True))
        for w in (self.pool, self.songs):
            w.setObjectName("cards")
            w.setSpacing(1)
        for s in range(SLOTS):
            item = QListWidgetItem(self.label(s))
            item.setData(Qt.UserRole, s)
            self.pool.addItem(item)
        self._fill_picker()

    def _small(self, text: str, fn) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("secondary")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(fn)
        return b

    def label(self, s: int) -> str:
        return f"{slot_name(s)} · {self.main.aliases.preset(s) or self.main.local.presets[s].amp_name}"

    def _pool_card(self, s: int) -> dict:
        p = self.main.local.presets[s]
        return {"badge": slot_name(s), "title": self.main.aliases.preset(s) or p.amp_name,
                "chip": self.main.aliases.amp(p.amp) or p.amp_name, "color": led_color(p.color)}

    def _song_card(self, i: int) -> dict:
        s, slot = self.current()["songs"][i], self.slots[i]
        if slot is None:
            return {"badge": "⚠", "title": f"{i + 1}. {setlist.label(s)}", "sub": "Su preset ya no está en el editor",
                    "lost": True}
        p = self.main.local.presets[slot]
        return {"badge": slot_name(slot), "title": f"{i + 1}. {setlist.label(s)}", "sub": s.get("note", "").strip(),
                "chip": self.main.aliases.amp(p.amp) or p.amp_name, "color": led_color(p.color)}

    # the saved setlists ----------------------------------------------------------------

    def current(self) -> dict:
        return self.lists[self.index]

    def _fill_picker(self) -> None:
        self.pick.blockSignals(True)
        self.pick.clear()
        for sl in self.lists:
            self.pick.addItem(f"{sl['title']}  ({len(sl['songs'])})")
        self.pick.setCurrentIndex(self.index)
        self.pick.blockSignals(False)
        self._load()

    def _picked(self, i: int) -> None:
        if 0 <= i < len(self.lists):
            self.index = i
            self._load()

    def _renamed(self, text: str) -> None:
        self.current()["title"] = text.strip() or "Setlist"
        self.pick.setItemText(self.index, f"{self.current()['title']}  ({len(self.current()['songs'])})")
        self._store()

    def new(self) -> None:
        self.lists.append({"title": f"Show {len(self.lists) + 1}", "songs": []})
        self.index = len(self.lists) - 1
        self._store()
        self._fill_picker()
        self.title.setFocus()
        self.title.selectAll()

    def delete(self) -> None:
        sl = self.current()
        if sl["songs"] and not ask(self, "Borrar setlist", f"¿Borrar «{sl['title']}»? Los presets no se tocan."):
            return
        del self.lists[self.index]
        if not self.lists:
            self.lists.append({"title": "Mi show", "songs": []})
        self.index = min(self.index, len(self.lists) - 1)
        self._store()
        self._fill_picker()

    def _store(self) -> None:
        self.main.aliases.save()
        self.main._schedule_cloud()

    # songs -----------------------------------------------------------------------------

    def _load(self) -> None:
        """Shows the current setlist, with each song pointing to where its preset is now."""
        sl = self.current()
        sl["songs"] = setlist.refresh(sl["songs"], self.main.local, self.main.aliases.presets)
        self.title.setText(sl["title"])
        self.slots = setlist.resolve(sl["songs"], self.main.local, self.main.aliases.presets)
        row = self.songs.currentRow()
        self.songs.blockSignals(True)
        self.songs.clear()
        for i, (s, slot) in enumerate(zip(sl["songs"], self.slots)):
            note = s.get("note", "").strip()
            where = slot_name(slot) if slot is not None else "⚠ ya no está"
            item = QListWidgetItem(f"{i + 1}. {where}  ·  {setlist.label(s)}" + (f"   — {note}" if note else ""))
            item.setData(Qt.UserRole, i)
            item.setData(CARD_ROLE, self._song_card(i))
            self.songs.addItem(item)
        self.songs.blockSignals(False)
        self.songs.setCurrentRow(min(max(row, 0), self.songs.count() - 1))
        for r in range(self.pool.count()):
            self.pool.item(r).setText(self.label(r))
            self.pool.item(r).setData(CARD_ROLE, self._pool_card(r))
            self.pool.item(r).setHidden(r in self.slots)
        self._song_selected(self.songs.currentRow())
        self.pick.setItemText(self.index, f"{sl['title']}  ({len(sl['songs'])})")
        self._fill_starts()

    def _fill_starts(self) -> None:
        keep = self.start.currentData()
        n = max(1, len(self.current()["songs"]))
        self.start.blockSignals(True)
        self.start.clear()
        for s in range(SLOTS - n + 1):
            self.start.addItem(f"{slot_name(s)} (banco {s // 4 + 1})", s)
        self.start.setCurrentIndex(max(0, min(keep or 0, self.start.count() - 1)))
        self.start.blockSignals(False)
        self.update_info()

    def _song_selected(self, row: int) -> None:
        songs = self.current()["songs"]
        self.note.setEnabled(0 <= row < len(songs))
        self.note.setText(songs[row].get("note", "") if 0 <= row < len(songs) else "")

    def _note_edited(self, text: str) -> None:
        row = self.songs.currentRow()
        if 0 <= row < len(self.current()["songs"]):
            self.current()["songs"][row]["note"] = text
            self._store()
            note = text.strip()
            s, slot = self.current()["songs"][row], self.slots[row]
            self.songs.item(row).setText(f"{row + 1}. {slot_name(slot) if slot is not None else '⚠ ya no está'}  ·  "
                                         f"{setlist.label(s)}" + (f"   — {note}" if note else ""))
            self.songs.item(row).setData(CARD_ROLE, self._song_card(row))

    def add(self) -> None:
        item = self.pool.currentItem()
        if item is None or item.isHidden():
            return
        s = item.data(Qt.UserRole)
        self.current()["songs"].append(setlist.song(self.main.local, self.main.aliases.presets, s))
        row = self.pool.currentRow()
        nxt = next((r for r in range(row + 1, self.pool.count()) if not self.pool.item(r).isHidden()), None)
        self._store()
        self._load()
        self.songs.setCurrentRow(self.songs.count() - 1)
        if nxt is not None:
            self.pool.setCurrentRow(nxt)

    def remove(self) -> None:
        row = self.songs.currentRow()
        if 0 <= row < len(self.current()["songs"]):
            del self.current()["songs"][row]
            self._store()
            self._load()

    def move(self, delta: int) -> None:
        row, songs = self.songs.currentRow(), self.current()["songs"]
        if row >= 0 and 0 <= row + delta < len(songs):
            songs[row], songs[row + delta] = songs[row + delta], songs[row]
            self._store()
            self.songs.setCurrentRow(row + delta)
            self._load()

    def _reordered(self) -> None:
        """Drag and drop: the list widget moved its items; put the songs in the same order."""
        songs = self.current()["songs"]
        order = [self.songs.item(i).data(Qt.UserRole) for i in range(self.songs.count())]
        self.current()["songs"] = [songs[i] for i in order]
        self._store()
        self._load()

    def update_info(self) -> None:
        songs, start = self.current()["songs"], self.start.currentData() or 0
        lost = self.slots.count(None)
        self.order_btn.setEnabled(bool(songs) and not lost)
        self.stage_btn.setEnabled(bool(songs))
        if not songs:
            self.status(self.info, "Agrega canciones con doble clic o «Agregar →».")
        elif lost:
            self.status(self.info, f"{lost} canción(es) ya no tienen su preset en el editor (⚠): quítalas o vuelve a "
                                   "agregarlas para poder ordenar.", False)
        else:
            moved = sum(1 for new, old in enumerate(setlist.layout(self.slots, start)) if new != old)
            self.status(self.info, f"{len(songs)} canciones de {slot_name(start)} a {slot_name(start + len(songs) - 1)}. "
                        + (f"Cambian de lugar {moved} presets; deshacer (Ctrl+Z) lo vuelve atrás." if moved
                           else "Ya están en ese orden: no se mueve nada."), True)

    def copy_text(self) -> None:
        QApplication.clipboard().setText(setlist.text(self.current()["title"], self.current()["songs"], self.slots))
        self.status(self.info, "Lista copiada: pégala en un mensaje o imprímela.", True)

    def apply(self) -> None:
        start = self.start.currentData() or 0
        self.main.apply_setlist(list(self.slots), start)
        self._store()
        self._load()
        self.status(self.info, f"Ordenado de {slot_name(start)} a {slot_name(start + len(self.slots) - 1)}. "
                               "«Guardar cambios» lo pasa a la pedalera.", True)

    def stage(self) -> None:
        if self.current()["songs"]:
            StageWindow(self.main, self.current()["title"], self.current()["songs"], self.slots,
                        max(0, self.songs.currentRow())).exec()


class StageWindow(QDialog):
    """Stage mode: the current song in big letters over a glow in its preset's LED colour, its slot
    and note, the show's progress and the next song; the arrows, space, Page Up/Down (page turner
    pedals) or the buttons move through the show and activate each preset on the pedal when it is
    connected."""

    def __init__(self, main, title: str, songs: list[dict], slots: list[int | None], first: int = 0):
        super().__init__(main)
        self.main, self.songs, self.slots = main, songs, slots
        self.glow = QColor(ACCENT_HOVER)
        self.setObjectName("stage")
        self.setWindowTitle(f"Escenario · {title}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 24, 40, 28)
        top = QHBoxLayout()
        self.show_title = QLabel(f"SETLIST · {title}")
        self.show_title.setObjectName("stageDim")
        self.count = QLabel()
        self.count.setObjectName("stageDim")
        close = QPushButton("Salir (Esc)")
        close.setObjectName("secondary")
        close.clicked.connect(self.accept)
        top.addWidget(self.show_title)
        top.addStretch()
        top.addWidget(self.count)
        top.addSpacing(16)
        top.addWidget(close)
        lay.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setObjectName("stageProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        lay.addWidget(self.progress)
        lay.addStretch(1)
        self.center = QWidget()
        center = QVBoxLayout(self.center)
        center.setSpacing(6)
        self.slot = QLabel()
        self.slot.setObjectName("stageSlot")
        self.amp = QLabel()
        self.amp.setObjectName("stageAmp")
        self.name = QLabel()
        self.name.setObjectName("stageName")
        self.name.setWordWrap(True)
        self.note = QLabel()
        self.note.setObjectName("stageNote")
        self.note.setWordWrap(True)
        self.warn = QLabel()
        self.warn.setObjectName("stageWarn")
        for w in (self.slot, self.amp, self.name, self.note, self.warn):
            w.setAlignment(Qt.AlignCenter)
            center.addWidget(w)
        self.fade = QGraphicsOpacityEffect(self.center)
        self.center.setGraphicsEffect(self.fade)
        self.anim = QPropertyAnimation(self.fade, b"opacity", self)
        self.anim.setDuration(260)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        lay.addWidget(self.center)
        lay.addStretch(1)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        self.prev = QPushButton("◀  Anterior")
        self.next = QPushButton("Siguiente  ▶")
        card = QFrame()
        card.setObjectName("stageNextCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 10, 18, 10)
        inner.setSpacing(0)
        caption = QLabel("SIGUE")
        caption.setObjectName("stageCaption")
        self.up_next = QLabel()
        self.up_next.setObjectName("stageNext")
        for w in (caption, self.up_next):
            w.setAlignment(Qt.AlignCenter)
            inner.addWidget(w)
        for b, d in ((self.prev, -1), (self.next, 1)):
            b.setObjectName("stageButton")
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, d=d: self.go(self.pos + d))
        self.next.setProperty("primary", True)
        close.setFocusPolicy(Qt.NoFocus)
        bottom.addWidget(self.prev)
        bottom.addWidget(card, 1)
        bottom.addWidget(self.next)
        lay.addLayout(bottom)
        self.progress.setRange(0, len(songs))
        self.pending: int | None = None   # slot to activate once the pedal is free (fast steps never get lost)
        self.retry = QTimer(self)
        self.retry.setSingleShot(True)
        self.retry.setInterval(120)
        self.retry.timeout.connect(self._activate)
        self.pos = -1
        self.go(first)
        self.showFullScreen()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Dark stage with a soft glow in the current preset's LED colour behind the song."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0b0e11"))
        g = QRadialGradient(self.rect().center(), max(self.width(), self.height()) * 0.6)
        inner, outer = QColor(self.glow), QColor(self.glow)
        inner.setAlpha(70)
        outer.setAlpha(0)
        g.setColorAt(0, inner)
        g.setColorAt(1, outer)
        painter.fillRect(self.rect(), g)

    def go(self, i: int) -> None:
        if not 0 <= i < len(self.songs) or i == self.pos:
            return
        self.pos = i
        s, slot = self.songs[i], self.slots[i]
        self.count.setText(f"{i + 1} / {len(self.songs)}")
        self.progress.setValue(i + 1)
        self.slot.setText(slot_name(slot) if slot is not None else "—")
        self.name.setText(setlist.label(s))
        self.note.setText(s.get("note", "").strip())
        self.warn.setText("")
        self.amp.setText("")
        if slot is None:
            self.glow = QColor(ERROR)
            self.warn.setText("Este preset ya no está en el editor.")
        else:
            p = self.main.local.presets[slot]
            self.glow = led_color(p.color)
            self.amp.setText(f"{self.main.aliases.amp(p.amp) or p.amp_name}  ·  {p.cab_name}")
            self.main.select_slot(slot)
            if not self.main.connected:
                self.warn.setText("Pedalera no conectada: solo se muestra.")
            elif slot in self.main.modified_slots():
                self.warn.setText("Cambios sin guardar: suena la versión de la pedalera.")
            if self.main.connected:
                self.pending = slot
                self._activate()
        self.slot.setStyleSheet(f"color: {self.glow.lighter(115).name()};")   # the slot in the LED colour
        nxt = self.songs[i + 1] if i + 1 < len(self.songs) else None
        nslot = self.slots[i + 1] if nxt else None
        self.up_next.setText(f"{slot_name(nslot) if nslot is not None else '—'} · {setlist.label(nxt)}" if nxt
                             else "Fin del show")
        self.prev.setEnabled(i > 0)
        self.next.setEnabled(i + 1 < len(self.songs))
        self.anim.stop()
        self.anim.start()
        self.update()

    def _activate(self) -> None:
        if self.pending is None:
            return
        if self.main.busy:   # the previous song is still being selected
            self.retry.start()
            return
        self.main.current, self.pending = self.pending, None
        self.main.activate_selected(quiet=True)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        k = event.key()
        if k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space, Qt.Key_PageDown, Qt.Key_Return, Qt.Key_Enter):
            self.go(self.pos + 1)
        elif k in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp, Qt.Key_Backspace):
            self.go(self.pos - 1)
        elif k == Qt.Key_Home:
            self.go(0)
        else:
            super().keyPressEvent(event)


class CalibrationWizard(StyledDialog):
    """Finds which byte a front-panel knob is stored in: snapshot the bank, let the user save
    a preset from the pedal (LIVE mode), read again and show the bytes that changed."""

    LOG = library.DATA_DIR / "calibration.log"

    def __init__(self, main):
        super().__init__(main, "Asistente de calibración", "Confirma en qué byte guarda la pedalera cada "
                         "perilla: mueves una perilla en la pedalera, guardas y la app muestra qué cambió.",
                         720, 680, scroll=True)
        self.reference: Bank | None = None
        self.header_badge("Modo LIVE")
        _, l1 = self.card("1", "Tomar referencia")
        h1 = QLabel("Lee el estado actual de los 36 presets para poder comparar después.")
        h1.setObjectName("hint")
        h1.setWordWrap(True)
        self.ref_btn = QPushButton("Tomar referencia")
        self.ref_btn.setObjectName("primary")
        self.ref_btn.setCursor(Qt.PointingHandCursor)
        self.ref_btn.clicked.connect(self.take_reference)
        self.ref_state = QLabel()
        row = QHBoxLayout()
        row.addWidget(self.ref_btn)
        row.addWidget(self.ref_state, 1)
        l1.addWidget(h1)
        l1.addLayout(row)
        _, l2 = self.card("2", "Guardar desde la pedalera")
        h2 = QLabel("Entra en modo LIVE (pulsa B+C), mueve <b>una sola</b> perilla y mantén pulsado A, B, C o D "
                    "hasta que parpadee: así se guarda en ese preset.")
        h2.setWordWrap(True)
        h2.setTextFormat(Qt.RichText)
        l2.addWidget(h2)
        _, l3 = self.card("3", "Leer cambios", stretch=1)
        self.read_btn = QPushButton("Leer cambios")
        self.read_btn.setObjectName("primary")
        self.read_btn.setCursor(Qt.PointingHandCursor)
        self.read_btn.setEnabled(False)
        self.read_btn.clicked.connect(self.read_changes)
        h3 = QLabel("Aparecen los bytes que cambiaron y el control que la app les asigna. Si no coincide con la "
                    "perilla que moviste, ese byte está mal en el mapa. Cada lectura pasa a ser la nueva referencia.")
        h3.setObjectName("hint")
        h3.setWordWrap(True)
        self.out = QPlainTextEdit()
        self.out.setObjectName("log")
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(160)
        self.out.setPlaceholderText("Los cambios detectados aparecerán aquí.")
        l3.addWidget(h3)
        l3.addWidget(self.read_btn, 0, Qt.AlignLeft)
        l3.addWidget(self.out, 1)
        log = self.button("Abrir registro", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.LOG))),
                          "link", left=True)
        log.setToolTip(str(self.LOG))
        self.button("Cerrar", self.accept)
        self.status(self.ref_state, "Sin referencia todavía.")

    def _read(self, then) -> None:
        if not self.main.run_job(lambda dev, _: dev.read_bank(), then, "Leyendo la pedalera..."):
            self.status(self.ref_state, "Hay una operación en curso; espera unos segundos.", False)

    def take_reference(self) -> None:
        def done(bank: Bank) -> None:
            self.reference = bank
            self.read_btn.setEnabled(True)
            self.status(self.ref_state, f"Referencia tomada a las {datetime.now():%H:%M:%S}.", True)
            self.out.appendPlainText(f"[{datetime.now():%H:%M:%S}] Referencia tomada. Ahora guarda desde la pedalera.")
        self._read(done)

    def read_changes(self) -> None:
        def done(bank: Bank) -> None:
            lines = []
            for s in bank.diff_slots(self.reference):
                old, new = self.reference.presets[s].raw, bank.presets[s].raw
                for i in range(REC_LEN):
                    if old[i] != new[i]:
                        lines.append(f"  {slot_name(s)}  byte {i:2d}  {byte_name(i):<11} {old[i]:3d} → {new[i]:3d}")
            stamp = f"[{datetime.now():%H:%M:%S}]"
            text = f"{stamp} Sin cambios: ¿guardaste en la pedalera?" if not lines else \
                f"{stamp} Cambios:\n" + "\n".join(lines)
            self.out.appendPlainText(text)
            try:
                self.LOG.parent.mkdir(parents=True, exist_ok=True)
                with self.LOG.open("a") as f:
                    f.write(text.replace(stamp, f"[{datetime.now():%Y-%m-%d %H:%M:%S}]") + "\n")
            except OSError:
                pass
            self.reference = bank
        self._read(done)


class MidiPortDialog(StyledDialog):
    """Choose the MIDI input/output ports by hand when automatic detection fails
    (port names differ between Windows installations)."""

    def __init__(self, main):
        super().__init__(main, "Puerto MIDI", "Elige cómo se conecta la app con la pedalera. En Windows cierra "
                         "M-EFCS: el puerto solo lo puede usar un programa a la vez.", 700, 560)
        self.settings = library.Settings()
        _, l1 = self.card("1", "Modo de conexión")
        modes = QHBoxLayout()
        self.auto = self.mode_card("⚡  Automático\nBusca la Tank-G (TANK, M-VAVE, USB-Midi…)")
        self.manual = self.mode_card("⚙  Elegir puertos\nSi la detección automática falla")
        group = QButtonGroup(self)
        group.addButton(self.auto)
        group.addButton(self.manual)
        modes.addWidget(self.auto)
        modes.addWidget(self.manual)
        l1.addLayout(modes)
        self.ports_card, l2 = self.card("2", "Puertos")
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.in_combo = QComboBox()
        self.out_combo = QComboBox()
        form.addRow("Entrada (desde la pedalera)", self.in_combo)
        form.addRow("Salida (hacia la pedalera)", self.out_combo)
        l2.addLayout(form)
        row = QHBoxLayout()
        self.port_info = QLabel()
        self.port_info.setObjectName("hint")
        refresh = QPushButton("Actualizar lista")
        refresh.setObjectName("link")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.populate)
        row.addWidget(self.port_info, 1)
        row.addWidget(refresh)
        l2.addLayout(row)
        _, lb = self.card("3", "Bluetooth (Tank-G v2)")
        hb = QLabel("Sin cable: busca la pedalera por Bluetooth. Se usa cuando no hay una conectada por USB. "
                    "Desconecta antes la app del teléfono: la pedalera acepta una sola conexión.")
        hb.setObjectName("hint")
        hb.setWordWrap(True)
        lb.addWidget(hb)
        rowb = QHBoxLayout()
        self.ble_combo = QComboBox()
        self.ble_combo.setMinimumWidth(260)
        saved_ble = self.settings.ble
        self.ble_combo.addItem("(ninguna)", None)
        if saved_ble:
            self.ble_combo.addItem(saved_ble[0], saved_ble)
            self.ble_combo.setCurrentIndex(1)
        self.scan_btn = QPushButton("Buscar")
        self.scan_btn.setCursor(Qt.PointingHandCursor)
        self.scan_btn.clicked.connect(self.scan_ble)
        self.ble_state = QLabel()
        self.ble_state.setObjectName("hint")
        rowb.addWidget(self.ble_combo, 1)
        rowb.addWidget(self.scan_btn)
        lb.addLayout(rowb)
        lb.addWidget(self.ble_state)
        if not device.ble_available():
            self.scan_btn.setEnabled(False)
            self.status(self.ble_state, "Falta la librería «bleak» (pip install bleak).", False)
        _, l3 = self.card("4", "Comprobar")
        row3 = QHBoxLayout()
        test = QPushButton("Probar conexión")
        test.setCursor(Qt.PointingHandCursor)
        test.clicked.connect(self.test)
        self.result = QLabel()
        self.result.setWordWrap(True)
        row3.addWidget(test)
        row3.addWidget(self.result, 1)
        l3.addLayout(row3)
        self.body.addStretch()
        self.button("Cancelar", self.reject)
        self.button("Guardar", self.save, "primary")
        saved = self.settings.midi_ports
        (self.manual if saved else self.auto).setChecked(True)
        self.manual.toggled.connect(self._mode_changed)
        self.populate()
        self._mode_changed()
        self.status(self.result, "Pulsa «Probar conexión» para leer la pedalera con esta configuración.")

    def _mode_changed(self) -> None:
        self.ports_card.setEnabled(self.manual.isChecked())

    def populate(self) -> None:
        try:
            ins, outs = device.list_midi_ports()
        except device.DeviceError as e:
            self.status(self.port_info, str(e), False)
            ins, outs = [], []
        else:
            self.status(self.port_info, f"{len(ins)} puerto(s) de entrada y {len(outs)} de salida.")
        saved = self.settings.midi_ports or ("", "")
        for combo, names, want in ((self.in_combo, ins, saved[0]), (self.out_combo, outs, saved[1])):
            combo.clear()
            combo.addItems(names)
            pick = want if want in names else next((n for n in names if device._port_score(n)), None)
            if pick:
                combo.setCurrentText(pick)

    def _chosen(self) -> tuple[str, str] | None:
        if self.auto.isChecked():
            return None
        if not self.in_combo.currentText() or not self.out_combo.currentText():
            return None
        return self.in_combo.currentText(), self.out_combo.currentText()

    def test(self) -> None:
        if self.main.busy:
            self.status(self.result, "Hay una operación en curso; prueba en unos segundos.", False)
            return
        # () = automatic detection, ignoring any saved manual choice
        devs = device.find_devices(self._chosen() or ("", "")) if self.manual.isChecked() \
            else device.find_devices(())
        if not devs:
            self.status(self.result, "No hay ningún puerto que coincida.", False)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dev = device.TankG.open(devs[0] if self.manual.isChecked() else None)
            address = dev.info.address
            dev.close()
            self.status(self.result, f"Tank-G encontrada en «{address}».", True)
        except device.DeviceError as e:
            self.status(self.result, str(e), False)
        finally:
            QApplication.restoreOverrideCursor()

    def scan_ble(self) -> None:
        self.scan_btn.setEnabled(False)
        self.status(self.ble_state, "Buscando pedaleras Bluetooth… (unos segundos)")

        def done(found) -> None:
            self.scan_btn.setEnabled(True)
            current = self.ble_combo.currentData()
            self.ble_combo.clear()
            self.ble_combo.addItem("(ninguna)", None)
            for info in found:
                self.ble_combo.addItem(info.name, (info.name, info.address))
            if found:
                self.ble_combo.setCurrentIndex(1)
            elif current:
                self.ble_combo.addItem(current[0], current)
            self.status(self.ble_state, f"{len(found)} pedalera(s) encontrada(s)." if found else
                        "No se encontró ninguna. ¿Está encendida y sin la app del teléfono conectada?", bool(found))

        def failed(msg: str) -> None:
            self.scan_btn.setEnabled(True)
            self.status(self.ble_state, msg, False)

        self.main._background(device.scan_bluetooth, done, failed)

    def save(self) -> None:
        if self.manual.isChecked() and self._chosen() is None:
            self.status(self.result, "Elige un puerto de entrada y uno de salida.", False)
            return
        self.settings.set_midi_ports(self._chosen())
        self.settings.set_ble(self.ble_combo.currentData())
        self.accept()


_PENDING: set = set()   # running tasks stay referenced even if their dialog is closed


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    """Runs fn() in a worker thread (no pedal involved)."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            self.signals.done.emit(self.fn())
        except ai.AIError as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - surface unexpected errors to the user
            self.signals.failed.emit(f"Error inesperado: {e}")



STEP_STATES = ("Copiar las instrucciones", "Pegarlas en el chat y enviar", "Copiar la respuesta de la IA")


class AIDialog(StyledDialog):
    """Describe a sound in words; an LLM fills every control of the current preset.

    Two ways to reach the model: the browser (no key: copy the prompt into claude.ai /
    chatgpt.com / Gemini and copy the answer back, detected from the clipboard) or an API key."""

    KEY_URLS = {"claude": "https://console.anthropic.com/settings/keys",
                "openai": "https://platform.openai.com/api-keys"}
    SUGGESTIONS = ai.SUGGESTIONS

    def __init__(self, main):
        super().__init__(main, "✨ Crear preset con IA", "Describe el sonido con tus palabras; la IA ajusta "
                         "amplificador, gabinete, EQ y efectos.", 800, 900, scroll=True)
        self.settings = library.Settings()
        self.result: tuple | None = None
        self.waiting_clipboard = False
        alias = main.aliases.preset(main.current)
        self.preset_target = f"{slot_name(main.current)}" + (f" · {alias}" if alias else "")
        bank_no = main.current // 4 + 1
        bank_alias = main.aliases.bank(main.current // 4)
        self.bank_target = f"Banco {bank_no} ({bank_no}A–{bank_no}D)" + (f" · {bank_alias}" if bank_alias else "")
        self.target = self.header_badge()

        # 1 · description ---------------------------------------------------------
        c1, l1 = self.card("1", "Describe el sonido")
        scope = QHBoxLayout()
        scope.setSpacing(0)
        self.one_btn = QPushButton(f"Solo este preset ({slot_name(main.current)})")
        self.bank_btn = QPushButton(f"Banco completo ({main.current // 4 + 1}A–{main.current // 4 + 1}D)")
        scope_group = QButtonGroup(self)
        for i, b in enumerate((self.one_btn, self.bank_btn)):
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton#seg { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }" if i == 0
                            else "QPushButton#seg { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }")
            scope_group.addButton(b)
            scope.addWidget(b)
        scope.addStretch()
        self.scope_hint = QLabel()
        self.scope_hint.setObjectName("hint")
        l1.addLayout(scope)
        l1.addWidget(self.scope_hint)
        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("desc")
        self.prompt.setPlaceholderText("Ej.: crunch cálido para riffs de rock clásico, con un poco de reverb")
        self.prompt.setFixedHeight(76)
        l1.addWidget(self.prompt)
        chips = QGridLayout()
        chips.setHorizontalSpacing(6)
        chips.setVerticalSpacing(6)
        for i, text in enumerate(self.SUGGESTIONS):
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, x=text: self.prompt.setPlainText(x))
            chips.addWidget(b, i // 4, i % 4)
        l1.addLayout(chips)
        row = QHBoxLayout()
        row.addWidget(QLabel("Instrumento"))
        self.instrument = QComboBox()
        self.instrument.addItems(ai.INSTRUMENTS)
        row.addWidget(self.instrument, 1)
        l1.addLayout(row)

        # 2 · connection ----------------------------------------------------------
        c2, l2 = self.card("2", "Conexión con la IA")
        modes = QHBoxLayout()
        self.web_card = self.mode_card("🌐  Navegador\nGratis · usa tu cuenta de Claude, ChatGPT o Gemini")
        self.api_card = self.mode_card("🔑  Clave de API\nAutomático · requiere una clave de pago")
        group = QButtonGroup(self)
        group.addButton(self.web_card)
        group.addButton(self.api_card)
        modes.addWidget(self.web_card)
        modes.addWidget(self.api_card)
        l2.addLayout(modes)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._web_page())
        self.stack.addWidget(self._api_page())
        l2.addWidget(self.stack)

        # 3 · result --------------------------------------------------------------
        c3, l3 = self.card("3", "Resultado", stretch=1)
        self.result_box = QFrame()
        self.result_box.setObjectName("result")
        self.result_lay = QVBoxLayout(self.result_box)
        self.result_lay.setContentsMargins(14, 12, 14, 12)
        l3.addWidget(self.result_box, 1)
        c3.setMinimumHeight(250)
        self.result_card = c3
        self._show_empty("El preset propuesto aparecerá aquí.")

        self.button("Cancelar", self.reject)
        self.apply_btn = self.button("", self.apply, "primary")
        self.apply_btn.setEnabled(False)

        saved = self.settings.ai
        site = saved.get("site", "Claude")
        self.site_buttons.get(site, self.site_buttons["Claude"]).setChecked(True)
        (self.api_card if saved.get("mode") == "api" else self.web_card).setChecked(True)
        idx = self.provider.findData(saved.get("provider", "claude"))
        self.provider.setCurrentIndex(max(0, idx))
        self.remember.setChecked(bool(saved.get("keys")))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.web_card.toggled.connect(self._mode_changed)
        for b in self.site_buttons.values():
            b.toggled.connect(self._site_changed)
        (self.bank_btn if saved.get("scope") == "bank" else self.one_btn).setChecked(True)
        self.bank_btn.toggled.connect(self._scope_changed)
        self._provider_changed()
        self._site_changed()
        self._mode_changed()
        self._scope_changed()
        self._set_step(0)
        QApplication.clipboard().dataChanged.connect(self._clipboard_changed)

    # building blocks ------------------------------------------------------------

    def _web_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.site_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for i, site in enumerate(ai.WEB_SITES):
            b = QPushButton(site)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            radius = "border-top-left-radius: 8px; border-bottom-left-radius: 8px;" if i == 0 else \
                "border-top-right-radius: 8px; border-bottom-right-radius: 8px;" if i == len(ai.WEB_SITES) - 1 else ""
            b.setStyleSheet(f"QPushButton#seg {{ {radius} }}")
            group.addButton(b)
            seg.addWidget(b)
            self.site_buttons[site] = b
        seg.addStretch()
        lay.addLayout(seg)
        self.copy_btn = QPushButton()
        self.copy_btn.setObjectName("bigPrimary")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self.copy_and_open)
        lay.addWidget(self.copy_btn)
        steps = QHBoxLayout()
        self.step_labels = []
        for i, text in enumerate(STEP_STATES):
            lab = QLabel()
            lab.setWordWrap(True)
            steps.addWidget(lab, 1)
            self.step_labels.append((lab, text))
        lay.addLayout(steps)
        manual = QHBoxLayout()
        hint = QLabel("La respuesta se detecta sola al copiarla.")
        hint.setObjectName("hint")
        paste = QPushButton("Pegar la respuesta manualmente")
        paste.setObjectName("link")
        paste.setCursor(Qt.PointingHandCursor)
        paste.clicked.connect(self.paste_answer)
        manual.addWidget(hint)
        manual.addStretch()
        manual.addWidget(paste)
        lay.addLayout(manual)
        return page

    def _api_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 6, 0, 0)
        form.setVerticalSpacing(8)
        self.provider = QComboBox()
        for key, p in ai.PROVIDERS.items():
            self.provider.addItem(p["label"], key)
        form.addRow("Servicio", self.provider)
        key_row = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key_link = QLabel()
        self.key_link.setOpenExternalLinks(True)
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.key_link)
        form.addRow("Clave", key_row)
        self.remember = QCheckBox("Recordar en este equipo (se guarda sin cifrar)")
        form.addRow("", self.remember)
        self.adv_btn = QPushButton("▸ Opciones avanzadas")
        self.adv_btn.setObjectName("link")
        self.adv_btn.setCheckable(True)
        self.adv_btn.toggled.connect(self._toggle_advanced)
        form.addRow("", self.adv_btn)
        self.model = QLineEdit()
        self.model_label = QLabel("Modelo")
        form.addRow(self.model_label, self.model)
        self.url = QLineEdit()
        self.url_label = QLabel("URL")
        form.addRow(self.url_label, self.url)
        self.gen_btn = QPushButton("✨  Generar preset")
        self.gen_btn.setObjectName("bigPrimary")
        self.gen_btn.setCursor(Qt.PointingHandCursor)
        self.gen_btn.clicked.connect(self.generate)
        form.addRow(self.gen_btn)
        return page

    # state ------------------------------------------------------------------------

    def _bank(self) -> bool:
        return self.bank_btn.isChecked()

    def _scope_changed(self) -> None:
        bank = self._bank()
        self.target.setText("Destino: " + (self.bank_target if bank else self.preset_target))
        self.scope_hint.setText("La IA crea 4 presets coherentes (A–D) y nombra el banco." if bank else
                                "La IA crea un solo preset para la posición seleccionada.")
        first = self.main.current // 4 + 1
        upload = " y subir" if self.main.connected and self.main.device is not None else ""
        self.apply_btn.setText(f"Aplicar{upload} al banco {first}" if bank
                               else f"Aplicar{upload} a {slot_name(self.main.current)}")
        self.prompt.setPlaceholderText("Ej.: banco para tocar rock de los 70: limpio, crunch, rítmica y solo" if bank
                                       else "Ej.: crunch cálido para riffs de rock clásico, con un poco de reverb")
        self.result = None
        self.apply_btn.setEnabled(False)
        self.waiting_clipboard = False
        self._set_step(0)
        self._show_empty("Los 4 presets propuestos aparecerán aquí." if bank else "El preset propuesto aparecerá aquí.")

    def _likes(self) -> list:
        first = self.main.current // 4 * 4
        return [self.main.local.presets[first + i] for i in range(4)]

    def _toggle_advanced(self, on: bool) -> None:
        self.adv_btn.setText(("▾" if on else "▸") + " Opciones avanzadas")
        compatible = self.provider.currentData() == "compatible"
        for w in (self.model, self.model_label):
            w.setVisible(on or compatible)
        for w in (self.url, self.url_label):
            w.setVisible(compatible)

    def _mode_changed(self) -> None:
        self.stack.setCurrentIndex(0 if self.web_card.isChecked() else 1)

    def _site(self) -> str:
        return next((s for s, b in self.site_buttons.items() if b.isChecked()), "Claude")

    def _site_changed(self) -> None:
        self.copy_btn.setText(f"Copiar instrucciones y abrir {self._site()}  ↗")

    def _set_step(self, current: int) -> None:
        """0 = nothing done yet, 1..3 = steps completed."""
        for i, (lab, text) in enumerate(self.step_labels):
            if i < current:
                mark, color = "✓", "#5dff9e"
            elif i == current:
                mark, color = f"{i + 1}", "#ffd36b"
            else:
                mark, color = f"{i + 1}", "#6b7480"
            lab.setText(f'<span style="color:{color}; font-weight:bold">{mark}</span> '
                        f'<span style="color:{"#e6e6e6" if i <= current else "#6b7480"}">{text}</span>')

    def _show_empty(self, text: str, error: bool = False) -> None:
        self._clear_result()
        lab = QLabel(("✗  " if error else "") + text)
        lab.setWordWrap(True)
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet(f"color: {'#ff7d8f' if error else '#6b7480'}; padding: 18px;")
        self.result_lay.addWidget(lab)

    def _clear_result(self) -> None:
        while self.result_lay.count():
            item = self.result_lay.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().hide()
                        sub.widget().deleteLater()

    def _show_result(self, preset, name: str, explanation: str) -> None:
        self._clear_result()
        g = preset.get
        head = QHBoxLayout()
        r, gr, b = preset.color
        swatch = QLabel()
        swatch.setFixedSize(18, 18)
        swatch.setStyleSheet(f"background: rgb({r},{gr},{b}); border-radius: 9px; border: 1px solid #000;")
        swatch.setToolTip("Color del LED")
        nm = QLabel(name)
        nm.setObjectName("resName")
        head.addWidget(swatch)
        head.addWidget(nm, 1)
        self.result_lay.addLayout(head)
        ex = QLabel(explanation)
        ex.setObjectName("resText")
        ex.setWordWrap(True)
        self.result_lay.addWidget(ex)

        def zone(key):
            return zone_of(FIELD_BY_KEY[key], g(key)).capitalize()

        def module(color, title, on, detail):
            state = "ON" if on else "OFF"
            lab = QLabel(f'<span style="color:{color if on else "#6b7480"}">●</span> <b>{title}</b> '
                         f'<span style="color:#8a96a3">{state}</span><br>'
                         f'<span style="color:{"#c8d0d8" if on else "#6b7480"}">{detail}</span>')
            lab.setObjectName("module")
            return lab
        grid = QGridLayout()
        grid.setSpacing(8)
        mods = [
            module("#ff5a36", "AMP", g("amp_on"), f"{AMP_MODELS[g('amp_type')]} · Gain {g('gain')} · "
                   f"T {g('treble')} M {g('middle')} B {g('bass')} · Vol {g('volume')}"),
            module("#f2f2f2", "GATE / CAB", True, f"Gate {g('gate')} · {CAB_MODELS[g('cab')]}"),
            module("#ffb627", "MOD", g("mod_on"), f"{zone('mod_fx')} · Speed {g('mod_speed')}"),
            module("#3cc8ff", "DELAY", g("dly_on"), f"{zone('dly_mix')} · Time {g('dly_time')}"),
            module("#b86bff", "REVERB", g("rvb_on"), f"{zone('rvb_decay')} · Mix {g('rvb_mix')}"),
        ]
        for i, m in enumerate(mods):
            grid.addWidget(m, i // 2, i % 2)
        self.result_lay.addLayout(grid)
        self.result_lay.addStretch()

    def _show_bank_result(self, bank_name: str, items: list) -> None:
        self._clear_result()
        nm = QLabel(bank_name or "Banco")
        nm.setObjectName("resName")
        self.result_lay.addWidget(nm)
        grid = QGridLayout()
        grid.setSpacing(8)
        first = self.main.current // 4 + 1
        for i, (preset, name, explanation) in enumerate(items):
            g = preset.get
            r, gr, b = preset.color
            fx = [lbl for key, lbl in (("mod_on", "MOD"), ("dly_on", "DELAY"), ("rvb_on", "REVERB")) if g(key)]
            short = explanation if len(explanation) <= 110 else explanation[:107] + "…"
            lab = QLabel(f'<span style="color:rgb({r},{gr},{b})">●</span> <b>{first}{"ABCD"[i]} · {name}</b><br>'
                         f'<span style="color:#ff8a6b">{AMP_MODELS[g("amp_type")]}</span> · Gain {g("gain")} · '
                         f'{CAB_MODELS[g("cab")]}<br>'
                         f'<span style="color:#8a96a3">{" + ".join(fx) if fx else "sin efectos"}</span><br>'
                         f'<span style="color:#c8d0d8">{short}</span>')
            lab.setObjectName("module")
            lab.setWordWrap(True)
            lab.setToolTip(explanation)
            grid.addWidget(lab, i // 2, i % 2)
        self.result_lay.addLayout(grid)
        self.result_lay.addStretch()

    # common -----------------------------------------------------------------------

    def _check_ready(self) -> str | None:
        text = self.prompt.toPlainText().strip()
        if not text:
            self.prompt.setFocus()
            self._show_empty("Escribe primero cómo quieres que suene (o elige una sugerencia).", error=True)
            return None
        if self.main.local is None:
            self._show_empty("Lee primero la pedalera o abre un banco.", error=True)
            return None
        return text

    def _save_settings(self) -> None:
        cfg = self._cfg()
        saved = dict(self.settings.ai)
        keys = dict(saved.get("keys", {}))
        if self.remember.isChecked() and cfg.api_key:
            keys[cfg.provider] = cfg.api_key
        elif not self.remember.isChecked():
            keys = {}
        self.settings.set_ai({"mode": "web" if self.web_card.isChecked() else "api", "site": self._site(),
                              "scope": "bank" if self._bank() else "preset",
                              "provider": cfg.provider, "model": cfg.model, "base_url": cfg.base_url,
                              "keys": keys})

    def _done(self, result) -> None:
        self.result = result
        self.waiting_clipboard = False
        self._set_step(3)
        if self._bank():
            self._show_bank_result(*result)
        else:
            self._show_result(*result)
        QApplication.processEvents()
        self.scroll.ensureWidgetVisible(self.result_card)
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("✨  Generar preset")
        self.apply_btn.setEnabled(True)
        self.activateWindow()

    def _failed(self, msg: str) -> None:
        self._show_empty(msg, error=True)
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("✨  Generar preset")

    def apply(self) -> None:
        if not self.result:
            return
        if self._bank():
            bank_name, items = self.result
            self.main.apply_generated_bank(self.main.current // 4, bank_name, items)
        else:
            preset, name, _ = self.result
            self.main.apply_generated(preset, name)
        self.accept()

    # browser mode -----------------------------------------------------------------

    def copy_and_open(self) -> None:
        text = self._check_ready()
        if text is None:
            return
        self._save_settings()
        prompt = ai.web_prompt(text, self.instrument.currentText(), self._bank(), dict(self.main.aliases.amps))
        QApplication.clipboard().setText(prompt)
        self.waiting_clipboard = True
        self.apply_btn.setEnabled(False)
        where = chatapps.open_chat(self._site(), lambda url: QDesktopServices.openUrl(QUrl(url)), prompt)
        self._set_step(1)
        if where == "shared":
            how = f"Las instrucciones ya están escritas en la app de {self._site()}: revisa y envía, luego copia la respuesta."
        else:
            how = (f"Pega con Ctrl+V en {'la app de ' + self._site() if where == 'app' else 'el chat'}, "
                   "envía y copia la respuesta.")
        self._show_empty(f"Esperando la respuesta de {self._site()}…\n{how}")

    def _clipboard_changed(self) -> None:
        if not self.waiting_clipboard or self.main.local is None:
            return
        text = QApplication.clipboard().text()
        found = ai.parse_bank_text(text) if self._bank() else ai.parse_design_text(text)
        if found is not None:
            self._from_text(text)

    def paste_answer(self) -> None:
        if self.main.local is not None:
            self._from_text(QApplication.clipboard().text())

    def _from_text(self, text: str) -> None:
        try:
            self._done(ai.bank_from_text(text, self._likes()) if self._bank() else
                       ai.from_text(text, self.main.local.presets[self.main.current]))
        except ai.AIError as e:
            self._failed(str(e))

    # API mode ---------------------------------------------------------------------

    def _cfg(self) -> ai.AIConfig:
        return ai.AIConfig(self.provider.currentData(), self.key.text().strip(),
                           self.model.text().strip(), self.url.text().strip())

    def _provider_changed(self) -> None:
        key = self.provider.currentData()
        p = ai.PROVIDERS[key]
        saved = self.settings.ai
        same = saved.get("provider") == key
        self.model.setPlaceholderText(p["model"])
        self.model.setText(saved.get("model", "") if same else "")
        self.url.setPlaceholderText(p["url"])
        self.url.setText(saved.get("base_url", "") if same else "")
        self.key.setText(saved.get("keys", {}).get(key, ""))
        self.key.setPlaceholderText("opcional" if key == "compatible" else f"sk-…  (o variable {p['env']})")
        link = self.KEY_URLS.get(key)
        self.key_link.setText(f'<a style="color:#5dd3ff" href="{link}">Conseguir clave ↗</a>' if link else
                              '<span style="color:#8a96a3">Ollama: «ollama pull llama3.1»</span>')
        self._toggle_advanced(self.adv_btn.isChecked())

    def generate(self) -> None:
        text = self._check_ready()
        if text is None:
            return
        self._save_settings()
        cfg, instrument = self._cfg(), self.instrument.currentText()
        like = self.main.local.presets[self.main.current]
        likes, bank = self._likes(), self._bank()
        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("Pensando el sonido…")
        self.apply_btn.setEnabled(False)
        self._show_empty("Pensando los 4 presets del banco…" if bank else "Pensando el sonido…")
        amps = dict(self.main.aliases.amps)   # uploaded models the AI may choose
        task = _Task(lambda: ai.generate_bank(cfg, text, instrument, likes, amps) if bank else
                     ai.generate(cfg, text, instrument, like, amps))
        _PENDING.add(task)
        task.signals.done.connect(lambda r: (_PENDING.discard(task), self.isVisible() and self._done(r)))
        task.signals.failed.connect(lambda m: (_PENDING.discard(task), self.isVisible() and self._failed(m)))
        QThreadPool.globalInstance().start(task)
