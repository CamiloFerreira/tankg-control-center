package io.github.camiloferreira.tankg;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.media.midi.MidiDevice;
import android.media.midi.MidiDeviceInfo;
import android.media.midi.MidiInputPort;
import android.media.midi.MidiManager;
import android.media.midi.MidiOutputPort;
import android.media.midi.MidiReceiver;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.provider.Settings;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Iterator;

/**
 * Tank-G Control for Android: the UI of android/ui (packed as assets/web)
 * in a WebView, plus a bridge to android.media.midi so the page can talk to the pedal over
 * USB-OTG. The page is served from https://appassets.androidplatform.net so ES modules and
 * localStorage work like on a normal secure origin.
 *
 * Bridge (window.AndroidMidi): list() -> JSON [{id, name}], open(id) -> __midiOpened(id, ok, err),
 * send(hex), close(), saveFile(name, base64, mime), httpRequest(id, method, url, headers, body) ->
 * __httpDone(id, status, text) (text is base64 when the headers carry X-Tankg-Base64: 1), openUrl(url), openChat(package, url, text), copyText(text), version(),
 * installUpdate(apkUrl, sumsUrl) -> __updateState(state, detail) (refuses an APK not in SHA256SUMS),
 * blePermission(), blePedals(), bleOpen(address) -> __bleState(state, detail), bleSend(hex),
 * bleClose(); Bluetooth notifications -> __bleIn(hex). Incoming complete SysEx frames ->
 * __midiIn(hex); device plug/unplug -> __midiState(state, name). <input type=file> opens the
 * system file picker.
 */
public class MainActivity extends Activity {
    private static final String HOST = "appassets.androidplatform.net";
    private static final String INSTALL_ACTION = "io.github.camiloferreira.tankg.INSTALL_STATUS";
    private static final int PICK_FILE = 1;
    private ValueCallback<Uri[]> pickCallback;
    private Ble ble;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;
    private MidiManager midi;
    private MidiDevice device;
    private MidiInputPort toPedal;     // we send into the device's input port
    private MidiOutputPort fromPedal;  // and listen on its output port
    private final ByteArrayOutputStream frame = new ByteArrayOutputStream();
    private boolean inSysex;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);   // debug builds only: chrome://inspect over adb
        }
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        web.setBackgroundColor(0xFF15191D);
        web.setWebViewClient(new AssetClient());
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (pickCallback != null) pickCallback.onReceiveValue(null);
                pickCallback = callback;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                try {
                    startActivityForResult(Intent.createChooser(i, "Abrir archivo"), PICK_FILE);
                } catch (Exception e) {
                    pickCallback = null;
                    return false;
                }
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(), "AndroidMidi");
        setContentView(web);

        ble = new Ble(this, this::js);
        midi = (MidiManager) getSystemService(MIDI_SERVICE);
        if (midi != null) midi.registerDeviceCallback(deviceCallback, ui);
        if (state != null) web.restoreState(state);
        else web.loadUrl("https://" + HOST + "/index.html");
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PICK_FILE || pickCallback == null) return;
        Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
        pickCallback.onReceiveValue(uri == null ? null : new Uri[]{uri});
        pickCallback = null;
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        // The page closes its own dialog, sheet or preset list (window.__back() returns true); only
        // when nothing is open does back leave the app. Not history: WebView skips entries pushed
        // without a user gesture, so back used to close the app instead of the menu.
        web.evaluateJavascript("window.__back ? window.__back() : false", handled -> {
            if (!"true".equals(handled)) super.onBackPressed();
        });
    }

    @Override
    protected void onDestroy() {
        ble.close();
        try {
            unregisterReceiver(installReceiver);
        } catch (IllegalArgumentException ignored) {
            // never registered
        }
        if (midi != null) midi.unregisterDeviceCallback(deviceCallback);
        closeDevice();
        web.destroy();
        super.onDestroy();
    }

    private boolean bluetoothAllowed() {
        return Build.VERSION.SDK_INT < 31 || checkSelfPermission("android.permission.BLUETOOTH_CONNECT") == PackageManager.PERMISSION_GRANTED;
    }

    private void js(String code) {
        ui.post(() -> web.evaluateJavascript(code, null));
    }

    private static String quote(String s) {
        return JSONObject.quote(s == null ? "" : s);
    }

    private static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder(b.length * 2);
        for (byte x : b) sb.append(String.format("%02x", x & 0xff));
        return sb.toString();
    }

    private static byte[] unhex(String h) {
        byte[] out = new byte[h.length() / 2];
        for (int i = 0; i < out.length; i++) out[i] = (byte) Integer.parseInt(h.substring(2 * i, 2 * i + 2), 16);
        return out;
    }

    private static String deviceName(MidiDeviceInfo info) {
        Bundle p = info.getProperties();
        String name = p.getString(MidiDeviceInfo.PROPERTY_NAME);
        if (name == null || name.isEmpty()) name = p.getString(MidiDeviceInfo.PROPERTY_PRODUCT);
        return name == null ? "MIDI " + info.getId() : name;
    }

    private synchronized void closeDevice() {
        try {
            if (fromPedal != null) fromPedal.close();
            if (toPedal != null) toPedal.close();
            if (device != null) device.close();
        } catch (IOException ignored) {
            // closing must never fail the caller
        }
        fromPedal = null;
        toPedal = null;
        device = null;
        inSysex = false;
        frame.reset();
    }

    /** Reassembles SysEx frames that Android may deliver in several chunks. */
    private final MidiReceiver receiver = new MidiReceiver() {
        @Override
        public void onSend(byte[] msg, int offset, int count, long timestamp) {
            synchronized (MainActivity.this) {
                for (int i = offset; i < offset + count; i++) {
                    int b = msg[i] & 0xff;
                    if (b == 0xF0) {
                        frame.reset();
                        inSysex = true;
                    }
                    if (!inSysex) continue;   // only SysEx replies matter to the protocol
                    frame.write(b);
                    if (b == 0xF7) {
                        inSysex = false;
                        js("window.__midiIn&&__midiIn('" + hex(frame.toByteArray()) + "')");
                    }
                }
            }
        }
    };

    private final MidiManager.DeviceCallback deviceCallback = new MidiManager.DeviceCallback() {
        @Override
        public void onDeviceAdded(MidiDeviceInfo info) {
            js("window.__midiState&&__midiState('connected'," + quote(deviceName(info)) + ")");
        }

        @Override
        public void onDeviceRemoved(MidiDeviceInfo info) {
            if (device != null && device.getInfo().getId() == info.getId()) closeDevice();
            js("window.__midiState&&__midiState('disconnected'," + quote(deviceName(info)) + ")");
        }
    };

    private class Bridge {
        /** USB/virtual MIDI devices. */
        @JavascriptInterface
        public String list() {
            JSONArray out = new JSONArray();
            if (midi == null) return out.toString();
            for (MidiDeviceInfo info : midi.getDevices()) {
                if (info.getInputPortCount() == 0 || info.getOutputPortCount() == 0) continue;
                if (info.getType() == MidiDeviceInfo.TYPE_BLUETOOTH) continue;   // BLE goes through Ble (see below)
                try {
                    out.put(new JSONObject().put("id", info.getId()).put("name", deviceName(info)));
                } catch (Exception ignored) {
                    // JSONObject.put only throws for non-finite numbers
                }
            }
            return out.toString();
        }

        @JavascriptInterface
        public void open(int id) {
            closeDevice();
            MidiManager.OnDeviceOpenedListener opened = dev -> {
                if (dev == null) {
                    js("__midiOpened(" + id + ",false,'Android no pudo abrirlo')");
                    return;
                }
                synchronized (MainActivity.this) {
                    device = dev;
                    toPedal = dev.openInputPort(0);
                    fromPedal = dev.openOutputPort(0);
                    if (toPedal == null || fromPedal == null) {
                        closeDevice();
                        js("__midiOpened(" + id + ",false,'puerto ocupado por otra app')");
                        return;
                    }
                    fromPedal.connect(receiver);
                }
                js("__midiOpened(" + id + ",true,'')");
            };
            MidiDeviceInfo found = null;
            for (MidiDeviceInfo info : midi.getDevices()) if (info.getId() == id) found = info;
            if (found == null) {
                js("__midiOpened(" + id + ",false,'no existe')");
                return;
            }
            midi.openDevice(found, opened, ui);
        }

        @JavascriptInterface
        public boolean send(String hexData) {
            MidiInputPort port = toPedal;
            if (port == null) return false;
            try {
                byte[] data = unhex(hexData);
                port.send(data, 0, data.length);
                return true;
            } catch (IOException e) {
                return false;
            }
        }

        @JavascriptInterface
        public void close() {
            closeDevice();
        }

        /** Android 12+: asks for the Bluetooth permissions; true when already granted. */
        @JavascriptInterface
        public boolean blePermission() {
            if (Build.VERSION.SDK_INT < 31) return true;
            String[] perms = {"android.permission.BLUETOOTH_CONNECT", "android.permission.BLUETOOTH_SCAN"};
            boolean ok = checkSelfPermission(perms[0]) == PackageManager.PERMISSION_GRANTED
                    && checkSelfPermission(perms[1]) == PackageManager.PERMISSION_GRANTED;
            if (!ok) ui.post(() -> requestPermissions(perms, 7));
            return ok;
        }

        /** Bonded Bluetooth pedals: JSON [{name, address}]. */
        @JavascriptInterface
        public String blePedals() {
            return bluetoothAllowed() ? ble.pedals() : "[]";
        }

        @JavascriptInterface
        public void bleOpen(String address) {
            if (bluetoothAllowed()) ble.open(address);
        }

        @JavascriptInterface
        public boolean bleSend(String hexData) {
            return ble.send(unhex(hexData));
        }

        @JavascriptInterface
        public void bleClose() {
            ble.close();
        }

        @JavascriptInterface
        public String version() {
            try {
                return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
            } catch (PackageManager.NameNotFoundException e) {
                return "";
            }
        }

        @JavascriptInterface
        public void openUrl(String url) {
            ui.post(() -> {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                    // no browser installed
                }
            });
        }

        /** Hands the prompt to the AI service's app when installed: shared as text (it lands in the
         *  message box, the standard Android share target), else the app is opened (the prompt is on the
         *  clipboard anyway), else the web page. Returns "shared", "app" or "web". */
        @JavascriptInterface
        public String openChat(String pkg, String url, String text) {
            PackageManager pm = getPackageManager();
            Intent intent = null;
            String where = "web";
            if (!pkg.isEmpty()) {
                Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain").setPackage(pkg)
                        .putExtra(Intent.EXTRA_TEXT, text);
                Intent view = new Intent(Intent.ACTION_VIEW, Uri.parse(url)).setPackage(pkg);
                if (!text.isEmpty() && share.resolveActivity(pm) != null) {
                    intent = share;
                    where = "shared";
                } else if (view.resolveActivity(pm) != null) {
                    intent = view;
                    where = "app";
                } else if ((intent = pm.getLaunchIntentForPackage(pkg)) != null) {
                    where = "app";
                }
            }
            Intent chosen = intent != null ? intent : new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            ui.post(() -> {
                try {
                    startActivity(chosen.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                } catch (Exception e) {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                }
            });
            return where;
        }

        /** Older pages: open the app or the web page without sharing text. */
        @JavascriptInterface
        public String openChat(String pkg, String url) {
            return openChat(pkg, url, "");
        }

        @JavascriptInterface
        public void copyText(String text) {
            ui.post(() -> {
                ClipboardManager cm = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("Tank-G", text));
            });
        }

        /** POST for the AI providers (no CORS, local servers work). Answer -> __httpDone. */
        @JavascriptInterface
        public void httpPost(int id, String url, String headersJson, String body) {
            httpRequest(id, "POST", url, headersJson, body);
        }

        /** GET / POST / DELETE (AI providers, Google sign-in and Drive). Answer -> __httpDone(id, status, text). */
        @JavascriptInterface
        public void httpRequest(int id, String method, String url, String headersJson, String body) {
            new Thread(() -> {
                int status = 0;
                String text;
                try {
                    HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                    c.setRequestMethod(method);
                    c.setConnectTimeout(20000);
                    c.setReadTimeout(120000);
                    boolean hasBody = body != null && !body.isEmpty();
                    c.setDoOutput(hasBody);
                    JSONObject h = new JSONObject(headersJson);
                    boolean binary = "1".equals(h.optString("X-Tankg-Base64"));   // answer as base64 (model files)
                    h.remove("X-Tankg-Base64");
                    for (Iterator<String> it = h.keys(); it.hasNext(); ) {
                        String k = it.next();
                        c.setRequestProperty(k, h.getString(k));
                    }
                    if (hasBody) {
                        try (OutputStream out = c.getOutputStream()) {
                            out.write(body.getBytes(StandardCharsets.UTF_8));
                        }
                    }
                    status = c.getResponseCode();
                    InputStream in = status >= 400 ? c.getErrorStream() : c.getInputStream();
                    byte[] raw = in == null ? new byte[0] : readAll(in);
                    text = binary && status < 400 ? android.util.Base64.encodeToString(raw, android.util.Base64.NO_WRAP)
                            : new String(raw, StandardCharsets.UTF_8);
                } catch (Exception e) {
                    text = String.valueOf(e.getMessage());
                }
                js("__httpDone(" + id + "," + status + "," + quote(text) + ")");
            }).start();
        }

        /** Downloads the APK, checks its SHA-256 and hands it to the system installer. */
        @JavascriptInterface
        public void installUpdate(String url, String sumsUrl) {
            if (Build.VERSION.SDK_INT >= 26 && !getPackageManager().canRequestPackageInstalls()) {
                update("permission", "Permite «instalar apps desconocidas» para Tank-G y vuelve a pulsar Actualizar.");
                ui.post(() -> startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getPackageName()))));
                return;
            }
            new Thread(() -> {
                try {
                    update("download", "Descargando…");
                    byte[] apk = download(url);
                    String sha256 = "";
                    for (String line : new String(download(sumsUrl), StandardCharsets.UTF_8).split("\n")) {
                        String[] parts = line.trim().split("\\s+");
                        if (parts.length == 2 && parts[1].replace("*", "").equals("TankG-android.apk")) sha256 = parts[0];
                    }
                    if (sha256.isEmpty() || !sha256.equalsIgnoreCase(hex(MessageDigest.getInstance("SHA-256").digest(apk)))) {
                        update("error", "La descarga no coincide con SHA256SUMS: no se instala.");
                        return;
                    }
                    update("install", "Instalando…");
                    PackageInstaller pi = getPackageManager().getPackageInstaller();
                    PackageInstaller.SessionParams params =
                            new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
                    params.setAppPackageName(getPackageName());
                    int sessionId = pi.createSession(params);
                    try (PackageInstaller.Session session = pi.openSession(sessionId)) {
                        try (OutputStream out = session.openWrite("TankG.apk", 0, apk.length)) {
                            out.write(apk);
                            session.fsync(out);
                        }
                        ui.post(() -> {
                            IntentFilter f = new IntentFilter(INSTALL_ACTION);
                            if (Build.VERSION.SDK_INT >= 33) registerReceiver(installReceiver, f, Context.RECEIVER_NOT_EXPORTED);
                            else registerReceiver(installReceiver, f);
                        });
                        Intent status = new Intent(INSTALL_ACTION).setPackage(getPackageName());
                        int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0);
                        session.commit(PendingIntent.getBroadcast(MainActivity.this, sessionId, status, flags).getIntentSender());
                    }
                } catch (Exception e) {
                    update("error", "No se pudo actualizar: " + e.getMessage());
                }
            }).start();
        }

        /** Saves a file into Downloads (Android 10+) or the app's own folder (older). */
        @JavascriptInterface
        public String saveFile(String name, String base64) {
            return saveFile(name, base64, "application/octet-stream");
        }

        @JavascriptInterface
        public String saveFile(String name, String base64, String mime) {
            byte[] data = Base64.decode(base64, Base64.DEFAULT);
            try {
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                    v.put(MediaStore.Downloads.MIME_TYPE, mime);
                    Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                    if (uri == null) return "";
                    try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                        out.write(data);
                    }
                    return "Descargas/" + name;
                }
                File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                File f = new File(dir, name);
                try (OutputStream out = new FileOutputStream(f)) {
                    out.write(data);
                }
                return f.getAbsolutePath();
            } catch (IOException e) {
                return "";
            }
        }
    }

    private void update(String state, String detail) {
        js("window.__updateState&&__updateState(" + quote(state) + "," + quote(detail) + ")");
    }

    private final BroadcastReceiver installReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
            if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
                if (confirm != null) startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                update("confirm", "Confirma la instalación en la ventana de Android.");
            } else if (status == PackageInstaller.STATUS_SUCCESS) {
                update("done", "Actualizado.");
            } else {
                update("error", "Android no instaló la actualización: " + intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE));
            }
        }
    };

    private static byte[] readAll(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
        in.close();
        return out.toByteArray();
    }

    /** GET following redirects (GitHub release assets redirect to a CDN). */
    private static byte[] download(String url) throws IOException {
        for (int hops = 0; hops < 5; hops++) {
            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(20000);
            c.setReadTimeout(60000);
            int code = c.getResponseCode();
            if (code >= 300 && code < 400 && c.getHeaderField("Location") != null) {
                url = c.getHeaderField("Location");
                continue;
            }
            if (code != 200) throw new IOException("HTTP " + code);
            return readAll(c.getInputStream());
        }
        throw new IOException("demasiadas redirecciones");
    }

    /** Serves assets/web at https://appassets.androidplatform.net/; other links open in the browser. */
    private class AssetClient extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (!HOST.equals(u.getHost())) return null;
            String path = u.getPath() == null || u.getPath().equals("/") ? "/index.html" : u.getPath();
            try {
                InputStream in = getAssets().open("web" + path);
                WebResourceResponse r = new WebResourceResponse(mime(path), "utf-8", in);
                r.setResponseHeaders(java.util.Collections.singletonMap("Cache-Control", "no-cache"));
                return r;
            } catch (IOException e) {
                return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found",
                        null, new ByteArrayInputStream(new byte[0]));
            }
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            if (HOST.equals(req.getUrl().getHost())) return false;
            startActivity(new Intent(Intent.ACTION_VIEW, req.getUrl()));
            return true;
        }

        private String mime(String path) {
            if (path.endsWith(".html")) return "text/html";
            if (path.endsWith(".js")) return "text/javascript";
            if (path.endsWith(".css")) return "text/css";
            if (path.endsWith(".png")) return "image/png";
            if (path.endsWith(".svg")) return "image/svg+xml";
            if (path.endsWith(".json") || path.endsWith(".webmanifest")) return "application/json";
            return "application/octet-stream";
        }
    }
}
