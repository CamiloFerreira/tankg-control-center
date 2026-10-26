Gestor de presets para la pedalera M-VAVE Tank-G (Linux y Windows).

## Descarga

- **Windows:** `TankG-windows-x64.exe` — doble clic. Cierra M-EFCS antes de abrirlo (en Windows el
  puerto MIDI solo lo puede usar un programa a la vez). Windows SmartScreen puede avisar porque el
  ejecutable no está firmado: «Más información» → «Ejecutar de todas formas».
- **Linux:** `TankG-linux-x86_64` — `chmod +x TankG-linux-x86_64 && ./TankG-linux-x86_64`.
  Con argumentos funciona como línea de comandos (`./TankG-linux-x86_64 list`).

No necesita Python ni drivers: la Tank-G es USB-MIDI class-compliant.

## Verificar la descarga

`SHA256SUMS` contiene la huella de cada archivo.
- Linux: `sha256sum -c SHA256SUMS --ignore-missing`
- Windows (PowerShell): `Get-FileHash .\TankG-windows-x64.exe` y compara con la línea de `SHA256SUMS`.

## Funciones

Leer y guardar los 36 presets, editor con el aspecto del panel de la pedalera, nombres de presets y
bancos, color del LED, plantillas, restaurar de fábrica, exportar/importar presets y bancos,
backups automáticos antes de cada escritura con verificación por relectura, escucha en vivo,
asistente de calibración y selección manual del puerto MIDI.

**Crear con IA:** describe el sonido y la IA crea el preset o el banco completo (A–D). Funciona en
el navegador con tu cuenta de Claude, ChatGPT o Gemini (gratis, sin clave) o automático con clave
de API (Claude, OpenAI u Ollama local).

AMP y CAB están verificados; la posición del resto de controles está deducida del manual (ver
`research/FINDINGS.md`).
