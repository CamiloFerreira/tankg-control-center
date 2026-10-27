package io.github.camiloferreira.tankg;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Arrays;
import java.util.UUID;

/**
 * Bluetooth LE link to the pedal (Tank-G v2 advertises "TANK-Gv2_BLE"). The editor protocol runs
 * over the Jieli serial service: writes to ae41, notifications from ae42 (captured from the
 * official app, research/FINDINGS.md). Framing is done in web/js/protocol.js; this class only
 * moves bytes: send(hex) and notifications -> __bleIn(hex), state -> __bleState(state, detail).
 */
@SuppressLint("MissingPermission")   // MainActivity checks the Bluetooth permissions before any call
class Ble {
    interface Js {
        void call(String code);
    }

    static final UUID SERIAL = UUID.fromString("0000ae40-0000-1000-8000-00805f9b34fb");
    static final UUID TX = UUID.fromString("0000ae41-0000-1000-8000-00805f9b34fb");
    static final UUID RX = UUID.fromString("0000ae42-0000-1000-8000-00805f9b34fb");
    static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    private final Context ctx;
    private final Js js;
    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic tx;
    private int mtu = 23;
    private volatile boolean ready;

    Ble(Context ctx, Js js) {
        this.ctx = ctx;
        this.js = js;
    }

    private BluetoothAdapter adapter() {
        BluetoothManager m = (BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
        return m == null ? null : m.getAdapter();
    }

    private void state(String s, String detail) {
        js.call("window.__bleState&&__bleState(" + JSONObject.quote(s) + "," + JSONObject.quote(detail) + ")");
    }

    /** Bonded LE devices whose name points at the pedal: JSON [{name, address}]. */
    String pedals() {
        JSONArray out = new JSONArray();
        BluetoothAdapter a = adapter();
        if (a == null || !a.isEnabled()) return out.toString();
        for (BluetoothDevice d : a.getBondedDevices()) {
            String n = d.getName() == null ? "" : d.getName();
            String low = n.toLowerCase();
            if (d.getType() == BluetoothDevice.DEVICE_TYPE_CLASSIC) continue;
            if (!(low.contains("tank") || low.contains("m-vave") || low.contains("mvave") || low.contains("jieli"))) continue;
            try {
                out.put(new JSONObject().put("name", n).put("address", d.getAddress()));
            } catch (Exception ignored) {
                // plain strings never fail
            }
        }
        return out.toString();
    }

    void open(String address) {
        close();
        BluetoothAdapter a = adapter();
        if (a == null || !a.isEnabled()) {
            state("error", "Bluetooth apagado");
            return;
        }
        gatt = a.getRemoteDevice(address).connectGatt(ctx, false, new BluetoothGattCallback() {
            @Override
            public void onConnectionStateChange(BluetoothGatt g, int status, int newState) {
                if (newState == BluetoothProfile.STATE_CONNECTED) g.requestMtu(247);
                else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                    boolean was = ready;
                    ready = false;
                    g.close();
                    if (g == gatt) gatt = null;
                    state(was ? "disconnected" : "error", "estado " + status);
                }
            }

            @Override
            public void onMtuChanged(BluetoothGatt g, int newMtu, int status) {
                mtu = newMtu;
                g.discoverServices();
            }

            @Override
            public void onServicesDiscovered(BluetoothGatt g, int status) {
                BluetoothGattService s = g.getService(SERIAL);
                if (s == null) {
                    state("error", "la pedalera no ofrece el servicio de edición");
                    return;
                }
                tx = s.getCharacteristic(TX);
                BluetoothGattCharacteristic rx = s.getCharacteristic(RX);
                g.setCharacteristicNotification(rx, true);
                BluetoothGattDescriptor d = rx.getDescriptor(CCCD);
                if (d == null) {
                    ready = true;
                    state("ready", String.valueOf(mtu));
                    return;
                }
                d.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                if (!g.writeDescriptor(d)) state("error", "no se pudo activar las notificaciones");
            }

            @Override
            public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) {
                ready = status == BluetoothGatt.GATT_SUCCESS;
                state(ready ? "ready" : "error", ready ? String.valueOf(mtu) : "notificaciones: estado " + status);
            }

            @Override
            public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
                js.call("window.__bleIn&&__bleIn('" + hex(c.getValue()) + "')");
            }
        }, BluetoothDevice.TRANSPORT_LE);
    }

    /** Writes a frame, split to the negotiated MTU. Runs on the JS bridge thread (blocking is fine). */
    boolean send(byte[] data) {
        BluetoothGatt g = gatt;
        if (!ready || g == null || tx == null) return false;
        tx.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE);
        int chunk = Math.max(20, mtu - 3);
        for (int i = 0; i < data.length; i += chunk) {
            tx.setValue(Arrays.copyOfRange(data, i, Math.min(data.length, i + chunk)));
            boolean ok = false;
            for (int tries = 0; tries < 40 && !(ok = g.writeCharacteristic(tx)); tries++) {
                try {
                    Thread.sleep(10);   // the stack accepts one operation at a time
                } catch (InterruptedException e) {
                    return false;
                }
            }
            if (!ok) return false;
        }
        return true;
    }

    void close() {
        ready = false;
        BluetoothGatt g = gatt;
        gatt = null;
        if (g != null) {
            g.disconnect();
            g.close();
        }
    }

    private static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder(b.length * 2);
        for (byte x : b) sb.append(String.format("%02x", x & 0xff));
        return sb.toString();
    }
}
