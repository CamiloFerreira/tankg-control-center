# Política de privacidad — Tank-G Control Center

Última actualización: 27 de octubre de 2026

Tank-G Control Center («la app») es un editor de presets gratuito y de código abierto para la
pedalera M-VAVE Tank-G, disponible para Linux, Windows y Android. Lo desarrolla un particular,
Camilo Ferreira («el desarrollador»). Este documento explica qué datos usa la app y adónde van.

**Resumen:** la app no tiene servidores propios, no tiene cuentas de usuario, no muestra
publicidad y no recoge estadísticas ni telemetría. Tus datos quedan en tu equipo y, solo si tú lo
activas, en tu propio Google Drive.

## 1. Datos que se guardan en tu equipo

- Los presets que lees o editas, las copias de seguridad, los nombres que das a presets y bancos,
  y los ajustes de la app (puerto MIDI, pedalera Bluetooth elegida, calibración).
- En Linux se guardan en `~/.local/share/tankg`, en Windows en `%APPDATA%\tankg` y en Android en
  el almacenamiento privado de la app. Al desinstalar la app o borrar esa carpeta, desaparecen.
- La app se comunica con la pedalera por USB o Bluetooth. Esa comunicación es local y no sale
  de tu equipo.

## 2. Sincronización con Google Drive (opcional)

Solo funciona si eliges **Nube → Conectar con Google Drive** e inicias sesión con tu cuenta de
Google.

- **Permiso que se pide:** `https://www.googleapis.com/auth/drive.file`. Con él, la app solo puede
  ver y modificar los archivos que ella misma creó. No puede leer tus otros archivos, fotos ni
  documentos de Drive.
- **Qué se sube:** el banco de 36 presets, los nombres de presets y bancos, la fecha y un nombre del
  equipo (por ejemplo «Linux · mi-pc» o «Android»). Se guarda en la carpeta «Tank-G Control
  Center» de **tu** Drive, con un historial de hasta 30 versiones.
- **Qué guarda la app:** un token de acceso de Google, solo en tu equipo, para sincronizar sin
  volver a pedirte que inicies sesión. El desarrollador no lo recibe nunca.
- **Quién lo ve:** solo tú. Los datos van directamente de tu equipo a Google; no pasan por ningún
  servidor del desarrollador.
- **Cómo desconectarlo:** con Nube → Desconectar se borra el token del equipo. Para quitar el
  permiso por completo, ve a <https://myaccount.google.com/permissions>. Si quieres borrar los
  datos, elimina la carpeta «Tank-G Control Center» de tu Drive.

El uso y la transferencia de la información recibida de las API de Google a cualquier otra app
cumplen la [Política de Datos de Usuario de los Servicios de las API de Google](https://developers.google.com/terms/api-services-user-data-policy),
incluidos los requisitos de Uso Limitado. Los datos de Google Drive solo se usan para sincronizar
tus presets. No se venden, no se usan para publicidad, no se comparten con terceros y ninguna
persona los lee.

## 3. Generación de presets con IA (opcional)

- **Modo navegador:** la app copia una instrucción y abre Claude, ChatGPT o Gemini, ya sea su web o
  su app. Tú decides si la envías, y queda sujeta a la política de privacidad de ese servicio.
- **Modo clave de API:** si escribes tu propia clave de Anthropic, OpenAI u otro proveedor
  compatible, la app envía tu descripción y el preset actual directamente a ese proveedor. La clave
  se guarda solo en tu equipo, y solo si eliges recordarla.

## 4. Actualizaciones

La app consulta las versiones publicadas en GitHub
(<https://github.com/CamiloFerreira/tankg-control-center-releases>) para avisarte de
actualizaciones y descargarlas. GitHub puede registrar tu dirección IP según su propia política de
privacidad.

## 5. Permisos en Android

- **USB y Bluetooth (incluida la búsqueda de dispositivos cercanos):** solo para conectar con la
  pedalera. No se usan para conocer tu ubicación.
- **Internet:** para Google Drive, la IA y las actualizaciones, como se explica arriba.
- **Instalar paquetes:** para instalar las actualizaciones de la app cuando tú lo confirmas.

## 6. Menores

La app no está dirigida específicamente a menores y no recoge datos personales del desarrollador
ni de ningún tercero.

## 7. Cambios y contacto

Si esta política cambia, la nueva versión se publicará en este mismo archivo, con su fecha
actualizada. Para dudas o solicitudes, abre un issue en
<https://github.com/CamiloFerreira/tankg-control-center/issues>.

---

## Privacy policy (English summary)

Tank-G Control Center has no servers, no user accounts, no ads and no analytics. Presets, backups,
names and settings stay on your device.

**Google Drive sync** is optional. It uses the `drive.file` scope, so the app can only access the
files it creates, which are kept in a "Tank-G Control Center" folder in your own Drive. Data goes
directly from your device to Google. The access token is stored only on your device. Use of
information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements. Drive data is used only to sync your presets: it is never
sold, never used for advertising, never shared with third parties, and never read by humans. You
can revoke access at <https://myaccount.google.com/permissions>.

**AI generation** is optional. Your request is sent only to the provider you choose, using your
own API key, which is stored locally.

**Update checks** contact GitHub.

Contact: <https://github.com/CamiloFerreira/tankg-control-center/issues>.
