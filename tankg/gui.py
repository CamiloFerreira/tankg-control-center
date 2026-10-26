"""PySide6 desktop UI laid out like the Tank-G front panel.

Two banks are kept: `device` (last image read from the pedal) and `local` (working copy).
Presets that differ are marked until sent. The pedal is opened only for the duration of
each operation, so other programs (M-EFCS, DAWs, PipeWire) keep access to it.
"""
from __future__ import annotations

import ctypes.util
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMenu, QToolButton, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QSpinBox, QStyle, QToolBar, QVBoxLayout, QWidget,
)

from . import dialogs, library, templates, theme
from .device import DeviceError, TankG, find_devices
from .model import AMP_MODELS, CAB_MODELS, FIELD_BY_KEY, SLOTS, Bank, Preset, slot_name, zone_of

SECTION_COLORS = {
    "gate": "#f2f2f2", "amp": "#ff5a36", "mod": "#ffb627",
    "dly": "#3cc8ff", "rvb": "#b86bff", "cab": "#f2f2f2",
}
LIVE_DELAY_MS = 700

STYLE = """
/* Pedal panel and main-window specifics; shared rules live in theme.QSS. */
QFrame#browser { background: #1d2228; border-radius: 10px; }
QPushButton#bankHead {
    color: #8a96a3; font-weight: bold; text-align: left; border: none; padding: 0 2px; font-size: 11px;
}
QPushButton#bankHead:hover { color: #e6e6e6; }
QLineEdit#alias {
    background: transparent; color: #f4f4f4; border: none; border-bottom: 1px dashed #4a5561;
    font-size: 18px; padding: 2px 4px; min-width: 220px;
}
QLineEdit#alias:focus { border-bottom: 1px solid #1f9e6e; }
QLabel#bankTag { color: #8a96a3; font-size: 12px; }
QPushButton#slot {
    background: #262d35; color: #e6e6e6; border: 2px solid #333c46; border-radius: 6px;
    padding: 1px; text-align: center; font-size: 10px;
}
QPushButton#slot:hover { background: #2e3742; }
QFrame#pedal {
    border-radius: 14px; border: 1px solid #0f4f4e;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #34a9a6, stop:1 #1f7f7d);
}
QLabel#knobLabel { color: #10302f; font-size: 10px; font-weight: bold; }
QLabel#zone { color: #0d2e2d; font-size: 10px; }
QLabel#sectionTitle { color: #0d2e2d; font-weight: bold; letter-spacing: 1px; }
QFrame#section { background: rgba(0,0,0,0.08); border-radius: 10px; }
QSpinBox {
    background: #10181b; color: #f0f0f0; border: 1px solid #0c3b3a; border-radius: 4px; font-weight: bold;
}
QSpinBox::up-button, QSpinBox::down-button { width: 0px; border: none; }
QLabel#display {
    background: #050708; color: #ff3b30; border-radius: 6px; padding: 4px 12px;
    font-family: monospace; font-size: 30px; font-weight: bold;
}
QPushButton#foot {
    background: qradialgradient(cx:0.5, cy:0.4, radius:0.6, stop:0 #c9ccd1, stop:1 #5d6168);
    border: 4px solid #3a3f45; border-radius: 34px; min-width: 68px; max-width: 68px;
    min-height: 68px; max-height: 68px; color: #111; font-weight: bold;
}
QLabel#footLabel { color: #0d2e2d; font-weight: bold; }
QPushButton#bank {
    background: #1b5e5c; color: #e9fffe; border-radius: 6px; padding: 6px 12px; font-weight: bold;
}
QLabel#presetTitle { font-size: 22px; font-weight: bold; color: #f4f4f4; }
QLabel#badge { background: #6b4e00; color: #ffd36b; border-radius: 8px; padding: 2px 8px; }
QLabel#conn { border-radius: 8px; padding: 2px 10px; font-weight: bold; }
"""


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class Job(QRunnable):
    """Runs fn(dev, report) with a freshly opened TankG in a worker thread."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            dev = TankG.open()
            try:
                result = self.fn(dev, self.signals.progress.emit)
            finally:
                dev.close()
            self.signals.done.emit(result)
        except DeviceError as e:
            self.signals.failed.emit(str(e))
        except Exception:  # noqa: BLE001 - surface unexpected errors to the user
            self.signals.failed.emit(traceback.format_exc())


# widgets -------------------------------------------------------------------------

class Led(QLabel):
    def __init__(self, color: str):
        super().__init__()
        self.color = color
        self.setFixedSize(12, 12)
        self.set_on(False)

    def set_on(self, on: bool) -> None:
        c = self.color if on else "#0b2423"
        glow = f"border: 1px solid {self.color};" if on else "border: 1px solid #0a1d1c;"
        self.setStyleSheet(f"background: {c}; border-radius: 6px; {glow}")


class Knob(QWidget):
    """A front-panel control: label, LED, vertical slider and numeric input."""
    changed = Signal(str, int)

    def __init__(self, key: str, section: str):
        super().__init__()
        self.field = FIELD_BY_KEY[key]
        self._loading = False
        color = SECTION_COLORS[section]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(4)
        self.led = Led(color)
        label = QLabel(self.field.label)
        label.setObjectName("knobLabel")
        label.setAlignment(Qt.AlignCenter)
        tip = "Verificado." if self.field.verified else \
            "Posición del byte deducida del manual y de datos reales; pendiente de calibrar."
        label.setToolTip(f"{self.field.label}: byte {self.field.offset}. {tip}")
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, self.field.maximum)
        self.slider.setMinimumHeight(120)
        self.slider.setStyleSheet(STYLE_SLIDER.replace("VAR_COLOR", color))
        self.spin = QSpinBox()
        self.spin.setRange(0, self.field.maximum)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setFixedWidth(44)
        self.zone = QLabel("")
        self.zone.setObjectName("zone")
        self.zone.setAlignment(Qt.AlignCenter)
        self.zone.setVisible(bool(self.field.zones))
        if self.field.zones:
            self.zone.setToolTip("Tipo aproximado: la perilla se divide en 3 tramos "
                                 f"({' / '.join(self.field.zones)}). Límites exactos sin calibrar.")
        lay.addWidget(self.led, 0, Qt.AlignHCenter)
        lay.addWidget(label)
        lay.addWidget(self.slider, 1, Qt.AlignHCenter)
        lay.addWidget(self.spin, 0, Qt.AlignHCenter)
        lay.addWidget(self.zone)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def set_value(self, v: int) -> None:
        self._loading = True
        self.slider.setValue(v)
        self.spin.setValue(v)
        self._update_zone(v)
        self._loading = False

    def _update_zone(self, v: int) -> None:
        if self.field.zones:
            self.zone.setText("≈ " + zone_of(self.field, v))

    def _from_slider(self, v: int) -> None:
        if not self._loading:
            self.spin.blockSignals(True)
            self.spin.setValue(v)
            self.spin.blockSignals(False)
            self._update_zone(v)
            self.changed.emit(self.field.key, v)

    def _from_spin(self, v: int) -> None:
        if not self._loading:
            self.slider.blockSignals(True)
            self.slider.setValue(v)
            self.slider.blockSignals(False)
            self._update_zone(v)
            self.changed.emit(self.field.key, v)


class Selector(QWidget):
    """TYPE / IR CAB: a stepped knob shown as a drop-down list."""
    changed = Signal(str, int)

    def __init__(self, key: str, items: list[str], section: str):
        super().__init__()
        self.field = FIELD_BY_KEY[key]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(4)
        self.led = Led(SECTION_COLORS[section])
        label = QLabel(self.field.label)
        label.setObjectName("knobLabel")
        label.setAlignment(Qt.AlignCenter)
        label.setToolTip(f"{self.field.label}: byte {self.field.offset}. Verificado con la lista oficial.")
        self.combo = QComboBox()
        self.combo.addItems(items)
        self.combo.setMinimumWidth(108)
        lay.addWidget(self.led, 0, Qt.AlignHCenter)
        lay.addWidget(label)
        lay.addStretch()
        lay.addWidget(self.combo)
        lay.addStretch()
        self.combo.currentIndexChanged.connect(lambda i: self.changed.emit(self.field.key, i))

    def set_value(self, v: int) -> None:
        self.combo.blockSignals(True)
        if 0 <= v < self.combo.count():
            self.combo.setCurrentIndex(v)
        self.combo.blockSignals(False)


class Section(QFrame):
    """A group of controls with an optional module on/off switch (footswitch in LIVE mode)."""
    toggled = Signal(str, int)

    def __init__(self, title: str, section: str, switch_key: str | None = None):
        super().__init__()
        self.setObjectName("section")
        self.section = section
        self.switch_key = switch_key
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 8)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("sectionTitle")
        head.addWidget(t)
        head.addStretch()
        self.switch = None
        if switch_key:
            self.switch = QPushButton("ON")
            self.switch.setCheckable(True)
            self.switch.setFixedWidth(46)
            self.switch.setToolTip(f"Módulo encendido/apagado (byte {FIELD_BY_KEY[switch_key].offset}, "
                                   "deducido; pendiente de calibrar)")
            self.switch.toggled.connect(self._toggled)
            head.addWidget(self.switch)
        outer.addLayout(head)
        self.row = QHBoxLayout()
        self.row.setSpacing(6)
        outer.addLayout(self.row, 1)
        self.controls: list = []

    def add(self, w) -> None:
        self.controls.append(w)
        self.row.addWidget(w)

    def _toggled(self, on: bool) -> None:
        self._style_switch(on)
        self.toggled.emit(self.switch_key, int(on))

    def _style_switch(self, on: bool) -> None:
        c = SECTION_COLORS[self.section]
        self.switch.setText("ON" if on else "OFF")
        self.switch.setStyleSheet(
            f"background: {c}; color: #111; border-radius: 6px; font-weight: bold;" if on else
            "background: #0e2b2a; color: #6c8f8e; border-radius: 6px; font-weight: bold;")

    def set_on(self, on: bool) -> None:
        if self.switch:
            self.switch.blockSignals(True)
            self.switch.setChecked(on)
            self.switch.blockSignals(False)
            self._style_switch(on)
        for c in self.controls:
            c.led.set_on(on)


def two_lines(text: str, width: int = 9) -> str:
    """Wrap a short name onto at most two lines of `width` characters."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    lines = [l if len(l) <= width else l[:width - 1] + "…" for l in lines]
    if len(lines) > 2:
        lines = [lines[0], lines[1][:width - 1] + "…"]
    return "\n".join(lines)


class SlotButton(QPushButton):
    def __init__(self, slot: int):
        super().__init__()
        self.slot = slot
        self.setObjectName("slot")
        self.setMinimumSize(QSize(52, 40))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def show_preset(self, p: Preset | None, selected: bool, modified: bool, alias: str = "") -> None:
        amp = p.amp_name if p else "—"
        self.setText(two_lines(alias or amp) + (" •" if modified else ""))
        r, g, b = p.color if p else (60, 70, 80)
        border = "#ffffff" if selected else f"rgb({r},{g},{b})"
        bg = "#2f4f5c" if selected else "#262d35"
        self.setStyleSheet(f"QPushButton#slot {{ border: 2px solid {border}; background: {bg}; }}")
        tip = f"Preset {slot_name(self.slot)}" + (f" — {alias}" if alias else "")
        if p:
            tip += f"\n{p.amp_name} / {p.cab_name}"
        self.setToolTip(tip + ("\nModificado, sin guardar en la pedalera" if modified else ""))


STYLE_SLIDER = """
QSlider::groove:vertical { background: #0e2b2a; width: 6px; border-radius: 3px; }
QSlider::sub-page:vertical { background: #0e2b2a; border-radius: 3px; }
QSlider::add-page:vertical { background: VAR_COLOR; border-radius: 3px; }
QSlider::handle:vertical {
    background: qradialgradient(cx:0.4, cy:0.4, radius:0.7, stop:0 #4a4f55, stop:1 #111);
    border: 2px solid #0a0a0a; height: 22px; margin: 0 -9px; border-radius: 12px;
}
"""


# main window -------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tank-G Control Center")
        self.resize(1440, 860)
        self.pool = QThreadPool.globalInstance()
        self.aliases = library.Aliases()
        self.device: Bank | None = None
        self.local: Bank | None = None
        self.current = 0
        self.clipboard: Preset | None = None
        self.undo_stack: list[Bank] = []
        self.busy = False
        self._jobs: set[Job] = set()
        self.connected = False
        self.session_backup_done = False
        self.live_timer = QTimer(self)
        self.live_timer.setSingleShot(True)
        self.live_timer.timeout.connect(self._live_send)

        root = QWidget()
        root.setObjectName("root")
        main = QHBoxLayout(root)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(10)
        main.addWidget(self._build_browser())
        main.addWidget(self._build_editor(), 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

        self.conn = QLabel()
        self.conn.setObjectName("conn")
        self.statusBar().addPermanentWidget(self.conn)
        self._build_toolbar()
        self._build_menus()
        self.refresh()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_device)
        self.timer.start(2000)
        self._poll_device()

    # layout --------------------------------------------------------------------------

    def _build_browser(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("browser")
        frame.setFixedWidth(252)
        lay = QVBoxLayout(frame)
        title = QLabel("PRESETS")
        title.setObjectName("sectionTitle")
        title.setStyleSheet("color: #8a96a3;")
        lay.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        self.slot_buttons: list[SlotButton] = []
        self.bank_heads: list[QPushButton] = []
        for letter in range(4):
            col = QLabel("ABCD"[letter])
            col.setAlignment(Qt.AlignCenter)
            col.setStyleSheet("color: #8a96a3; font-weight: bold;")
            grid.addWidget(col, 0, letter)
        for bank in range(9):
            head = QPushButton()
            head.setObjectName("bankHead")
            head.setCursor(Qt.PointingHandCursor)
            head.setToolTip("Clic para poner nombre al banco")
            head.clicked.connect(lambda _=False, n=bank: self.rename_bank(n))
            grid.addWidget(head, bank * 2 + 1, 0, 1, 4)
            self.bank_heads.append(head)
            for letter in range(4):
                b = SlotButton(bank * 4 + letter)
                b.clicked.connect(lambda _=False, s=b.slot: self.select_slot(s))
                grid.addWidget(b, bank * 2 + 2, letter)
                self.slot_buttons.append(b)
            grid.setRowMinimumHeight(bank * 2 + 1, 18)
        lay.addLayout(grid)
        lay.addStretch()
        hint = QLabel("• sin guardar · borde = color LED")
        hint.setStyleSheet("color: #6b7480; font-size: 11px;")
        lay.addWidget(hint)
        return frame

    def _build_editor(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        head = QHBoxLayout()
        self.title = QLabel("1A")
        self.title.setObjectName("presetTitle")
        self.alias_edit = QLineEdit()
        self.alias_edit.setObjectName("alias")
        self.alias_edit.setPlaceholderText("Nombre del preset…")
        self.alias_edit.setMaxLength(40)
        self.alias_edit.setToolTip("Nombre solo para esta aplicación (la pedalera no guarda nombres)")
        self.alias_edit.editingFinished.connect(self._alias_edited)
        self.bank_tag = QLabel()
        self.bank_tag.setObjectName("bankTag")
        self.badge = QLabel("modificado")
        self.badge.setObjectName("badge")
        self.ai_btn = QPushButton("✨ Crear con IA")
        self.ai_btn.setObjectName("primary")
        self.ai_btn.setToolTip("Describe un sonido y la IA (Claude, ChatGPT o un modelo local) crea el preset")
        self.ai_btn.clicked.connect(self.open_ai)
        self.color_btn = QPushButton("Color LED")
        self.color_btn.setObjectName("action")
        self.color_btn.setToolTip("Color del interruptor de este preset (bytes 18-20, deducido)")
        self.color_btn.clicked.connect(self.pick_color)
        self.revert_btn = QPushButton("Revertir")
        self.revert_btn.setObjectName("action")
        self.revert_btn.clicked.connect(self.revert_selected)
        self.send_btn = QPushButton("Guardar preset")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send_selected)
        head.addWidget(self.title)
        head.addWidget(self.alias_edit)
        head.addWidget(self.bank_tag)
        head.addWidget(self.badge)
        head.addStretch()
        head.addWidget(self.ai_btn)
        head.addWidget(self.color_btn)
        head.addWidget(self.revert_btn)
        head.addWidget(self.send_btn)
        lay.addLayout(head)

        pedal = QFrame()
        pedal.setObjectName("pedal")
        pl = QVBoxLayout(pedal)
        pl.setContentsMargins(14, 12, 14, 14)
        brand = QHBoxLayout()
        logo = QLabel("M-VAVE")
        logo.setStyleSheet("color: #39ff7a; background: #0a0f10; border-radius: 4px; padding: 2px 8px;"
                           "font-weight: bold;")
        name = QLabel("TANK-G")
        name.setStyleSheet("color: #0d2e2d; font-size: 20px; font-weight: bold; letter-spacing: 3px;")
        brand.addWidget(logo)
        brand.addStretch()
        brand.addWidget(name)
        pl.addLayout(brand)

        knobs = QHBoxLayout()
        knobs.setSpacing(6)
        self.sections: list[Section] = []
        self.controls: dict[str, QWidget] = {}

        def section(title, sec, switch, items):
            s = Section(title, sec, switch)
            for it in items:
                s.add(it)
                self.controls[it.field.key] = it
                it.changed.connect(self._field_changed)
            s.toggled.connect(self._field_changed)
            self.sections.append(s)
            knobs.addWidget(s, len(items))
            return s

        section("GATE", "gate", None, [Knob("gate", "gate")])
        section("AMP", "amp", "amp_on", [
            Selector("amp_type", [f"{i + 1}. {n}" for i, n in enumerate(AMP_MODELS)], "amp"),
            Knob("gain", "amp"), Knob("treble", "amp"), Knob("middle", "amp"),
            Knob("bass", "amp"), Knob("volume", "amp")])
        section("MOD", "mod", "mod_on", [Knob("mod_fx", "mod"), Knob("mod_speed", "mod")])
        section("DELAY", "dly", "dly_on", [Knob("dly_mix", "dly"), Knob("dly_time", "dly")])
        section("REVERB", "rvb", "rvb_on", [Knob("rvb_decay", "rvb"), Knob("rvb_mix", "rvb")])
        section("CAB", "cab", None, [
            Selector("cab", [n if i == 0 else f"{i}. {n}" for i, n in enumerate(CAB_MODELS)], "cab")])
        pl.addLayout(knobs, 1)

        feet = QHBoxLayout()
        feet.setSpacing(18)
        self.foot_buttons = {}
        bank_minus = QPushButton("◀ BANK −")
        bank_minus.setObjectName("bank")
        bank_minus.clicked.connect(lambda: self.select_slot((self.current - 4) % SLOTS))
        bank_plus = QPushButton("BANK + ▶")
        bank_plus.setObjectName("bank")
        bank_plus.clicked.connect(lambda: self.select_slot((self.current + 4) % SLOTS))
        self.display = QLabel("1A")
        self.display.setObjectName("display")
        self.display.setAlignment(Qt.AlignCenter)

        def foot(letter: str, label: str) -> QWidget:
            box = QVBoxLayout()
            b = QPushButton(letter)
            b.setObjectName("foot")
            b.setToolTip(f"Seleccionar el preset {letter} del banco actual y activarlo en la pedalera")
            b.clicked.connect(lambda: self.foot_pressed("ABCD".index(letter)))
            self.foot_buttons[letter] = b
            lab = QLabel(f"{letter}/{label}")
            lab.setObjectName("footLabel")
            lab.setAlignment(Qt.AlignCenter)
            box.addWidget(b, 0, Qt.AlignHCenter)
            box.addWidget(lab)
            holder = QWidget()
            holder.setLayout(box)
            return holder

        feet.addWidget(foot("A", "REVERB"))
        feet.addWidget(bank_minus)
        feet.addWidget(foot("B", "DELAY"))
        feet.addStretch()
        feet.addWidget(self.display)
        feet.addStretch()
        feet.addWidget(foot("C", "MOD"))
        feet.addWidget(bank_plus)
        feet.addWidget(foot("D", "AMP"))
        pl.addLayout(feet)
        lay.addWidget(pedal, 1)

        note = QLabel("TYPE e IR CAB verificados con la lista oficial. El resto de controles siguen el "
                      "manual; su posición en la memoria está deducida y pendiente de calibrar (ver tooltip). "
                      "MASTER es global y no se guarda en el preset.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #7d8793; font-size: 11px;")
        lay.addWidget(note)
        return w

    def _build_toolbar(self) -> None:
        tb = QToolBar("Principal")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        icon = self.style().standardIcon

        def add(text, fn, ic, tip=""):
            a = QAction(icon(ic), text, self)
            a.triggered.connect(fn)
            a.setToolTip(tip or text)
            tb.addAction(a)
            return a

        add("Leer pedalera", self.read_device, QStyle.SP_BrowserReload, "Leer los 36 presets (F5)")
        self.send_all_action = add("Guardar todo", self.send_all, QStyle.SP_DialogSaveButton,
                                   "Enviar a la pedalera todos los presets modificados (Ctrl+Enter)")
        tb.addSeparator()
        add("Deshacer", self.undo, QStyle.SP_ArrowBack, "Ctrl+Z")
        add("Copiar", self.copy_preset, QStyle.SP_FileDialogDetailedView, "Ctrl+C")
        add("Pegar", self.paste_preset, QStyle.SP_FileDialogContentsView, "Ctrl+V")
        add("Intercambiar", self.swap_preset, QStyle.SP_BrowserStop, "Intercambiar con otro slot")
        add("Fábrica", self.factory_selected, QStyle.SP_DialogResetButton, "Restaurar el preset de fábrica")
        tpl = QToolButton()
        tpl.setText("Plantilla")
        tpl.setIcon(icon(QStyle.SP_FileIcon))
        tpl.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tpl.setPopupMode(QToolButton.InstantPopup)
        tpl.setToolTip("Reemplazar este preset por una plantilla")
        tpl.setMenu(self._template_menu())
        tb.addWidget(tpl)
        tb.addSeparator()
        add("Backup", self.backup_device, QStyle.SP_DriveHDIcon, "Backup del banco de la pedalera (Ctrl+B)")
        tb.addSeparator()
        self.live_action = QAction(icon(QStyle.SP_MediaVolume), "Escucha en vivo", self)
        self.live_action.setCheckable(True)
        self.live_action.setToolTip("Cada cambio se guarda en la pedalera y se activa el preset para oírlo "
                                    "al momento (escribe en la memoria de la pedalera)")
        self.live_action.toggled.connect(self._live_toggled)
        tb.addAction(self.live_action)

    def _action(self, menu, text, fn, shortcut=None):
        a = QAction(text, self)
        a.triggered.connect(fn)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        menu.addAction(a)
        return a

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&Archivo")
        self._action(m, "Abrir banco...", self.open_bank, "Ctrl+O")
        self._action(m, "Guardar banco como...", self.save_bank, "Ctrl+S")
        m.addSeparator()
        self._action(m, "Importar preset...", self.import_preset, "Ctrl+I")
        self._action(m, "Exportar preset...", self.export_preset, "Ctrl+E")
        m.addSeparator()
        self._action(m, "Exportar banco actual (4 presets con nombres)...", self.export_bank_set)
        self._action(m, "Importar banco (.tgset) en el banco actual...", self.import_bank_set)
        m.addSeparator()
        self._action(m, "Comparar con archivo de banco...", self.compare_file)
        self._action(m, "Salir", self.close, "Ctrl+Q")
        m = mb.addMenu("&Pedalera")
        self._action(m, "Leer presets", self.read_device, "F5")
        self._action(m, "Guardar todos los cambios", self.send_all, "Ctrl+Return")
        self._action(m, "Guardar este preset", self.send_selected, "Ctrl+Shift+Return")
        self._action(m, "Activar este preset", self.activate_selected, "Ctrl+Space")
        m.addSeparator()
        self._action(m, "Backup de la pedalera", self.backup_device, "Ctrl+B")
        self._action(m, "Restaurar banco desde archivo...", self.restore_to_device)
        self._action(m, "Gestor de backups...", lambda: dialogs.BackupManager(self).exec())
        self._action(m, "Puerto MIDI...", self.choose_midi_port)
        m.addSeparator()
        self._action(m, "Asistente de calibración...", lambda: dialogs.CalibrationWizard(self).exec())
        m = mb.addMenu("&Editar")
        self._action(m, "Deshacer", self.undo, "Ctrl+Z")
        m.addSeparator()
        self._action(m, "Copiar preset", self.copy_preset, "Ctrl+C")
        self._action(m, "Pegar preset", self.paste_preset, "Ctrl+V")
        self._action(m, "Duplicar en otro slot...", self.duplicate_preset, "Ctrl+D")
        self._action(m, "Intercambiar con otro slot...", self.swap_preset)
        self._action(m, "Renombrar preset", lambda: self.alias_edit.setFocus(), "F2")
        self._action(m, "Renombrar banco...", lambda: self.rename_bank(self.current // 4), "Shift+F2")
        self._action(m, "Mover a la izquierda", lambda: self.move_preset(-1), "Alt+Left")
        self._action(m, "Mover a la derecha", lambda: self.move_preset(1), "Alt+Right")
        m.addSeparator()
        self._action(m, "Crear preset con IA...", self.open_ai, "Ctrl+K")
        m.addMenu(self._template_menu())
        self._action(m, "Restaurar preset de fábrica", self.factory_selected)
        self._action(m, "Restaurar banco actual de fábrica", self.factory_current_bank)
        self._action(m, "Restaurar los 36 presets de fábrica", self.factory_all)
        self._action(m, "Revertir este preset", self.revert_selected)
        self._action(m, "Revertir todo", self.revert_all)
        m = mb.addMenu("A&yuda")
        self._action(m, "Bytes del preset", self.show_bytes)
        self._action(m, "Acerca de", self.about)

    # state ---------------------------------------------------------------------------

    def modified_slots(self) -> list[int]:
        if self.local is None or self.device is None:
            return []
        return self.local.diff_slots(self.device)

    def _push_undo(self) -> None:
        if self.local is not None:
            self.undo_stack.append(self.local.copy())
            del self.undo_stack[:-200]

    def _set_local(self, slot: int, preset: Preset) -> None:
        self._push_undo()
        self.local.presets[slot] = preset.copy()
        self.refresh()
        self._schedule_live()

    def refresh(self) -> None:
        modified = set(self.modified_slots())
        for b in self.slot_buttons:
            p = self.local.presets[b.slot] if self.local else None
            b.show_preset(p, b.slot == self.current, b.slot in modified, self.aliases.preset(b.slot))
        for n, head in enumerate(self.bank_heads):
            alias = self.aliases.bank(n)
            head.setText(f"BANCO {n + 1}" + (f" · {alias}" if alias else ""))
        name = slot_name(self.current)
        self.title.setText(name)
        if not self.alias_edit.hasFocus():
            self.alias_edit.setText(self.aliases.preset(self.current))
        bank_alias = self.aliases.bank(self.current // 4)
        self.bank_tag.setText(f"Banco {self.current // 4 + 1}" + (f" · {bank_alias}" if bank_alias else ""))
        self.bank_tag.setMinimumWidth(self.bank_tag.sizeHint().width())
        self.display.setText(name)
        self.badge.setVisible(self.current in modified)
        self.revert_btn.setEnabled(self.current in modified)
        self.send_btn.setEnabled(self.current in modified)
        self.send_all_action.setToolTip(f"Guardar en la pedalera {len(modified)} preset(s) modificados (Ctrl+Enter)")
        self.send_all_action.setEnabled(bool(modified))
        p = self.local.presets[self.current] if self.local else None
        for key, ctrl in self.controls.items():
            ctrl.setEnabled(p is not None)
            if p is not None:
                ctrl.set_value(p.get(key))
        for s in self.sections:
            s.setEnabled(p is not None)
            on = p is not None and (s.switch_key is None or bool(p.get(s.switch_key)))
            if s.section == "gate":
                on = p is not None and p.get("gate") > 0
            if s.section == "cab":
                on = p is not None and p.get("cab") > 0
            s.set_on(on)
        if p is not None:
            r, g, b = p.color
            text = "#111" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#fff"
            self.color_btn.setStyleSheet(f"background: rgb({r},{g},{b}); color: {text}; border-radius: 6px;"
                                         "padding: 6px 12px;")
        letter = self.current % 4
        for i, l in enumerate("ABCD"):
            lit = i == letter and p is not None
            r, g, b = p.color if lit else (0, 0, 0)
            ring = f"rgb({r},{g},{b})" if lit else "#3a3f45"
            self.foot_buttons[l].setStyleSheet(f"QPushButton#foot {{ border: 4px solid {ring}; }}")
        self._update_status()

    def _update_status(self) -> None:
        if self.connected:
            self.conn.setText("● Tank-G conectada")
            self.conn.setStyleSheet("background: #12402c; color: #5dff9e;")
        else:
            self.conn.setText("● Tank-G desconectada")
            self.conn.setStyleSheet("background: #40121a; color: #ff7d8f;")
        n = len(self.modified_slots())
        self.setWindowTitle("Tank-G Control Center" + (f" — {n} sin guardar" if n else ""))

    def _need_local(self) -> bool:
        if self.local is None:
            QMessageBox.information(self, "Sin datos", "Conecta la pedalera y pulsa «Leer pedalera», "
                                    "o abre un archivo de banco.")
            return False
        return True

    def _ask_slot(self, title: str, exclude: int | None = None) -> int | None:
        names = [slot_name(i) for i in range(SLOTS) if i != exclude]
        name, ok = QInputDialog.getItem(self, title, "Slot destino:", names, 0, False)
        return [slot_name(i) for i in range(SLOTS)].index(name) if ok else None

    # interactions --------------------------------------------------------------------

    def select_slot(self, slot: int) -> None:
        self.current = slot
        self.refresh()

    def foot_pressed(self, letter: int) -> None:
        self.select_slot(self.current // 4 * 4 + letter)
        if self.connected:
            self.activate_selected(quiet=True)

    def _field_changed(self, key: str, value: int) -> None:
        if self.local is None:
            return
        p = self.local.presets[self.current].copy()
        if p.get(key) == value:
            return
        p.set(key, value)
        self._set_local(self.current, p)

    def _alias_edited(self) -> None:
        if self.alias_edit.text().strip() != self.aliases.preset(self.current):
            self.aliases.set_preset(self.current, self.alias_edit.text())
            self.refresh()

    def rename_bank(self, bank: int) -> None:
        name, ok = QInputDialog.getText(self, f"Banco {bank + 1}", "Nombre del banco (vacío = sin nombre):",
                                        text=self.aliases.bank(bank))
        if ok:
            self.aliases.set_bank(bank, name)
            self.refresh()

    def pick_color(self) -> None:
        if not self._need_local():
            return
        p = self.local.presets[self.current].copy()
        c = QColorDialog.getColor(QColor(*p.color), self, f"Color LED de {slot_name(self.current)}")
        if c.isValid():
            p.color = (c.red(), c.green(), c.blue())
            self._set_local(self.current, p)

    # background jobs -------------------------------------------------------------------

    def _run(self, fn, on_done, label: str, quiet_errors: bool = False) -> bool:
        if self.busy:
            return False
        self.busy = True
        self.statusBar().showMessage(label)
        job = Job(fn)
        job.setAutoDelete(False)
        self._jobs.add(job)   # keep the runnable and its signals alive until it reports back
        job.signals.done.connect(lambda r: (self._jobs.discard(job), self._job_done(on_done, r)))
        job.signals.failed.connect(lambda m: (self._jobs.discard(job), self._job_failed(m, quiet_errors)))
        job.signals.progress.connect(self.statusBar().showMessage)
        self.pool.start(job)
        return True

    def _job_done(self, on_done, result) -> None:
        self.busy = False
        self.statusBar().clearMessage()
        on_done(result)
        self.refresh()

    def _job_failed(self, msg: str, quiet: bool) -> None:
        self.busy = False
        self.statusBar().clearMessage()
        if quiet:
            self.statusBar().showMessage(f"Error: {msg}", 8000)
        else:
            QMessageBox.critical(self, "Error", msg)
        self.refresh()

    def choose_midi_port(self) -> None:
        if dialogs.MidiPortDialog(self).exec():
            self.connected = False
            self.device = None if not self.modified_slots() else self.device
            self._poll_device()

    def _poll_device(self) -> None:
        was = self.connected
        self.connected = bool(find_devices())
        if not self.connected and not self.statusBar().currentMessage():
            self.statusBar().showMessage("No se detecta la Tank-G. Si está conectada, elige el puerto en "
                                         "Pedalera → Puerto MIDI…")
        if self.connected != was:
            self.statusBar().showMessage("Tank-G conectada" if self.connected else "Tank-G desconectada", 4000)
            if self.connected and self.device is None:
                self.read_device()
        self._update_status()

    def read_device(self) -> None:
        if self.modified_slots() and not dialogs.ask(
                self, "Leer pedalera", "Hay cambios sin guardar. ¿Descartarlos y leer la pedalera?"):
            return

        def done(bank: Bank) -> None:
            self.device = bank
            if self.local is not None:
                self._push_undo()
            self.local = bank.copy()
            self.statusBar().showMessage("Presets leídos de la pedalera", 4000)

        if not self._run(lambda dev, _: dev.read_bank(), done, "Leyendo presets..."):
            QMessageBox.information(self, "Ocupado", "Hay una operación en curso.")

    def _write_job(self, slots: list[int], select: int | None):
        target = self.local.copy()
        need_backup = not self.session_backup_done

        def work(dev: TankG, report):
            current = dev.read_bank()
            path = str(library.backup(current, "auto")) if need_backup else None
            after = dev.write_presets(
                target, slots, lambda n, total, s: report(f"Guardando {slot_name(s)} ({n + 1}/{total})..."))
            if select is not None:
                dev.select_preset(select)
            return after, path
        return work

    def _apply_written(self, slots: list[int], result) -> str:
        after, path = result
        if path:
            self.session_backup_done = True
        self.device = after
        return path or ""

    def _send(self, slots: list[int], select: int | None = None, confirm: bool = True) -> None:
        if not slots:
            return
        names = ", ".join(slot_name(s) for s in slots)
        if confirm and len(slots) > 1 and not dialogs.ask(
                self, "Guardar en la pedalera",
                f"Se sobrescribirán en la pedalera: {names}\n¿Continuar?"):
            return

        def done(result) -> None:
            path = self._apply_written(slots, result)
            msg = f"Guardado y verificado: {names}"
            self.statusBar().showMessage(msg + (f" · backup previo: {path}" if path else ""), 8000)

        if not self._run(self._write_job(slots, select), done, "Guardando..."):
            QMessageBox.information(self, "Ocupado", "Hay una operación en curso.")

    def send_all(self) -> None:
        if self._need_local() and self.device is not None:
            self._send(self.modified_slots())

    def send_selected(self) -> None:
        if self._need_local() and self.current in self.modified_slots():
            self._send([self.current], select=self.current)

    def activate_selected(self, quiet: bool = False) -> None:
        s = self.current
        if s in self.modified_slots() and not quiet:
            self.statusBar().showMessage("Este preset tiene cambios sin guardar: suena la versión de la pedalera.",
                                         5000)
        self._run(lambda dev, _: dev.select_preset(s),
                  lambda _: self.statusBar().showMessage(f"Preset {slot_name(s)} activo en la pedalera", 3000),
                  f"Activando {slot_name(s)}...", quiet_errors=True)

    # live audition -----------------------------------------------------------------

    def _live_toggled(self, on: bool) -> None:
        if on and not dialogs.ask(
                self, "Escucha en vivo",
                "Cada cambio se guardará en la memoria de la pedalera y se activará el preset para que lo "
                "oigas al momento.\nAntes del primer cambio se hace un backup automático.\n\n¿Activar?"):
            self.live_action.setChecked(False)
            return
        if on:
            self._schedule_live()

    def _schedule_live(self) -> None:
        if self.live_action.isChecked() and self.connected and self.device is not None:
            self.live_timer.start(LIVE_DELAY_MS)

    def _live_send(self) -> None:
        if self.local is None or self.device is None:
            return
        if self.busy:
            self.live_timer.start(LIVE_DELAY_MS)
            return
        slot = self.current
        if slot not in self.modified_slots():
            return
        self._run(self._write_job([slot], slot),
                  lambda r: (self._apply_written([slot], r),
                             self.statusBar().showMessage(f"{slot_name(slot)} actualizado en la pedalera", 2500)),
                  f"Enviando {slot_name(slot)}...", quiet_errors=True)

    # bank operations -----------------------------------------------------------------

    def backup_device(self) -> None:
        self._run(lambda dev, _: str(library.backup(dev.read_bank(), "manual")),
                  lambda path: QMessageBox.information(self, "Backup", f"Banco guardado en:\n{path}"),
                  "Haciendo backup...")

    def restore_to_device(self) -> None:
        if self.device is None:
            QMessageBox.information(self, "Restaurar", "Lee primero la pedalera.")
            return
        bank = self._open_bank_dialog("Restaurar banco")
        if bank is None:
            return
        self._push_undo()
        self.local = bank
        self.refresh()
        self._send(self.modified_slots())

    def undo(self) -> None:
        if self.undo_stack:
            self.local = self.undo_stack.pop()
            self.refresh()
            self._schedule_live()

    def copy_preset(self) -> None:
        if self._need_local():
            self.clipboard = self.local.presets[self.current].copy()
            self.statusBar().showMessage(f"Preset {slot_name(self.current)} copiado", 3000)

    def paste_preset(self) -> None:
        if self._need_local() and self.clipboard is not None:
            self._set_local(self.current, self.clipboard)

    def duplicate_preset(self) -> None:
        if not self._need_local():
            return
        d = self._ask_slot("Duplicar preset", self.current)
        if d is not None:
            src = self.local.presets[self.current]
            alias = self.aliases.preset(self.current)
            if alias:
                self.aliases.set_preset(d, alias)
            self.current = d
            self._set_local(d, src)

    def swap_preset(self) -> None:
        if not self._need_local():
            return
        d = self._ask_slot("Intercambiar preset", self.current)
        if d is not None:
            self._swap(self.current, d)

    def move_preset(self, delta: int) -> None:
        if self._need_local() and 0 <= self.current + delta < SLOTS:
            self._swap(self.current, self.current + delta)

    def _swap(self, a: int, b: int) -> None:
        self._push_undo()
        self.aliases.swap(a, b)
        p = self.local.presets
        p[a], p[b] = p[b], p[a]
        self.current = b
        self.refresh()

    def _factory(self) -> Bank | None:
        if not self._need_local():
            return None
        factory = library.factory_bank()
        if factory is None:
            QMessageBox.warning(self, "Fábrica", "No se encontró el banco de fábrica "
                                "(research/factory/tankG_am4_preset.bin).")
        return factory

    def _restore_factory(self, slots: list[int]) -> None:
        factory = self._factory()
        if factory is None:
            return
        self._push_undo()
        for s in slots:
            self.local.presets[s] = factory.presets[s].copy()
        self.refresh()
        self._schedule_live()
        self.statusBar().showMessage("Presets de fábrica cargados en el editor. «Guardar» los pasa a la pedalera.",
                                     6000)

    def factory_selected(self) -> None:
        self._restore_factory([self.current])

    def factory_current_bank(self) -> None:
        first = self.current // 4 * 4
        self._restore_factory(list(range(first, first + 4)))

    def factory_all(self) -> None:
        if dialogs.ask(self, "Fábrica", "¿Cargar en el editor los 36 presets de fábrica?\n"
                                "La pedalera no cambia hasta que pulses «Guardar todo»."):
            self._restore_factory(list(range(SLOTS)))

    def _template_menu(self) -> QMenu:
        menu = QMenu("Nuevo desde plantilla", self)
        for name in templates.TEMPLATES:
            menu.addAction(name, lambda n=name: self.apply_template(n))
        return menu

    def apply_template(self, name: str) -> None:
        if self._need_local():
            self._set_local(self.current, templates.build(name, self.local.presets[self.current]))
            self.statusBar().showMessage(f"Plantilla «{name}» aplicada a {slot_name(self.current)}", 4000)

    def open_ai(self) -> None:
        if self._need_local():
            dialogs.AIDialog(self).exec()

    def apply_generated(self, preset: Preset, name: str) -> None:
        self.aliases.set_preset(self.current, name)
        self._set_local(self.current, preset)
        self.statusBar().showMessage(f"Preset «{name}» creado con IA en {slot_name(self.current)}. "
                                     "Escúchalo (o activa «Escucha en vivo») y pulsa «Guardar preset».", 8000)

    def apply_generated_bank(self, bank: int, bank_name: str, items: list) -> None:
        self._push_undo()
        for i, (preset, name, _) in enumerate(items):
            slot = bank * 4 + i
            self.local.presets[slot] = preset.copy()
            self.aliases.set_preset(slot, name)
        if bank_name:
            self.aliases.set_bank(bank, bank_name)
        self.refresh()
        self._schedule_live()
        self.statusBar().showMessage(f"Banco {bank + 1} creado con IA. Escúchalo y pulsa «Guardar todo».", 8000)

    def run_job(self, fn, on_done, label: str) -> bool:
        """For dialogs: run fn(dev, report) in the background."""
        return self._run(fn, on_done, label)

    def load_local_bank(self, bank: Bank, message: str) -> None:
        self._push_undo()
        self.local = bank
        self.refresh()
        self.statusBar().showMessage(message, 6000)

    def show_diff(self, other: Bank, title: str) -> None:
        lines = []
        for s in self.local.diff_slots(other):
            a, b = self.local.presets[s].raw, other.presets[s].raw
            name = self.aliases.preset(s)
            changes = ", ".join(f"{dialogs.byte_name(i)} {b[i]}→{a[i]}" for i in range(len(a)) if a[i] != b[i])
            lines.append(f"{slot_name(s)}{f' ({name})' if name else ''}: {changes}")
        QMessageBox.information(self, "Comparación", "Idénticos." if not lines else f"{title}:\n" + "\n".join(lines))

    def revert_selected(self) -> None:
        if self.device is not None and self.local is not None:
            self._set_local(self.current, self.device.presets[self.current])

    def revert_all(self) -> None:
        if self.device is not None and self.local is not None:
            self._push_undo()
            self.local = self.device.copy()
            self.refresh()

    # files ---------------------------------------------------------------------------

    def _open_bank_dialog(self, title: str) -> Bank | None:
        path, _ = QFileDialog.getOpenFileName(self, title, str(library.BACKUP_DIR),
                                              "Banco Tank-G (*.tgbank *.bin)")
        if not path:
            return None
        try:
            return library.load_bank(path)
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Error", str(e))
            return None

    def open_bank(self) -> None:
        bank = self._open_bank_dialog("Abrir banco")
        if bank is not None:
            self.load_local_bank(bank, "Banco abierto. «Guardar todo» lo pasa a la pedalera.")

    def save_bank(self) -> None:
        if not self._need_local():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar banco", "tankg.tgbank", "Banco Tank-G (*.tgbank)")
        if path:
            library.save_bank(self.local, path)

    def import_preset(self) -> None:
        if not self._need_local():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importar preset", "", "Preset Tank-G (*.tgpreset)")
        if path:
            try:
                preset, name = library.load_preset_file(path)
                if name:
                    self.aliases.set_preset(self.current, name)
                self._set_local(self.current, preset)
            except (ValueError, OSError, KeyError) as e:
                QMessageBox.critical(self, "Error", str(e))

    def export_preset(self) -> None:
        if not self._need_local():
            return
        s = self.current
        alias = self.aliases.preset(s)
        default = f"{slot_name(s)} {alias}".strip().replace("/", "-") + ".tgpreset"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar preset", default,
                                              "Preset Tank-G (*.tgpreset)")
        if path:
            library.save_preset(self.local.presets[s], path, s, self.aliases.preset(s) or None)

    def compare_file(self) -> None:
        if not self._need_local():
            return
        other = self._open_bank_dialog("Comparar con")
        if other is not None:
            self.show_diff(other, "Archivo → editor")

    def export_bank_set(self) -> None:
        if not self._need_local():
            return
        bank = self.current // 4
        title = self.aliases.bank(bank) or f"Banco {bank + 1}"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar banco", f"{title}.tgset", "Banco Tank-G con nombres (*.tgset)")
        if path:
            library.save_set(self.local, list(range(bank * 4, bank * 4 + 4)), path, self.aliases, title)
            self.statusBar().showMessage(f"Exportado {path}", 5000)

    def import_bank_set(self) -> None:
        if not self._need_local():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importar banco", "", "Banco Tank-G con nombres (*.tgset)")
        if not path:
            return
        try:
            title, items = library.load_set(path)
        except (ValueError, OSError, KeyError) as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        bank = self.current // 4
        items = items[:4]
        if not dialogs.ask(self, "Importar banco", f"¿Reemplazar los presets {bank + 1}A–{bank + 1}"
                                f"{'ABCD'[len(items) - 1]} del editor con «{title or Path(path).stem}»?"):
            return
        self._push_undo()
        for i, (preset, name) in enumerate(items):
            slot = bank * 4 + i
            self.local.presets[slot] = preset
            self.aliases.set_preset(slot, name or "")
        if title:
            self.aliases.set_bank(bank, title)
        self.refresh()
        self._schedule_live()

    def show_bytes(self) -> None:
        if not self._need_local():
            return
        p = self.local.presets[self.current]
        dev = self.device.presets[self.current].to_bytes().hex(" ") if self.device else "—"
        QMessageBox.information(self, f"Bytes de {slot_name(self.current)}",
                                f"Local:     {p.to_bytes().hex(' ')}\nPedalera: {dev}")

    def about(self) -> None:
        QMessageBox.about(self, "Tank-G Control Center",
                          "Gestor de presets para M-VAVE Tank-G en Linux.\n\n"
                          "Protocolo: SysEx de M-EFCS (research/FINDINGS.md).\n"
                          f"Backups automáticos en {library.BACKUP_DIR}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.modified_slots() and not dialogs.ask(
                self, "Salir", "Hay presets modificados sin guardar en la pedalera. ¿Salir igualmente?"):
            event.ignore()
            return
        self.pool.waitForDone(10000)
        event.accept()


def _choose_qt_platform() -> None:
    """Qt >= 6.5 needs libxcb-cursor0 for X11; on a Wayland session without it use Wayland
    (same logic as run.sh, needed when started from the packaged executable)."""
    if not sys.platform.startswith("linux") or os.environ.get("QT_QPA_PLATFORM"):
        return
    if not os.environ.get("WAYLAND_DISPLAY"):
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        sockets = sorted(runtime.glob("wayland-[0-9]"))
        if sockets:
            os.environ["WAYLAND_DISPLAY"] = sockets[0].name
    if os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "wayland" if ctypes.util.find_library("xcb-cursor") is None \
            else "wayland;xcb"


def main() -> int:
    _choose_qt_platform()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Tank-G Control Center")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.QSS + STYLE)
    icon = library.PROJECT_ROOT / "packaging/icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
