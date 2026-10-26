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

## Firma (Windows)

El `.exe` está firmado con un certificado **autofirmado** («Camilo Ferreira (Tank-G Control
Center)», huella SHA-256 `A3:45:7F:B8:BD:DB:C3:93:31:75:1F:FE:60:57:F4:50:28:27:4E:98:F2:79:89:44:20:41:B4:27:BD:0F:0A:91`).
Windows no lo reconoce por sí solo; para que lo muestre como editor conocido en tus equipos,
instala `tankg-codesign.cer` (ver README, sección «Firma»). En otros PCs se comporta como un
ejecutable sin firmar.

## Funciones

Leer y guardar los 36 presets, editor con el aspecto del panel de la pedalera, nombres de presets y
bancos, color del LED, plantillas, restaurar de fábrica, exportar/importar presets y bancos,
backups automáticos antes de cada escritura con verificación por relectura, escucha en vivo y
asistente de calibración.

AMP y CAB están verificados; la posición del resto de controles está deducida del manual (ver
`research/FINDINGS.md`).
