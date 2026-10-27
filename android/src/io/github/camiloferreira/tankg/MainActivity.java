package io.github.camiloferreira.tankg;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
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

/**
 * Tank-G Control for Android: the web app (assets/web, same files as the repo's web/ folder)
 * in a WebView, plus a bridge to android.media.midi so the page can talk to the pedal over
 * USB-OTG. The page is served from https://appassets.androidplatform.net so ES modules and
 * localStorage work like on a normal secure origin.
 *
 * Bridge (window.AndroidMidi): list() -> JSON [{id, name}], open(id) -> __midiOpened(id, ok, err),
 * send(hex), close(), saveFile(name, base64). Incoming complete SysEx frames -> __midiIn(hex);
 * device plug/unplug -> __midiState(state, name).
 */
public class MainActivity extends Activity {
    private static final String HOST = "appassets.androidplatform.net";

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
        web.addJavascriptInterface(new Bridge(), "AndroidMidi");
        setContentView(web);

        midi = (MidiManager) getSystemService(MIDI_SERVICE);
        if (midi != null) midi.registerDeviceCallback(deviceCallback, ui);
        if (state != null) web.restoreState(state);
        else web.loadUrl("https://" + HOST + "/index.html");
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();   // the page uses history to close its sheets
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (midi != null) midi.unregisterDeviceCallback(deviceCallback);
        closeDevice();
        web.destroy();
        super.onDestroy();
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
        @JavascriptInterface
        public String list() {
            JSONArray out = new JSONArray();
            if (midi == null) return out.toString();
            for (MidiDeviceInfo info : midi.getDevices()) {
                if (info.getInputPortCount() == 0 || info.getOutputPortCount() == 0) continue;
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
            MidiDeviceInfo found = null;
            for (MidiDeviceInfo info : midi.getDevices()) if (info.getId() == id) found = info;
            if (found == null) {
                js("__midiOpened(" + id + ",false,'no existe')");
                return;
            }
            midi.openDevice(found, dev -> {
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
            }, ui);
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

        /** Saves a backup into Downloads (Android 10+) or the app's own folder (older). */
        @JavascriptInterface
        public String saveFile(String name, String base64) {
            byte[] data = Base64.decode(base64, Base64.DEFAULT);
            try {
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                    v.put(MediaStore.Downloads.MIME_TYPE, "application/octet-stream");
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
            if (path.endsWith(".json") || path.endsWith(".webmanifest")) return "application/json";
            return "application/octet-stream";
        }
    }
}
