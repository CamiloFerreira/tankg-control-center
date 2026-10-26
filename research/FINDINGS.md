# Tank-G — Investigación fase 1 (2026-10-26)

Leyenda: **[VERIFICADO]** = comprobado con la pedalera real o con archivos oficiales.
**[INFERIDO]** = deducido, falta confirmar. **[DESCONOCIDO]** = sin datos.

## 1. Sistema

- Ubuntu 24.04.5, kernel 7.0.0-38, Python 3.12.3.
- PipeWire activo. ALSA: `amidi`, `aseqdump`, `aconnect`.
- No instalados: `mido`, `python-rtmidi`, `pyusb`, PySide6/PyQt6, Wireshark/tshark, Wine.
- Usuario en `plugdev`, `audio` no. `/sys/kernel/debug/usb/usbmon` requiere root.

## 2. Dispositivo [VERIFICADO]

| Campo | Valor |
|---|---|
| USB VID:PID | `4c4a:c755` (Jieli Technology "USB Composite Device") |
| bcdDevice | 1.00 |
| Serial | `4150353336303414` |
| Audio | UAC1, 2in/2out, S24_3LE, 44.1 kHz (EP 0x02 OUT, 0x83 IN) |
| MIDI | USB-MIDI, bulk EP 0x04 OUT / 0x84 IN, ALSA `hw:3,0,0`, seq client "USB Composite Device" |
| HID | ninguno |

VID:PID genérico Jieli: **no identifica el modelo**. MK-300 y otros M-VAVE usan el mismo
nombre. Identificación real del modelo → por el contenido del banco (ver §4) **[INFERIDO]**.

Hay dos variantes de hardware: **TANK-G** y **TANK-Gv2**, firmwares distintos
(`TANK-G.fwsc`, `TANK-Gv2.fwsc`, ambos V97 2026-01-31). Cuál es la mía: **[DESCONOCIDO]**.
Versión de firmware instalada: **[DESCONOCIDO]** (no encontrada aún en lo leído).

## 3. Protocolo

Editor oficial: **M-EFCS** (Flutter; Windows/macOS/iOS/Android). Soporta TANK-G.
Código Dart en `package:m_efcs/data/products/tank_g/{config,data,structs,effect_params}.dart`.

Framing SysEx documentado para MK-300 por github.com/jpfaria/mvave (MIT):

```
F0 00 32 | CLS | CMD(4) | 02 | FIELD(4) | SUB(4) | pack7(payload + ck8) | F7
SUB = (len << 4) | space ; ck8 = 0xFB - (Σpayload + Σbytes(FIELD) + Σbytes(len<<8 | space<<4))
```

Tank-G **responde a este framing** [VERIFICADO]: lecturas `CLS=0D CMD=41` devuelven datos con
checksum válido. Implementación propia: `tankg/sysex.py`; sonda de solo lectura:
`tools/probe_read.py`.

Diferencias con MK-300:

- Space 0, offset 0, len 758 → **banco completo de presets** [VERIFICADO]. Lectura única de
  758 bytes funciona.
- Space 1 y 2 **no existen en Tank-G** [VERIFICADO]: devuelven el contenido que quedó en el buffer
  de respuesta de la petición anterior (o ceros), con el primer byte cambiado.
- Lectura de 448 bytes en space 1 (tamaño MK-300) → todo ceros.
- Status poll MK-300 (space 2, len 86) responde, contenido no interpretado.

**Escritura [VERIFICADO 2026-10-26]:** un preset = `CLS 09`, `CMD = 0x41 + 8·21`, space 0,
field = `2 + 21·slot`, len 21, payload = registro. Respuesta: ACK
`F0 00 32 01 08 00 00 00 00 7F 01 F7`. Después COMMIT (`CLS 09 CMD 41`, space F, len 0) → ACK.
Relectura muestra solo los bytes cambiados (probado en 9D, 1B, y restauración de 9D).
La relectura ya refleja el cambio antes del COMMIT. **Persistencia tras apagar: sin comprobar.**

**Activar preset [VERIFICADO]:** MIDI Program Change canal 1, programa 0–35 (`C0 01` → 1B).

## 4. Formato del banco [VERIFICADO salvo indicación]

Fuente: `tankG_am4_preset.bin` (assets de M-EFCS 2026-10-23, 758 bytes) = mismo formato que
la lectura en vivo de space 0.

```
0x000  2   magic A5 5A
0x002  36 × 21 bytes  presets 1A..9D  (índice k → banco k//4 + 1, letra "ABCD"[k%4])
```

Sin nombres de preset (la pedalera no los tiene) [INFERIDO por formato].

Registro (21 bytes):

| Byte | Significado | Estado |
|---|---|---|
| 5 | Modelo AMP 0–8 (J120_CL, J900_CL, VAVE_TS, RAT_OD, VAVE_HTS, VAVE_DS, MS_GV2, J900_HV, MS_HIGAIN) | VERIFICADO contra PDF oficial, 36/36 |
| 17 | CAB 1–8 (AC-SeVin, JVM_1960_57, MESA_412, WANGS112, VOX_AC30, HIFI_YAMAHA, EGNL_412, V30_MD421); 0 = sin CAB | VERIFICADO contra PDF, 36/36 |
| 6–10 | 5 valores 0–100 (¿knobs AMP: gain/bass/mid/treble/vol?) | INFERIDO |
| 4 | 0 en limpios, 0x1B–0x2E en high-gain (¿umbral noise gate?) | INFERIDO |
| 0–3, 11–16, 18–20 | flags/parámetros de MOD/DLY/REV/etc. | DESCONOCIDO |

Bytes 18–20 en vivo contienen `aa`, `55`, `ff`… (posible basura/no usados) [INFERIDO].

Archivos: `research/factory/*.bin` (tankG am3/am4, stationG, tankB, stationB),
`research/TANK-G_en.pdf`, release notes en `research/*.txt`.
Backup real: `backups/bank-2026-10-26.bin`
(sha256 `f9f59f6b3e73e00baf6c70a872912ed700a415ec5acb70cc22b9f3134741b5f9`).

## 5. MIDI de control (release notes v46) [VERIFICADO en doc, no probado]

- PC 0–35 seleccionan preset 1A..9D.
- CC 0–40 (modo "chocolate Program C") activan módulos. Mapa exacto: DESCONOCIDO.

## 6. Incógnitas que bloquean

1. Persistencia de la escritura tras apagar y encender.
2. Editar el buffer en vivo sin guardar (como MK-300 space 1) — no investigado.
3. Mapa completo de los 21 bytes (bloquea editor de parámetros, no la gestión de presets).
4. Versión de firmware y variante v1/v2.
5. Significado de spaces 1 y 2.

## 7. Vías para obtener la escritura

A. **Captura del editor oficial** (preferida, no invasiva): VM Windows (QEMU/virt-manager) en
   este host con passthrough USB de `4c4a:c755`, capturar con `usbmon` + Wireshark en el host.
   O PC Windows con Wireshark + USBPcap. Procedimiento en `research/CAPTURE.md` (pendiente).
B. **Descompilar M-EFCS** (APK arm64, Dart AOT) con blutter → `tank_g/structs.dart` y la
   lógica de escritura. Es lo que hizo jpfaria para las subidas NAM del MK-300.
C. **Escritura experimental** imitando MK-300 en un solo slot, con backup y verificación por
   relectura. Riesgo: corromper el banco (no el firmware) [INFERIDO]; recuperable si la
   escritura funciona o con reset de fábrica de la pedalera.

## 8. Mapa de campos según el manual (2026-10-26)

Manual (manuals.plus / equipboard): panel = NOISE GATE, TYPE, GAIN, TREBLE, MIDDLE, BASS, VOLUME,
MOD FX, MOD SPEED, DLY MIX, DLY TIME, RVB DECAY, RVB MIX, IR CAB, MASTER. MOD FX / DLY MIX /
RVB DECAY son perillas de 3 tramos (CHORUS/PHASER/TREMOLO, ANALOG/TAPE/DUAL, ROOM/SPRING/CLOUD;
entre tramos = módulo apagado). El color del LED de cada preset es configurable desde el editor.
MASTER es global.

4 on/off + gate + type + 5 EQ + 3×2 FX + cab + RGB = 21 bytes exactos. Hipótesis usada por la app:

| Byte | Campo | Evidencia |
|---|---|---|
| 0–3 | AMP / MOD / DELAY / REVERB on | [1]=1 coincide con bytes 11–12 no nulos en datos reales; resto INFERIDO |
| 4 | NOISE GATE (0 = off) | INFERIDO (0 en limpios) |
| 5 | TYPE | VERIFICADO |
| 6–10 | GAIN, TREBLE, MIDDLE, BASS, VOLUME (orden del panel) | INFERIDO, orden sin confirmar |
| 11–12 | MOD FX, MOD SPEED | INFERIDO |
| 13–14 | DLY MIX, DLY TIME | INFERIDO |
| 15–16 | RVB DECAY, RVB MIX | INFERIDO |
| 17 | IR CAB | VERIFICADO |
| 18–20 | color LED R, G, B (fábrica `ff 00 00`) | INFERIDO |

Límites de los 3 tramos: se asumen tercios iguales (sin calibrar).
Calibración propuesta: en modo LIVE mover una sola perilla, guardar (mantener A/B/C/D) en un slot,
leer el banco y comparar con el backup.
