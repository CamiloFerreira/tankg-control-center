// Run by tests/test_web.py with node: the JS protocol must produce the frames captured from
// the real pedal (same goldens as tests/test_tankg.py) and behave like the Python TankG.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as P from "../../web/js/protocol.js";
import { LIBRARY, FIELDS } from "../../web/js/data.js";

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
