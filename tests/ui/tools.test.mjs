// Run by tests/test_ui.py: argv[2] is a JSON file written by Python with inputs and the outputs of
// tankg/tuner.py, tankg/diag.py and tankg/demo.py; the APK must give the same results.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as tuner from "../../android/ui/js/tuner.js";
import * as diag from "../../android/ui/js/diag.js";
import * as tempo from "../../android/ui/js/tempo.js";
import { DEMO_BANKS, LIBRARY } from "../../android/ui/js/data.js";

const g = JSON.parse(readFileSync(process.argv[2], "utf8"));

// tuner: same frequency (to a hundredth of a cent), note and nearest string for every block
for (const c of g.tuner) {
  const f = tuner.detect(c.samples, c.rate);   // doubles, like Python
  const what = `${c.label} @ ${c.rate}`;
  if (c.freq === null) { assert.equal(f, null, what); continue; }
  assert.ok(f !== null, what);
  assert.ok(Math.abs(1200 * Math.log2(f / c.freq)) < 0.01, `${what}: ${f} vs ${c.freq}`);
  const n = tuner.note(f, c.a4);
  assert.equal(`${n.name}${n.octave}`, c.note, what);
  assert.ok(Math.abs(n.cents - c.cents) < 0.01, what);
  assert.equal(tuner.state(n.cents), c.state, what);
  for (const [t, r] of c.readings.entries()) {
    const got = tuner.reading(f, t, c.a4);
    assert.ok(Math.abs(got.cents - r.cents) < 0.01, `${what} afinación ${t}`);
    assert.deepEqual({ ...got, cents: 0 }, { ...r, cents: 0 }, `${what} afinación ${t}`);
  }
  assert.ok(Math.abs(tuner.level(c.samples) - c.level) < 1e-9, what);
}

// diagnostics: same masking, same report and same issue link
for (const c of g.scrub) assert.equal(diag.oneLine(diag.scrub(c.in)), c.out);
for (const c of g.reports) {
  assert.equal(diag.report(c.info), c.text);
  assert.equal(diag.issueUrl(c.text), c.url);
}
diag.error("Traceback (most recent call last):\n  File x\nDeviceError: sin respuesta de juan@example.com");
assert.match(diag.errors()[0], /^\d\d:\d\d:\d\d DeviceError: sin respuesta de <correo>$/);
assert.match(diag.lines().at(-1), / Error: DeviceError/);

// tempo: same tap tempo, marking and delay times
for (const c of g.tempo.taps) assert.equal(tempo.tap(c.times), c.bpm, JSON.stringify(c.times));
for (const c of g.tempo.bpms) {
  assert.equal(tempo.marking(c.bpm), c.marking);
  assert.deepEqual(tempo.delayTimes(c.bpm), c.delays);
  assert.equal(tempo.clamp(c.bpm + 0.4), c.clamped);
}

// demo pedal: the same banks and presets
assert.deepEqual(DEMO_BANKS, g.demo.banks);
const hex = DEMO_BANKS.flatMap((name, b) => (LIBRARY.find(x => x.name === name) || LIBRARY[b]).presets.map(p => p.hex));
assert.deepEqual(hex, g.demo.presets);
console.log("ok");
