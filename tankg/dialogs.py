"""Secondary windows: backup manager and calibration assistant."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from . import ai, device, library
from .model import FIELDS, OFF_COLOR, REC_LEN, Bank, slot_name

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


class AIDialog(QDialog):
    """Describe a sound in words; an LLM fills every control of the current preset."""

    KEY_URLS = {"claude": "https://console.anthropic.com/settings/keys",
                "openai": "https://platform.openai.com/api-keys"}

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.settings = library.Settings()
        self.result: tuple | None = None
        self.setWindowTitle("Crear preset con IA")
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        intro = QLabel("Describe el sonido que quieres con tus palabras. La IA elige amplificador, "
                       "gabinete, EQ y efectos, y lo carga en el preset seleccionado para que lo "
                       "escuches antes de guardarlo.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Ejemplos:\n• crunch tipo AC/DC para riffs\n• limpio con chorus estilo "
                                       "años 80\n• solo de Gilmour en Comfortably Numb\n• metal moderno muy apretado")
        self.prompt.setFixedHeight(110)
        lay.addWidget(self.prompt)
        form = QFormLayout()
        self.instrument = QComboBox()
        self.instrument.addItems(ai.INSTRUMENTS)
        form.addRow("Instrumento", self.instrument)
        self.provider = QComboBox()
        for key, p in ai.PROVIDERS.items():
            self.provider.addItem(p["label"], key)
        form.addRow("Servicio de IA", self.provider)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key_link = QLabel()
        self.key_link.setOpenExternalLinks(True)
        form.addRow("Clave de API", self.key)
        form.addRow("", self.key_link)
        self.remember = QCheckBox("Recordar la clave en este equipo (se guarda sin cifrar en settings.json)")
        form.addRow("", self.remember)
        self.model = QLineEdit()
        form.addRow("Modelo", self.model)
        self.url = QLineEdit()
        self.url_label = QLabel("URL del servidor")
        form.addRow(self.url_label, self.url)
        lay.addLayout(form)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Aquí aparecerá el preset propuesto.")
        lay.addWidget(self.output, 1)
        row = QHBoxLayout()
        self.gen_btn = QPushButton("✨ Generar")
        self.gen_btn.clicked.connect(self.generate)
        self.apply_btn = QPushButton()
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.reject)
        row.addWidget(self.gen_btn)
        row.addWidget(self.apply_btn)
        row.addWidget(close)
        lay.addLayout(row)

        saved = self.settings.ai
        idx = self.provider.findData(saved.get("provider", "claude"))
        self.provider.setCurrentIndex(max(0, idx))
        self.remember.setChecked(bool(saved.get("keys")))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()
        self.apply_btn.setText(f"Aplicar a {slot_name(main.current)}")

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
        compatible = key == "compatible"
        self.url.setVisible(compatible)
        self.url_label.setVisible(compatible)
        self.key.setText(saved.get("keys", {}).get(key, ""))
        env = p["env"]
        self.key.setPlaceholderText("opcional" if compatible else
                                    f"sk-…  (o variable de entorno {env})")
        link = self.KEY_URLS.get(key)
        self.key_link.setText(f'<a style="color:#5dd3ff" href="{link}">Conseguir una clave</a>' if link else
                              "Para Ollama: instala Ollama y ejecuta «ollama pull llama3.1».")

    def _save_settings(self) -> None:
        cfg = self._cfg()
        saved = dict(self.settings.ai)
        keys = dict(saved.get("keys", {}))
        if self.remember.isChecked() and cfg.api_key:
            keys[cfg.provider] = cfg.api_key
        elif not self.remember.isChecked():
            keys = {}
        self.settings.set_ai({"provider": cfg.provider, "model": cfg.model, "base_url": cfg.base_url,
                              "keys": keys})

    def generate(self) -> None:
        text = self.prompt.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "IA", "Escribe cómo quieres que suene.")
            return
        if self.main.local is None:
            QMessageBox.information(self, "IA", "Lee primero la pedalera o abre un banco.")
            return
        self._save_settings()
        cfg, instrument = self._cfg(), self.instrument.currentText()
        like = self.main.local.presets[self.main.current]
        self.gen_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.output.setPlainText("Pensando el sonido…")
        task = _Task(lambda: ai.generate(cfg, text, instrument, like))
        _PENDING.add(task)
        task.signals.done.connect(lambda r: (_PENDING.discard(task), self.isVisible() and self._done(r)))
        task.signals.failed.connect(lambda m: (_PENDING.discard(task), self.isVisible() and self._failed(m)))
        QThreadPool.globalInstance().start(task)

    def _done(self, result) -> None:
        self.result = result
        preset, name, explanation = result
        self.output.setPlainText(f"{name}\n\n{explanation}\n\n{ai.describe(preset)}")
        self.gen_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)

    def _failed(self, msg: str) -> None:
        self.output.setPlainText(f"✗ {msg}")
        self.gen_btn.setEnabled(True)

    def apply(self) -> None:
        if self.result:
            preset, name, _ = self.result
            self.main.apply_generated(preset, name)
            self.accept()
