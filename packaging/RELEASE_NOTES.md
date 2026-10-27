Gestor de presets para la pedalera M-VAVE Tank-G: Linux, Windows y **Android** (teléfono y tablet).

## Descarga

- **Windows:** `TankG-windows-x64.exe` — doble clic. Cierra M-EFCS antes de abrirlo (en Windows el
  puerto MIDI solo lo puede usar un programa a la vez).
- **Linux:** `TankG-linux-x86_64` — `chmod +x TankG-linux-x86_64 && ./TankG-linux-x86_64`.
  Con argumentos funciona como línea de comandos (`./TankG-linux-x86_64 list`).
- **Android 6+:** `TankG-android.apk` — ábrelo en el teléfono o tablet y permite «instalar apps de
  esta fuente». Conecta la pedalera con un adaptador **USB-OTG**: se conecta sola, sin permisos.

No necesita Python ni drivers: la Tank-G es USB-MIDI class-compliant.

## Novedades

- **Android:** la misma pedalera virtual del escritorio (faders, módulos, interruptores A–D que
  activan el preset), biblioteca, subida con progreso y verificación, backups y modo demo. Vista
  compacta en teléfono y disposición de escritorio en tablet o pantalla grande.
- **Biblioteca de sonidos sin IA:** más de 150 bancos y 600 presets. Cada banda trae Limpio (o
  Crunch), Rítmica, Variante y Solo: heavy, thrash, death, black, power, doom, nu metal, metalcore,
  progresivo, metal en español, hard rock, alternativo y blues, más bancos para bajo, guitarra
  clásica (nylon), acústica de acero, Stratocaster y Les Paul.
- **Subidas más rápidas y visibles:** ventana «Subiendo 2 de 4» con verificación (un preset en
  ~0,2 s); lo creado con IA o la biblioteca se sube al aplicarlo.
- **IA más precisa:** el prompt conoce el equipo de cada estilo e instrumento y trae ejemplos
  calibrados.
- **Interfaz de escritorio más simple:** seis acciones en la barra, clic derecho en cada preset,
  doble clic para activarlo.
- **Correcciones:** deshacer restaura los nombres, la escucha en vivo ya no escribe tras apagarla,
  la ventana de subida no se puede cerrar a mitad.

## Verificar la descarga

`SHA256SUMS` contiene la huella de cada archivo.
- Linux: `sha256sum -c SHA256SUMS --ignore-missing`
- Windows (PowerShell): `Get-FileHash .\TankG-windows-x64.exe` y compara con la línea de `SHA256SUMS`.

## Funciones

Leer y guardar los 36 presets, editor con el aspecto del panel de la pedalera, nombres de presets y
bancos, color del LED, biblioteca de sonidos, restaurar de fábrica, exportar/importar presets y
bancos, backups automáticos antes de cada escritura con verificación por relectura, escucha en vivo,
asistente de calibración y selección manual del puerto MIDI.

**Crear con IA** (escritorio): describe el sonido y la IA crea el preset o el banco completo (A–D).
Funciona en el navegador con tu cuenta de Claude, ChatGPT o Gemini (gratis, sin clave) o automático
con clave de API (Claude, OpenAI u Ollama local).

AMP y CAB están verificados; la posición del resto de controles está deducida del manual (ver
`research/FINDINGS.md`).
