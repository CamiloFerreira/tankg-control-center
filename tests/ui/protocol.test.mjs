// Run by tests/test_ui.py with node: the JS protocol must produce the frames captured from
// the real pedal (same goldens as tests/test_tankg.py) and behave like the Python TankG.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as P from "../../android/ui/js/protocol.js";
import { LIBRARY, FIELDS } from "../../android/ui/js/data.js";

const hex = b => Array.from(b, v => v.toString(16).padStart(2, "0")).join(" ");
const LIVE = Uint8Array.from(readFileSync(new URL("../live_bank.bin", import.meta.url)));

// golden frames captured on 2026-10-26
const rec = P.fromHex("010000012308442e3c343000006b6b090507550000");
assert.equal(hex(P.build(P.CLS_WRITE, P.CMD_READ + 8 * 21, 2 + 21 * 35, 21, 0, rec)),
  "f0 00 32 09 69 01 00 00 02 61 05 00 00 50 02 00 00 01 00 00 08 30 04 02 22 2e 78 50 01 " +
  "03 00 40 35 6b 12 14 38 50 0a 00 00 04 01 f7");
assert.equal(hex(P.COMMIT_FRAME), "f0 00 32 09 41 00 00 00 02 00 00 00 00 0f 00 00 00 0b 00 f7");
assert.equal(hex(P.readFrame(0, 86, 2)), "f0 00 32 0d 41 00 00 00 02 00 00 00 00 62 0a 00 00 05 01 f7");
assert.equal(hex(P.readFrame(0, 448, 1)), "f0 00 32 0d 41 00 00 00 02 00 00 00 00 01 38 00 00 2a 00 f7");

// codec round trips and checksum rejection
const all = Uint8Array.from({ length: 256 }, (_, i) => i);
assert.deepEqual(P.unpack7(P.pack7(all)).slice(0, 256), Array.from(all));
const reply = P.build(P.CLS_READ, P.CMD_READ + 8 * 758, 0, 758, 0, LIVE);
assert.deepEqual(P.parse(reply).payload, LIVE);
const bad = Uint8Array.from(reply); bad[bad.length - 3] ^= 1;
assert.throws(() => P.parse(bad));
assert.deepEqual(P.Bank.fromBytes(LIVE).toBytes(), LIVE);
assert.equal(P.slotName(0), "1A"); assert.equal(P.slotName(35), "9D");

// device flow against the fake pedal: write + ACK + commit, read-back verification, select
const pedal = P.fakePedal(LIVE, { latency: 1 });
const dev = new P.TankG(pedal);
const bank = await dev.readBank();
const target = bank.copy();
target.presets[1][5] = 0;
const steps = [];
const after = await dev.writePresets(target, [1], (n, t, s) => steps.push([n, t, s]));
assert.deepEqual(steps, [[0, 1, 1], [1, 1, null]]);
assert.equal(after.presets[1][5], 0);
assert.equal(pedal.sent.filter(s => hex(s) === hex(P.COMMIT_FRAME)).length, 1);
dev.selectPreset(1);
assert.deepEqual(Array.from(pedal.sent.at(-1)), [0xc0, 0x01]);

const dropping = P.fakePedal(LIVE, { latency: 1, dropWrites: true });
const dev2 = new P.TankG(dropping);
const t2 = (await dev2.readBank()).copy(); t2.presets[0][17] = 3;
await assert.rejects(dev2.writePresets(t2, [0]), P.DeviceError);

// generated data is sane
assert.equal(FIELDS.length, 18);
assert.ok(LIBRARY.length >= 100 && LIBRARY.every(b => b.presets.length === 4 && b.presets.every(p => p.hex.length === 42)));
console.log("web protocol ok");

// Bluetooth framing: frames captured from the official app over BLE on 2026-10-27
const rec9d = P.fromHex("010001011e07643e483c5f0000143c320f04ff0078");
assert.equal(hex(P.bleFrame(0x23, 2, 0, 4)), "00 59 23 08 00 00 04 00 00 00 20 04 00 00 d7");
assert.equal(hex(P.bleFrame(0x22, 0, 2 + 21 * 35, 21, Array.from(rec9d))),
  "00 59 22 1d 00 00 04 e1 02 00 00 15 00 00 01 00 01 01 1e 07 64 3e 48 3c 5f 00 00 14 3c 32 0f 04 ff 00 78 4a");
assert.equal(hex(P.bleFrame(0x22, 0xf, 0, 0)), "00 59 22 08 00 00 04 00 00 00 f0 00 00 00 0b");
assert.equal(hex(P.bleFrame(0x22, 0xe, 35, 1, [1])), "00 59 22 09 00 00 04 23 00 00 e0 01 00 00 01 f6");
// reply split across notifications, with garbage before it
const d = new P.BleDeframer();
const bleReply = P.fromHex("0059231d000004e1020000150000010001011e07643e483c5f0000143c320f04ff00784a");
assert.deepEqual(d.push([0x7f, ...bleReply.slice(0, 10)]), []);
const got = d.push(bleReply.slice(10));
assert.equal(got.length, 1); assert.equal(got[0].cmd, 0x23); assert.deepEqual(got[0].payload.slice(8), Array.from(rec9d));

// TankGBle against a fake pedal that speaks the captured framing
function fakeBlePedal(image) {
  const mem = Uint8Array.from(image); let cb = null; const sent = [];
  const deframer = new P.BleDeframer();
  return { mem, sent, onMessage: f => { cb = f; }, close() {},
    send(frame) {
      sent.push(Uint8Array.from(frame));
      for (const f of deframer.push(Array.from(frame))) {
        const f1 = f.payload[0] | f.payload[1] << 8 | f.payload[2] << 16, f2 = f.payload[4] | f.payload[5] << 8 | f.payload[6] << 16;
        const addr = f1 >> 8, len = f2 >> 8, space = (f2 >> 4) & 0xf, data = f.payload.slice(8);
        let out;
        if (f.cmd === 0x23) {
          const payload = [...f.payload.slice(0, 8), ...mem.slice(addr, addr + len)];
          const ck = (0xff - payload.reduce((a, b) => a + b, 0)) & 0xff;
          out = [0x00, 0x59, 0x23, payload.length & 0xff, payload.length >> 8, 0, ...payload, ck];
        } else {
          if (space === 0 && len) mem.set(data, addr);
          out = [0x00, 0x59, 0x00, 0x01, 0x00, 0x00, 0x00, 0xff];
        }
        // deliver in 2 chunks like MTU-limited notifications
        setTimeout(() => { cb?.(Uint8Array.from(out.slice(0, 9))); cb?.(Uint8Array.from(out.slice(9))); }, 1);
      }
      return true;
    } };
}
const bp = fakeBlePedal(LIVE);
const bdev = new P.TankGBle(bp);
const bbank = await bdev.readBank();
assert.deepEqual(bbank.toBytes(), LIVE);
const bt = bbank.copy(); bt.presets[35] = rec9d;
const bafter = await bdev.writePresets(bt, [35]);
assert.equal(hex(bafter.presets[35]), hex(rec9d));
assert.ok(bp.sent.some(f => hex(f) === "00 59 22 08 00 00 04 00 00 00 f0 00 00 00 0b"), "commit sent");
bdev.selectPreset(35);
assert.equal(hex(bp.sent.at(-1)), "00 59 22 09 00 00 04 23 00 00 e0 01 00 00 01 f6");
console.log("bluetooth framing ok");
