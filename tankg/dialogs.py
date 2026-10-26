"""Secondary windows. All share StyledDialog: header (title + subtitle + optional badge),
numbered cards in the body and a footer with secondary/primary buttons; colours come from
theme.QSS through objectNames only."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from . import ai, device, library
from .model import AMP_MODELS, CAB_MODELS, FIELD_BY_KEY, FIELDS, OFF_COLOR, REC_LEN, Bank, slot_name, zone_of
from .theme import ERROR, OK, TEXT_DIM

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
        _, l3 = self.card("3", "Comprobar")
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

    def save(self) -> None:
        if self.manual.isChecked() and self._chosen() is None:
            self.status(self.result, "Elige un puerto de entrada y uno de salida.", False)
            return
        self.settings.set_midi_ports(self._chosen())
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
    SUGGESTIONS = ["Crunch tipo AC/DC", "Limpio con chorus de los 80", "Blues tipo SRV", "Solo con delay largo",
                   "Metal moderno muy apretado", "Ambiental para arpegios", "Funk limpio y brillante"]

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
        self.apply_btn.setText(f"Aplicar al banco {first}" if bank else f"Aplicar a {slot_name(self.main.current)}")
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
        QApplication.clipboard().setText(ai.web_prompt(text, self.instrument.currentText(), self._bank()))
        self.waiting_clipboard = True
        self.apply_btn.setEnabled(False)
        QDesktopServices.openUrl(QUrl(ai.WEB_SITES[self._site()]))
        self._set_step(1)
        self._show_empty(f"Esperando la respuesta de {self._site()}…\nPega con Ctrl+V en el chat, envía y "
                         "copia la respuesta.")

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
        task = _Task(lambda: ai.generate_bank(cfg, text, instrument, likes) if bank else
                     ai.generate(cfg, text, instrument, like))
        _PENDING.add(task)
        task.signals.done.connect(lambda r: (_PENDING.discard(task), self.isVisible() and self._done(r)))
        task.signals.failed.connect(lambda m: (_PENDING.discard(task), self.isVisible() and self._failed(m)))
        QThreadPool.globalInstance().start(task)
