# Seguridad

Política de seguridad de Tank-G Control Center (Windows, Linux y Android) y registro público de las
vulnerabilidades corregidas. La revisión sigue como marco:

- **ISO/IEC 27001:2022 / 27002:2022** (Anexo A): desarrollo seguro y gestión de vulnerabilidades.
- **ISO/IEC 27034**: seguridad de aplicaciones.
- **ISO/IEC 29147 / 30111**: divulgación y tratamiento de vulnerabilidades.
- Como guía técnica, **OWASP MASVS** para la app Android (WebView con puente nativo).

## Versiones soportadas

Solo la última versión recibe correcciones. Desde la **1.11.0**, cada release declara una **versión
mínima** (`MIN_VERSION` en `tankg/version.py`, escrita en las notas del release como
`<!-- tankg-min-version: X -->`). Las apps anteriores a esa versión **no dejan trabajar** hasta
actualizarse: solo ofrecen «Actualizar» o «Salir», y no se conectan a la pedalera ni suben nada a la
nube. Sin internet la app funciona, porque no puede saber si hay una actualización obligatoria. La línea
de comandos (`tankg list`, etc.) no se bloquea.

| Versión | Estado |
|---|---|
| 1.11.x | Soportada. Versión mínima obligatoria |
| ≤ 1.10.2 | Sin soporte: actualizar a mano a la 1.11.0 (estas versiones no conocen el bloqueo) |

## Cómo reportar una vulnerabilidad

Escribe en privado a **camiloferrei9@gmail.com** con el asunto «Seguridad Tank-G». Indica la versión,
la plataforma y los pasos para reproducirla. Por favor, no abras un issue público. Respuesta inicial:
7 días como máximo. El arreglo sale como actualización obligatoria cuando el riesgo lo justifica, y la
vulnerabilidad se publica en este archivo y en las notas del release (ISO/IEC 29147).

## Revisión del 2026-11-03 (corregido en 1.11.0)

Se revisaron todas las entradas de datos de la app: archivos importados (`.tgbank`, `.tgpreset`,
`.tgset`, `.tgpack`), red (actualizaciones, IA, Google Drive, comunidad M-VAVE), el puente
JavaScript↔Android, el almacenamiento local de secretos, la escritura en la pedalera y la cadena de
compilación (GitHub Actions).

Gravedad: **Alta** = un atacante obtiene control o privilegios; **Media** = filtra secretos o altera
datos/dispositivo con alguna condición previa; **Baja** = defensa en profundidad o fallo de
disponibilidad.

| # | Gravedad | Plataforma | Vulnerabilidad | Afectadas | Control ISO 27002 |
|---|---|---|---|---|---|
| 1 | Alta | Linux (.deb) | Escalada a root en la autoactualización del `.deb` | Solo el commit `f66a051` de `main` (nunca en un release) | 8.28, 8.25 |
| 2 | Media | Android ≤ 12 | Receptor de estado de instalación expuesto: redirección de Intents | APK ≤ 1.10.2 | 8.26, 8.28 |
| 3 | Media | Linux/macOS | Token de Google Drive y claves de IA legibles por otros usuarios | ≤ 1.10.2 | 5.17, 8.3, 8.12 |
| 4 | Media | Todas | Un archivo manipulado podía enviar a la pedalera valores fuera de rango | ≤ 1.10.2 | 8.26, 8.28 |
| 5 | Media | Escritorio y Android | La clave de IA podía viajar sin cifrar o reenviarse en una redirección | ≤ 1.10.2 | 8.20, 8.24 |
| 6 | Baja | Android | El puente aceptaba cualquier esquema de URL y nombres de archivo con rutas | APK ≤ 1.10.2 | 8.26, 8.28 |
| 7 | Baja | Android | WebView con puente nativo sin Content-Security-Policy | APK ≤ 1.10.2 | 8.26 |
| 8 | Baja | Android | Las descargas de actualización seguían redirecciones a `http://` | APK ≤ 1.10.2 | 8.20, 8.24 |
| 9 | Baja | Escritorio | Archivos JSON mal formados cerraban la operación con un error inesperado | ≤ 1.10.2 | 8.28 |
| 10 | Baja | Windows | Script de actualización con nombre fijo en `%TEMP%` | ≤ 1.10.2 | 8.28 |
| 11 | Baja | CI/CD | Permisos de escritura en todos los jobs y acciones sin fijar a un commit | Repositorio | 5.21, 8.25, 8.32 |

### 1. Escalada a root en la autoactualización del `.deb` (Alta)

`updater.install` escribía el paquete nuevo en `/tmp/TankG-linux-amd64.deb` (nombre fijo, carpeta
compartida) y luego lo instalaba como root con `pkexec apt-get install`. Otro usuario local podía:

- crear antes ese nombre como enlace simbólico, para escribir en un archivo ajeno;
- o reemplazar el `.deb` verificado entre la comprobación de `SHA256SUMS` y la instalación, para que
  apt instalara su paquete como root.

**Corrección:**
- el paquete va a una carpeta nueva y privada (`mkdtemp`), se crea con `O_EXCL`, que no sigue enlaces;
- los argumentos llegan a `sh` como parámetros, no interpolados en el comando.

Este código entró en `main` el 2026-11-03 junto con el soporte `.deb` y se corrigió antes de publicarse
en ningún release. El `.deb` de la 1.10.2 lleva el código anterior, que no tiene esta función.

### 2. Receptor de instalación expuesto en Android ≤ 12 (Media)

En Android 12 y anteriores, el `BroadcastReceiver` que recibe el estado de una autoactualización se
registraba sin protección. Cualquier app instalada podía enviarle un estado falso
`STATUS_PENDING_USER_ACTION` con un `Intent` propio, y Tank-G lo lanzaba con su identidad.

**Corrección:**
- el receptor exige un permiso propio de nivel `signature`, así que solo nuestra app puede enviárselo;
- solo atiende a la sesión de instalación que la app abrió;
- solo lanza las pantallas de confirmación del sistema (`CONFIRM_*`), y nunca con permisos sobre URIs.

### 3. Secretos legibles por otros usuarios (Media)

`settings.json` guarda el token de refresco de Google Drive y, si el usuario lo pide, las claves de API
de IA. Se escribía con los permisos por defecto (0644), de modo que en un equipo Linux con varios
usuarios cualquiera podía leerlo y usar esas credenciales.

**Corrección:**
- la carpeta de datos queda en 0700 y `settings.json` en 0600;
- la escritura es atómica: un corte no deja el archivo a medias.

### 4. Valores fuera de rango hacia la pedalera (Media)

Los bytes de un `.tgpreset`, `.tgset`, `.tgpack` o banco se enviaban a la pedalera tal cual. Un archivo
manipulado o dañado podía escribir un TYPE (modelo de AMP) o un IR CAB inexistente, con un efecto
desconocido en el firmware.

**Corrección:** antes de cada escritura, por USB y por Bluetooth, se comprueban los bytes verificados en
hardware (TYPE ≤ 8, IR CAB ≤ 8). Si alguno está fuera de rango, el preset no se envía:
`model.check_writable` en escritorio y `checkRecord` en `protocol.js`. Los bytes inferidos no se tocan,
porque deben conservarse tal cual (`research/FINDINGS.md`).

### 5. Clave de IA sin cifrar o reenviada (Media)

El proveedor «compatible» aceptaba cualquier URL, incluida `http://` hacia internet: la clave de API y la
descripción viajaban sin cifrar. Además, una redirección HTTP reenviaba la cabecera con la clave a otra
dirección.

**Corrección:** solo se aceptan URLs `https://`, o `http://` hacia este equipo o la red local (Ollama,
LM Studio), con la misma regla en `ai.py` y `ai.js`. En escritorio, una redirección en la llamada a la
IA se rechaza en vez de seguirse.

### 6–8. Puente Android (Baja)

- **6.** `openUrl`, `openChat` y `httpRequest` aceptaban cualquier esquema (`intent:`, `file:`…); ahora
  solo `http(s)`. `saveFile` aceptaba nombres con rutas (`../`), que en Android ≤ 9 salían de la
  carpeta de descargas de la app; ahora el nombre se limpia.
- **7.** El WebView que tiene el puente nativo no tenía Content-Security-Policy. Ahora solo ejecuta el
  código propio de la app: sin scripts en línea ni remotos, sin marcos. El manifiesto prohíbe además el
  tráfico sin cifrar (`usesCleartextTraffic=false`).
- **8.** Las descargas de actualización seguían redirecciones a `http://`. Ahora se exige `https://` en
  cada salto; la integridad ya la garantizaba `SHA256SUMS` y la firma del APK.

### 9–10. Robustez (Baja)

- **9.** Un `.tgpreset` o `.tgset` con tipos inesperados (una lista en vez de un objeto, un número en
  `raw`) provocaba un error interno en vez de un mensaje claro. Ahora todo se valida y se rechaza con
  «no es un archivo válido». Una respuesta de IA con números infinitos tampoco rompe la generación.
- **10.** En Windows, el script de actualización tenía un nombre fijo en `%TEMP%`. Ahora va en una
  carpeta temporal nueva.

### 11. Cadena de suministro (CI/CD, Baja)

Todos los jobs de GitHub Actions tenían permiso de escritura en el repositorio, y las acciones se
referenciaban por etiqueta (`@v5`), que su autor puede mover.

**Corrección:**
- permiso de solo lectura por defecto; escritura solo en el job que publica el release;
- cada acción se fija al commit exacto (SHA).

## Controles que ya existían

- Las autoactualizaciones verifican `SHA256SUMS`. En Android, el sistema exige además la misma firma
  del APK, y el usuario confirma cada instalación.
- Antes de escribir en la pedalera se hace un backup, se escriben solo los presets que cambiaron y se
  verifica releyéndolos.
- La sincronización con Google Drive usa el permiso mínimo `drive.file`: solo los archivos que crea la
  app.
- El cliente OAuth (`cloud_secrets.json`) y las claves de firma nunca se suben al repositorio (CI usa
  secretos).
- APK: `allowBackup=false`, depuración del WebView solo en compilaciones debug, sin acceso a archivos
  desde el WebView, y enlaces externos abiertos en el navegador del sistema.

## Pendiente (riesgo aceptado por ahora)

| Riesgo | Por qué sigue | Mejora prevista |
|---|---|---|
| `SHA256SUMS` viene del mismo release que el ejecutable: protege de descargas dañadas, no de una cuenta de GitHub comprometida | Hace falta una clave de firma y gestionarla | Firmar los releases con una clave Ed25519 propia y verificarla en las tres apps (ISO 27002 8.24) |
| Los secretos se guardan en un archivo (0600), no en el llavero del sistema | Añade una dependencia (`keyring`) en escritorio | Usar el llavero del sistema (Secret Service, Credential Manager) |
| El `.exe` lleva un certificado autofirmado | Un certificado de una CA cuesta dinero | Certificado de firma de código de una CA |
| Dependencias de Python con versión mínima, no fijadas con hash | Simplicidad del desarrollo | Archivo de bloqueo con hashes para las compilaciones de release |
| Las apps ≤ 1.10.2 no conocen el bloqueo por versión mínima | Se añade en la 1.11.0 | Actualizar a mano una vez; desde la 1.11.0 es automático |
