Gestor de presets para la pedalera M-VAVE Tank-G: Linux, Windows y **Android** (teléfono y tablet).

## Descarga

- **Windows:** `TankG-windows-x64.exe` — doble clic. Cierra M-EFCS antes de abrirlo (en Windows el
  puerto MIDI solo lo puede usar un programa a la vez).
- **Linux:** `TankG-linux-x86_64` — `chmod +x TankG-linux-x86_64 && ./TankG-linux-x86_64`.
  Con argumentos funciona como línea de comandos (`./TankG-linux-x86_64 list`).
- **Android 6+:** `TankG-android.apk` — ábrelo en el teléfono o tablet y permite «instalar apps de
  esta fuente». Conecta la pedalera con un adaptador **USB-OTG** o por **Bluetooth** (Tank-G v2).

No necesita Python ni drivers: la Tank-G es USB-MIDI class-compliant.

## Novedades (1.8.0)

- **Subir modelos de AMP (.am4data)**, los mismos que descarga la app oficial M-EFCS: Pedalera →
  **Subir modelo de AMP** (en Android, menú). Eliges el archivo y cuál de los 9 AMP (perilla TYPE)
  reemplaza; la app calcula y envía todo igual que M-EFCS y muestra el nombre del modelo en la lista TYPE.
- **Restaurar AMP/CAB de fábrica**: vuelve a dejar los 9 AMP y los 8 CAB como vienen, eligiendo el
  juego **AM4** (modelos nuevos) o **AM3** (original), con o sin los 36 presets de ese juego (antes hace
  un backup del banco). Tarda unos 40 segundos.
- Estas dos funciones van **por Bluetooth** (Tank-G v2). Por USB la app avisa: el protocolo de la
  pedalera para eso solo se conoce por Bluetooth.
- **Perillas de tres tramos** (MOD FX, DLY MIX, RVB DECAY): si la perilla queda entre dos tramos, la
  app muestra «APAGADO» y apaga las luces del módulo, como hace la pedalera.

## Versión 1.7.1

- **Icono nuevo** en Linux, Windows y Android: una perilla con su arco de nivel.
- **Política de privacidad y condiciones del servicio**, enlazadas desde Ayuda → Acerca de
  (en Android, menú → Acerca de). Resumen: la app no tiene servidores ni telemetría, y Google
  Drive solo ve los archivos que crea la propia app.

## Versión 1.7

- **Nube con Google Drive: los mismos presets en Linux, Windows y Android.**
  - Menú **Nube → Conectar con Google Drive**: la app copia un código y abre google.com/device;
    pégalo, elige tu cuenta y pulsa «Permitir». Igual en PC y teléfono.
  - Cada vez que guardas en la pedalera se sube sola la copia (presets y nombres de presets y bancos).
  - Al abrir la app en otro equipo, si en la nube hay una versión más nueva, pregunta si cargarla.
  - **Historial:** se guardan las últimas 30 versiones y puedes volver a cualquiera.
  - Todo queda en la carpeta «Tank-G Control Center» de **tu** Drive. La app solo ve los archivos que
    ella misma creó, y cada persona usa su propia cuenta.

## Versión 1.6.2

- **Linux:** el ejecutable ya no se cierra al abrir con «Could not load the Qt platform plugin xcb».

## Versión 1.6

- **Bluetooth (Tank-G v2), sin cable:**
  - **Android:** empareja la pedalera en los ajustes de Android y la app se conecta sola al abrirse
    (como la app oficial). Si la apagas y la enciendes, se reconecta.
  - **Windows/Linux:** Pedalera → Puerto MIDI… → Bluetooth → Buscar, elige la pedalera y Guardar.
  - Todo funciona igual que por USB: leer, guardar con verificación, biblioteca, IA, escucha en vivo.
  - La pedalera acepta **una conexión a la vez**: cierra la app del teléfono para usar el PC y al revés.
- Ya no hay versión web: solo Windows, Linux y Android.

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
