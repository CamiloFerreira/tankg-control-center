Gestor de presets para la pedalera M-VAVE Tank-G: Linux, Windows y **Android** (teléfono y tablet).

## Descarga

- **Windows:** `TankG-windows-x64.exe` — doble clic. Cierra M-EFCS antes de abrirlo (en Windows el
  puerto MIDI solo lo puede usar un programa a la vez).
- **Linux:** `TankG-linux-x86_64` — `chmod +x TankG-linux-x86_64 && ./TankG-linux-x86_64`.
  Con argumentos funciona como línea de comandos (`./TankG-linux-x86_64 list`).
- **Android 6+:** `TankG-android.apk` — ábrelo en el teléfono o tablet y permite «instalar apps de
  esta fuente». Conecta la pedalera con un adaptador **USB-OTG** o por **Bluetooth** (Tank-G v2).

No necesita Python ni drivers: la Tank-G es USB-MIDI class-compliant.

## Novedades (1.10.1)

- **La nube ya no pisa cambios sin subir.** Si cerraste la app sin conexión (o antes de que se subiera un cambio),
  al abrirla recupera esos cambios y los sube, en vez de cargar la versión de la nube. Si mientras tanto otro
  equipo guardó en la nube, pregunta cuál usar; la otra versión queda en el historial de la nube o en los backups.
- Detalle visual: algunos chips de AMP en las tarjetas salían con un borde blanco.

## Novedades (1.10.0)

- **Setlists y modo escenario.** Botón «Setlists» junto a la Biblioteca (Ctrl+J; en Android, en la barra de abajo).
  - Guarda todos los shows que quieras, con los presets en el orden en que los vas a tocar y una nota por canción
    (afinación, capo, tempo…). Se sincronizan con Google Drive y cada canción encuentra su preset aunque lo muevas.
  - **Modo escenario**: pantalla completa con letras enormes sobre un brillo del color del LED del preset, barra
    de progreso y la canción que sigue. Flechas, barra espaciadora, Re Pág/Av Pág (pedales pasa-páginas), tocar
    o deslizar la pantalla pasan de canción y la activan en la pedalera. En Android la pantalla no se apaga.
  - **Ordenar** (opcional): deja las canciones seguidas desde el slot que elijas (1A, 1B, 1C, 1D, 2A…) para
    pasarlas con los footswitches; solo se mueven los presets necesarios y se deshace con Ctrl+Z.
  - «Copiar lista» da el setlist con slot y nota de cada canción, para imprimir o mandar a la banda.
- **Interfaz renovada.** La lista de presets, la Biblioteca y los Setlists usan tarjetas con el color del LED de
  cada preset, su AMP y su descripción; las barras tienen íconos; en Android hay una pantalla de inicio nueva.

## Novedades (1.9.1)

- **Valores de fábrica «Original (de caja)».** «Restaurar de fábrica» ahora deja los presets tal como vienen en
  una pedalera nueva (leídos de la pedalera tras restaurarla con M-EFCS) y es la opción por defecto. AM4 y AM3
  siguen disponibles.
- **Nombres para los presets de fábrica.** Los 9 bancos y los 36 presets de fábrica tienen nombre (Esenciales,
  Limpios y crunch, Rock clásico, Texturas, Vintage, Metal, Blues rock, Británicos, Solos y potencia), y se
  ponen solos al restaurar un preset, un banco o todo.

## Novedades (1.9.0)

- **Packs de bandas con AMP reales.** En la Biblioteca hay un grupo nuevo, **«★ Con AMP importado»**: 11 bancos
  (Pantera, Metallica, Guns N' Roses, AC/DC y Zeppelin, Van Halen, Iron Maiden y Priest, metal 5150, Blues y SRV,
  Queen/U2, Pink Floyd, Ozzy y Zakk Wylde) con presets hechos para capturas del amplificador de cada banda.
  - Los modelos son capturas de sus autores en la **comunidad de M-VAVE**: la app no los incluye, los descarga de
    su publicación original cuando los necesitas y muestra el crédito de cada autor. Si falta alguno, pregunta.
  - **Descargar AMP de los packs** (menú) los baja todos de una vez y quedan en el equipo, para usarlos sin conexión.
  - Al importar, cada modelo va a un TYPE (puedes cambiarlo y los presets se ajustan solos); se suben los AMP y
    luego los presets, verificados, por Bluetooth.
- **Packs propios (.tgpack):** exporta un preset, un banco o los 36 junto con los AMP que subiste, e impórtalos en
  otro equipo (Archivos → Importar/Exportar pack).
- **Avisos:** si un preset de un pack apunta a un TYPE donde ahora hay otro modelo, el editor lo dice y permite
  subir el correcto con un toque; antes de subir un AMP la app dice cuántos presets usan ese TYPE.
- **La IA conoce tus AMP subidos** y puede usarlos al crear presets y bancos.
- **Google Drive** sincroniza también de dónde vino cada AMP; en otro equipo ofrece descargar los que falten.
- Android: los .tgset/.tgpreset ya no se guardan como «.json».

## Versión 1.8.4

- **Windows/Linux: el menú se abre dentro de la ventana**, como en Android: un panel que se desliza
  desde la izquierda sobre el editor («☰ Menú» o Ctrl+Shift+P; se cierra con Esc o tocando fuera).
  Cada acción muestra su atajo de teclado. Ya no hay barra de menús: todo está en el menú y los atajos
  de siempre siguen funcionando (Ctrl+O, Ctrl+S, F5, Ctrl+Z…).

## Versión 1.8.3

- **Menú nuevo con buscador en Windows, Linux y Android.** Escribe lo que buscas («guardar», «nube»,
  «fábrica», «AMP»…) y aparece al instante; arriba, accesos rápidos (Leer, Guardar, Activar, En vivo,
  Biblioteca, Crear con IA) y debajo todas las acciones agrupadas, con icono y una línea que explica
  qué hace. Lo que no se puede usar en ese momento se ve atenuado.
  - **Windows/Linux:** botón «☰ Menú» de la barra o **Ctrl+Shift+P**; Enter ejecuta la primera
    coincidencia. La barra de menús de siempre sigue igual.
  - **Android:** el menú ⋮. En tablets se abre como panel lateral sin tapar el editor.
- **Corregido en Android:** el botón «atrás» a veces cerraba la app en vez de cerrar el menú o la ventana
  abierta.

## Versión 1.8.2

- **Conectar con Google Drive sin salir de la app:** la ventana muestra el código y ya no abre el
  navegador sola. Escríbelo en **cualquier dispositivo** (el PC, otro teléfono o el mismo) en
  google.com/device; el botón «Abrir Google» queda opcional.
- **Corregido en tablets:** al volver del navegador decía «Sin conexión con Google, ¿hay internet?»
  aunque se hubiera aprobado. Ahora sigue esperando y se conecta al volver a la app.

## Versión 1.8.1

- **Google Drive se sincroniza solo** (si lo conectaste en Nube → Conectar):
  - Al abrir la app, el editor carga la última versión de la nube sin preguntar. Lo que sea distinto de la
    pedalera queda como cambios sin guardar: la pedalera no cambia hasta que pulses «Guardar».
  - Cada cambio en el editor (valores, nombres, restaurar de fábrica, guardar) se sube solo a los pocos
    segundos. Abajo se ve el estado: «Guardando cambios en la nube…», «Cambios guardados en la nube».
  - Se sincronizan los presets, los nombres de presets y bancos, y ahora también los nombres de los
    modelos de AMP subidos.
- **Corregido:** la ventana «Restaurar AMP/CAB de fábrica» no se podía cerrar (por ejemplo cuando no
  encontraba la pedalera por Bluetooth).

## Versión 1.8.0

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
