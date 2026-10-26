"""Secondary windows: backup manager and calibration assistant."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QButtonGroup, QFrame, QGridLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton,
    QVBoxLayout, QWidget,
)

from . import ai, device, library
from .model import AMP_MODELS, CAB_MODELS, FIELD_BY_KEY, FIELDS, OFF_COLOR, REC_LEN, Bank, slot_name, zone_of

BYTE_NAMES = {f.offset: f.label for f in FIELDS}
BYTE_NAMES.update({OFF_COLOR: "LED rojo", OFF_COLOR + 1: "LED verde", OFF_COLOR + 2: "LED azul"})
_NAME_RE = re.compile(r"bank-(\d{8})-(\d{6})-(.+)\.tgbank$")


def byte_name(offset: int) -> str:
    return BYTE_NAMES.get(offset, f"byte {offset}")


class BackupManager(QDialog):
    """Lists automatic and manual backups; load one into the editor or compare it."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Backups")
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Copias del banco completo guardadas en {library.BACKUP_DIR}"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Fecha", "Motivo", "Distintos al editor", "Archivo"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _: self.load())
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn in [("Cargar en el editor", self.load), ("Comparar", self.compare),
                         ("Abrir carpeta", self.open_folder), ("Cerrar", self.accept)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.paths: list[Path] = []
        self.populate()

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
                self.table.setItem(r, c, QTableWidgetItem(v))

    def _selected(self) -> Path | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Backups", "Selecciona un backup.")
            return None
        return self.paths[rows[0].row()]

    def load(self) -> None:
        path = self._selected()
        if path is None:
            return
        try:
            bank = library.load_bank(path)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Error", str(e))
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


class CalibrationWizard(QDialog):
    """Finds which byte a front-panel knob is stored in: snapshot the bank, let the user save
    a preset from the pedal (LIVE mode), read again and show the bytes that changed."""

    LOG = library.DATA_DIR / "calibration.log"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.reference: Bank | None = None
        self.setWindowTitle("Asistente de calibración")
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        steps = QLabel(
            "<b>Sirve para confirmar en qué byte guarda la pedalera cada perilla.</b><ol>"
            "<li>Pulsa <b>Tomar referencia</b>.</li>"
            "<li>En la pedalera entra en modo LIVE (B+C), mueve <b>una sola</b> perilla y mantén "
            "pulsado A/B/C/D para guardar en ese preset.</li>"
            "<li>Pulsa <b>Leer cambios</b>: aparecen los bytes que cambiaron y el control que la app "
            "les asigna. Si no coincide con la perilla que moviste, el mapa está mal en ese byte.</li>"
            "</ol>Cada lectura pasa a ser la nueva referencia, así que puedes repetir con otra perilla. "
            f"El resultado se anota en {self.LOG}.")
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        lay.addWidget(steps)
        row = QHBoxLayout()
        self.ref_btn = QPushButton("1. Tomar referencia")
        self.ref_btn.clicked.connect(self.take_reference)
        self.read_btn = QPushButton("2. Leer cambios")
        self.read_btn.setEnabled(False)
        self.read_btn.clicked.connect(self.read_changes)
        row.addWidget(self.ref_btn)
        row.addWidget(self.read_btn)
        lay.addLayout(row)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        lay.addWidget(self.out, 1)

    def _read(self, then) -> None:
        if not self.main.run_job(lambda dev, _: dev.read_bank(), then, "Leyendo la pedalera..."):
            QMessageBox.information(self, "Ocupado", "Hay una operación en curso.")

    def take_reference(self) -> None:
        def done(bank: Bank) -> None:
            self.reference = bank
            self.read_btn.setEnabled(True)
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


class MidiPortDialog(QDialog):
    """Choose the MIDI input/output ports by hand when automatic detection fails
    (port names differ between Windows installations)."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.settings = library.Settings()
        self.setWindowTitle("Puerto MIDI")
        self.resize(620, 300)
        lay = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.auto = QRadioButton("Automático (buscar «USB Composite Device», «TANK», «M-VAVE»…)")
        self.manual = QRadioButton("Elegir los puertos:")
        lay.addWidget(self.auto)
        lay.addWidget(self.manual)
        form = QFormLayout()
        self.in_combo = QComboBox()
        self.out_combo = QComboBox()
        form.addRow("Entrada (desde la pedalera)", self.in_combo)
        form.addRow("Salida (hacia la pedalera)", self.out_combo)
        lay.addLayout(form)
        self.result = QLabel()
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        row = QHBoxLayout()
        for text, fn in [("Actualizar lista", self.populate), ("Probar", self.test),
                         ("Guardar", self.save), ("Cancelar", self.reject)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.manual.toggled.connect(lambda on: (self.in_combo.setEnabled(on), self.out_combo.setEnabled(on)))
        saved = self.settings.midi_ports
        (self.manual if saved else self.auto).setChecked(True)
        self.in_combo.setEnabled(bool(saved))
        self.out_combo.setEnabled(bool(saved))
        self.populate()

    def populate(self) -> None:
        try:
            ins, outs = device.list_midi_ports()
        except device.DeviceError as e:
            self.status.setText(str(e))
            ins, outs = [], []
        else:
            self.status.setText(f"{len(ins)} puerto(s) de entrada y {len(outs)} de salida. En Windows cierra "
                                "M-EFCS: el puerto solo lo puede usar un programa a la vez.")
        saved = self.settings.midi_ports or ("", "")
        for combo, names, want in ((self.in_combo, ins, saved[0]), (self.out_combo, outs, saved[1])):
            combo.clear()
            combo.addItems(names)
            pick = want if want in names else next((n for n in names if device._looks_like_tankg(n)), None)
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
            self.result.setText("Hay una operación en curso; prueba en unos segundos.")
            return
        # () = automatic detection, ignoring any saved manual choice
        devs = device.find_devices(self._chosen() or ("", "")) if self.manual.isChecked() \
            else device.find_devices(())
        if not devs:
            self.result.setText("✗ No hay ningún puerto que coincida.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dev = device.TankG.open(devs[0])
            dev.close()
            self.result.setText(f"✓ Tank-G encontrada en «{devs[0].address}»: banco de 36 presets leído.")
        except device.DeviceError as e:
            self.result.setText(f"✗ {e}")
        finally:
            QApplication.restoreOverrideCursor()

    def save(self) -> None:
        if self.manual.isChecked() and self._chosen() is None:
            QMessageBox.information(self, "Puerto MIDI", "Elige un puerto de entrada y uno de salida.")
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


AI_STYLE = """
QDialog#ai { background: #15191d; }
QLabel { color: #e6e6e6; }
QLabel#aiTitle { font-size: 22px; font-weight: bold; color: #ffffff; }
QLabel#aiSub { color: #8a96a3; }
QLabel#target { background: #1f3b46; color: #9fe8ff; border-radius: 10px; padding: 4px 12px; font-weight: bold; }
QFrame#card { background: #1d2228; border: 1px solid #2a323b; border-radius: 12px; }
QLabel#cardTitle { color: #ffffff; font-weight: bold; font-size: 14px; }
QLabel#step { background: #1f9e6e; color: white; border-radius: 11px; font-weight: bold;
              min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }
QLabel#hint { color: #8a96a3; font-size: 12px; }
QPlainTextEdit#desc, QLineEdit {
    background: #10161a; color: #f0f0f0; border: 1px solid #333c46; border-radius: 8px; padding: 6px;
    font-size: 13px;
}
QPlainTextEdit#desc:focus, QLineEdit:focus { border: 1px solid #1f9e6e; }
QComboBox { background: #10161a; color: #f0f0f0; border: 1px solid #333c46; border-radius: 8px; padding: 5px 8px; }
QPushButton#chip {
    background: #262d35; color: #cfd6dd; border: 1px solid #333c46; border-radius: 13px; padding: 4px 12px;
}
QPushButton#chip:hover { background: #2f3842; color: #ffffff; border-color: #1f9e6e; }
QToolButton#modeCard {
    background: #1a1f25; color: #cfd6dd; border: 2px solid #2a323b; border-radius: 12px;
    padding: 10px; text-align: left; font-size: 13px;
}
QToolButton#modeCard:hover { border-color: #3a4a58; }
QToolButton#modeCard:checked { background: #16332b; border-color: #1f9e6e; color: #ffffff; }
QPushButton#seg {
    background: #1a1f25; color: #cfd6dd; border: 1px solid #333c46; padding: 7px 18px; font-weight: bold;
}
QPushButton#seg:checked { background: #1f6f6d; color: white; border-color: #1f9e6e; }
QPushButton#segL { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#primary, QPushButton#bigPrimary {
    background: #1f9e6e; color: white; border: none; border-radius: 8px; padding: 9px 18px; font-weight: bold;
}
QPushButton#bigPrimary { font-size: 14px; padding: 11px 18px; }
QPushButton#primary:hover, QPushButton#bigPrimary:hover { background: #23b37d; }
QPushButton#primary:disabled { background: #2a3139; color: #6b7480; }
QPushButton#secondary {
    background: #2a3139; color: #e6e6e6; border: none; border-radius: 8px; padding: 9px 18px;
}
QPushButton#secondary:hover { background: #343d47; }
QPushButton#link { background: transparent; color: #5dd3ff; border: none; padding: 2px; text-decoration: underline; }
QCheckBox { color: #b8c2cc; }
QFrame#result { background: #10161a; border: 1px dashed #333c46; border-radius: 10px; }
QLabel#resName { font-size: 18px; font-weight: bold; color: #ffffff; }
QLabel#resText { color: #c8d0d8; }
QLabel#module { background: #1d2228; border-radius: 8px; padding: 6px 10px; color: #e6e6e6; }
"""

STEP_STATES = ("Copiar las instrucciones", "Pegarlas en el chat y enviar", "Copiar la respuesta de la IA")


class AIDialog(QDialog):
    """Describe a sound in words; an LLM fills every control of the current preset.

    Two ways to reach the model: the browser (no key: copy the prompt into claude.ai /
    chatgpt.com / Gemini and copy the answer back, detected from the clipboard) or an API key."""

    KEY_URLS = {"claude": "https://console.anthropic.com/settings/keys",
                "openai": "https://platform.openai.com/api-keys"}
    SUGGESTIONS = ["Crunch tipo AC/DC", "Limpio con chorus de los 80", "Blues tipo SRV", "Solo con delay largo",
                   "Metal moderno muy apretado", "Ambiental para arpegios", "Funk limpio y brillante"]

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.settings = library.Settings()
        self.result: tuple | None = None
        self.waiting_clipboard = False
        self.setObjectName("ai")
        self.setStyleSheet(AI_STYLE)
        self.setWindowTitle("Crear preset con IA")
        screen = self.screen().availableGeometry() if self.screen() else None
        self.resize(800, min(900, screen.height() - 60) if screen else 820)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: #15191d; }")
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 18, 20, 8)
        lay.setSpacing(12)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        t = QLabel("✨ Crear preset con IA")
        t.setObjectName("aiTitle")
        sub = QLabel("Describe el sonido con tus palabras; la IA ajusta amplificador, gabinete, EQ y efectos.")
        sub.setObjectName("aiSub")
        sub.setWordWrap(True)
        titles.addWidget(t)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        alias = main.aliases.preset(main.current)
        target = QLabel(f"Destino: {slot_name(main.current)}" + (f" · {alias}" if alias else ""))
        target.setObjectName("target")
        head.addWidget(target, 0, Qt.AlignTop)
        lay.addLayout(head)

        # 1 · description ---------------------------------------------------------
        c1, l1 = self._card("1", "Describe el sonido")
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
        lay.addWidget(c1)

        # 2 · connection ----------------------------------------------------------
        c2, l2 = self._card("2", "Conexión con la IA")
        modes = QHBoxLayout()
        self.web_card = self._mode_card("🌐  Navegador\nGratis · usa tu cuenta de Claude, ChatGPT o Gemini")
        self.api_card = self._mode_card("🔑  Clave de API\nAutomático · requiere una clave de pago")
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
        lay.addWidget(c2)

        # 3 · result --------------------------------------------------------------
        c3, l3 = self._card("3", "Resultado")
        self.result_box = QFrame()
        self.result_box.setObjectName("result")
        self.result_lay = QVBoxLayout(self.result_box)
        self.result_lay.setContentsMargins(14, 12, 14, 12)
        l3.addWidget(self.result_box, 1)
        c3.setMinimumHeight(250)
        self.result_card = c3
        lay.addWidget(c3, 1)
        self._show_empty("El preset propuesto aparecerá aquí.")

        foot = QHBoxLayout()
        foot.setContentsMargins(20, 6, 20, 16)
        foot.addStretch()
        close = QPushButton("Cancelar")
        close.setObjectName("secondary")
        close.clicked.connect(self.reject)
        self.apply_btn = QPushButton(f"Aplicar a {slot_name(main.current)}")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        foot.addWidget(close)
        foot.addWidget(self.apply_btn)
        outer.addLayout(foot)

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
        self._provider_changed()
        self._site_changed()
        self._mode_changed()
        self._set_step(0)
        QApplication.clipboard().dataChanged.connect(self._clipboard_changed)

    # building blocks ------------------------------------------------------------

    def _card(self, number: str, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        n = QLabel(number)
        n.setObjectName("step")
        n.setAlignment(Qt.AlignCenter)
        t = QLabel(title)
        t.setObjectName("cardTitle")
        head.addWidget(n)
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)
        return card, lay

    def _mode_card(self, text: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("modeCard")
        b.setText(text)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        b.setMinimumHeight(58)
        return b

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
                              "provider": cfg.provider, "model": cfg.model, "base_url": cfg.base_url,
                              "keys": keys})

    def _done(self, result) -> None:
        self.result = result
        self.waiting_clipboard = False
        self._set_step(3)
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
        if self.result:
            preset, name, _ = self.result
            self.main.apply_generated(preset, name)
            self.accept()

    # browser mode -----------------------------------------------------------------

    def copy_and_open(self) -> None:
        text = self._check_ready()
        if text is None:
            return
        self._save_settings()
        QApplication.clipboard().setText(ai.web_prompt(text, self.instrument.currentText()))
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
        if ai.parse_design_text(text) is not None:
            self._from_text(text)

    def paste_answer(self) -> None:
        if self.main.local is not None:
            self._from_text(QApplication.clipboard().text())

    def _from_text(self, text: str) -> None:
        try:
            self._done(ai.from_text(text, self.main.local.presets[self.main.current]))
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
        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("Pensando el sonido…")
        self.apply_btn.setEnabled(False)
        self._show_empty("Pensando el sonido…")
        task = _Task(lambda: ai.generate(cfg, text, instrument, like))
        _PENDING.add(task)
        task.signals.done.connect(lambda r: (_PENDING.discard(task), self.isVisible() and self._done(r)))
        task.signals.failed.connect(lambda m: (_PENDING.discard(task), self.isVisible() and self._failed(m)))
        QThreadPool.globalInstance().start(task)
