# Tank-G Control Center

Gestor de presets para la pedalera **M-VAVE Tank-G** en **Linux y Windows**. Habla el protocolo
SysEx del editor oficial M-EFCS directamente por USB-MIDI (la pedalera es class-compliant: no
necesita drivers).

- Linux: ALSA rawmidi (`/dev/snd/midiC*D0`), sin dependencias MIDI.
- Windows / macOS: `python-rtmidi` (se instala solo).

## Ejecutable (sin Python)

En **Releases** de GitHub: `TankG-windows-x64.exe` (Windows) y `TankG-linux-x86_64` (Linux), un
solo archivo cada uno. Para generarlos localmente:

```bash
.venv/bin/pip install pyinstaller
.venv/bin/python packaging/build.py        # → dist/TankG (dist\TankG.exe en Windows)
packaging/install-linux.sh                 # Linux: copia a ~/.local/bin y añade la app al menú
```

Una etiqueta `vX.Y.Z` subida a GitHub compila ambos y publica el release
(`.github/workflows/release.yml`).

## Windows (desde el código)

1. Instala Python 3.11+ desde https://www.python.org/downloads/ marcando **Add python.exe to PATH**.
2. Descarga el proyecto (Code → Download ZIP, o `git clone`).
3. Conecta la Tank-G por USB y **cierra M-EFCS**: en Windows el puerto MIDI solo lo puede usar
   un programa a la vez.
4. Doble clic en `run.bat` (la primera vez crea el entorno e instala dependencias, tarda un poco).
   Para la línea de comandos: `run.bat list`, `run.bat backup`, etc.

Datos (backups y nombres) en `%APPDATA%\tankg\`.

Si no detecta la pedalera (el nombre del puerto MIDI varía entre equipos Windows): menú
**Pedalera → Puerto MIDI…**, elige entrada y salida, «Probar» y «Guardar». Desde la línea de
comandos: `TankG ports` lista los puertos y `TankG ports --in "NOMBRE" --out "NOMBRE"` los fija.

## Uso

```bash
./run.sh                 # interfaz gráfica
./run.sh list            # listar los 36 presets (1A..9D)
./run.sh backup          # backup del banco en ~/.local/share/tankg/backups/
./run.sh export 1B 1b.tgpreset
./run.sh import 1b.tgpreset 3C
./run.sh copy 1B 4A      # copiar
./run.sh swap 1B 2A      # intercambiar
./run.sh set 1B --amp 4 --cab 2 --field gain=90 --field rvb_mix=40
./run.sh reset 1B        # volver al preset de fábrica
./run.sh select 5C       # activar un preset (MIDI Program Change)
./run.sh restore archivo.tgbank
./run.sh diff archivo.tgbank
```

`./run.sh` (Linux) o `run.bat` (Windows) crea el entorno `.venv` la primera vez.
Tests: `.venv/bin/python -m pytest -q`. GitHub Actions los ejecuta en Linux y Windows.

## Interfaz gráfica

- Izquierda: los 9 bancos × 4 presets (A–D). El borde de cada botón es el color del LED del
  preset; `•` = modificado y aún no guardado en la pedalera.
- Centro: panel con la misma distribución que la pedalera (GATE, AMP, MOD, DELAY, REVERB, CAB).
  Cada perilla es un deslizador con su campo numérico; TYPE e IR CAB son listas. Cada módulo
  tiene su interruptor ON/OFF. Las perillas de 3 tramos muestran el tipo aproximado.
- Abajo: interruptores D/AMP, C/MOD, B/DELAY, A/REVERB, BANK −/+ y el display. Pulsar un
  interruptor selecciona el preset y lo activa en la pedalera.
- Arriba: «Color LED», «Revertir» y «Guardar preset». Barra: leer pedalera, guardar todo,
  deshacer, copiar/pegar, intercambiar, restaurar de fábrica, importar/exportar, backup.
- Nombres (solo en la app, la pedalera no guarda nombres): escribe el nombre del preset junto
  al título (F2); clic en «BANCO n» para nombrar el banco (Shift+F2). Se guardan en
  `~/.local/share/tankg/aliases.json` (Windows: `%APPDATA%\tankg\aliases.json`), siguen al preset al intercambiar/duplicar y viajan
  dentro de los `.tgpreset`.
- Plantillas («Plantilla» en la barra o Editar → Nuevo desde plantilla): limpio, crunch,
  overdrive, distorsión, alta ganancia, solo, ambiental, acústica, bajo, vacío.
- Fábrica: restaurar el preset, el banco actual o los 36 presets de fábrica (se cargan en el
  editor; «Guardar» los pasa a la pedalera).
- Compartir: Archivo → Exportar/Importar banco (`.tgset`, 4 presets con sus nombres), además
  de presets sueltos (`.tgpreset`) y bancos completos (`.tgbank`).
- Pedalera → Gestor de backups: lista de copias con fecha y diferencias; cargar o comparar.
- Pedalera → Asistente de calibración: toma una referencia, guardas desde la pedalera en modo
  LIVE tras mover una perilla y muestra qué byte cambió (anota en `calibration.log`).
- **✨ Crear con IA** (cabecera del preset o Ctrl+K): describes el sonido con tus palabras
  («crunch tipo AC/DC», «limpio con chorus de los 80», «solo de Gilmour») y una IA rellena todos
  los controles, nombra el preset y explica sus decisiones. Queda en el editor para escucharlo
  antes de guardarlo. Servicios: Claude (Anthropic), ChatGPT (OpenAI) o cualquier servidor
  compatible con OpenAI (Ollama/LM Studio, local y gratis). Necesita tu propia clave de API
  (o las variables `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`); la clave solo se guarda si marcas
  «Recordar» (sin cifrar, en `settings.json`).
- «Escucha en vivo»: cada cambio se guarda en la pedalera y se activa el preset para oírlo.
- La conexión y desconexión se detectan solas. La pedalera solo se abre durante cada
  operación, así que no bloquea a PipeWire, a un DAW ni a M-EFCS.

## No soportado (todavía)

Funciones de M-EFCS cuyo protocolo para Tank-G no está verificado y que no se implementan para
no arriesgar los datos de la pedalera: importar IR/CAB, interruptor Loopback (USB) y otros
ajustes globales, actualización de firmware. Se podrán añadir con una captura del editor
oficial (ver research/FINDINGS.md §7).

## Seguridad

- Antes de cada escritura se guarda automáticamente un backup del banco completo.
- Solo se escriben los presets que cambian; después se relee la pedalera y se comprueba
  byte a byte.
- La pedalera tiene 36 posiciones fijas: "eliminar" equivale a restaurar el preset de
  fábrica de esa posición.

## Estado del protocolo

Detalle en [research/FINDINGS.md](research/FINDINGS.md).

| Función | Estado |
|---|---|
| Leer banco completo | verificado |
| Escribir un preset + commit | verificado (ACK y relectura) |
| Cambio permanente tras apagar | verificado |
| Activar preset (Program Change) | verificado |
| AMP (byte 5), CAB (byte 17) | verificados con la lista oficial |
| Resto de controles y color LED | posición deducida del manual, pendiente de calibrar |
| Versión de firmware | no disponible |

## Formatos

- `.tgbank`: imagen de 758 bytes (`A5 5A` + 36 × 21 bytes), igual a la de la pedalera y a
  `tankG_*_preset.bin` de M-EFCS.
- `.tgpreset`: JSON con los 21 bytes en hexadecimal (`raw`), nombre y campos legibles.
- `.tgset`: JSON con varios presets (normalmente un banco de 4) y sus nombres.

El banco de fábrica se toma de `research/factory/tankG_am4_preset.bin` (extraído de M-EFCS,
propiedad de M-VAVE, solo para uso local) o de `~/.local/share/tankg/factory.tgbank`.
