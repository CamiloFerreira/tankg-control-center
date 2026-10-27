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

- **Se actualiza sola:** al abrirla, la app avisa si hay una versión nueva y la instala (Windows,
  Linux y Android; en Android el sistema pide confirmar). Desde esta versión ya no hace falta
  descargar a mano. Cada descarga se comprueba con `SHA256SUMS`.
- **Android al nivel del escritorio:** menú completo (Pedalera, Editar, Archivo), pulsación larga en
  un preset, copiar/pegar/duplicar/intercambiar, nombres de banco, restaurar de fábrica, escucha en
  vivo, backups, abrir/guardar bancos, importar/exportar presets y bancos (`.tgpreset`, `.tgset`,
  compatibles con el PC), comparar, puerto MIDI, asistente de calibración y **Crear con IA**.
- **Corrección:** en Windows los nombres con tildes o «ñ» de los archivos `.tgpreset`/`.tgset` se
  guardaban con otra codificación; ahora son UTF-8 en todas las plataformas.

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
