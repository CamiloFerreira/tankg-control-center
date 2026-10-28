// Run by tests/test_ui.py: argv[2] is a JSON file written by Python with expected outputs of
// tankg/ai.py and tankg/library.py. Prints the JS-written files so Python can load them back.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { applyDesign, fromText, webPrompt, zoneGap } from "../../android/ui/js/ai.js";
import { FIELDS } from "../../android/ui/js/data.js";
import { SIG, TANH } from "../../android/ui/js/am4.js";
import { packFile, parsePackFile, parsePresetFile, parseSetFile, presetFile, remapPack, setFile } from "../../android/ui/js/files.js";
import { Bank, fromHex, toHex } from "../../android/ui/js/protocol.js";

const g = JSON.parse(readFileSync(process.argv[2], "utf8"));
for (const c of g.designs) assert.equal(toHex(applyDesign(c.design, c.like ? fromHex(c.like) : null)), c.expect, JSON.stringify(c.design));
for (const c of g.prompts) assert.equal(webPrompt(c.desc, c.instrument, c.bank, c.amps || {}), c.expect);
const one = fromText("Aquí va:\n```json\n" + JSON.stringify({ ...g.designs[0].design, name: "X", explanation: "Y" }) + "\n```", false, [null]);
assert.equal(toHex(one.bytes), g.designs[0].expectBlank);
const p = parsePresetFile(g.presetPy);
assert.equal(toHex(p.record), g.presetRaw); assert.equal(p.name, g.presetName);
const set = parseSetFile(g.setPy);
assert.equal(set.title, g.setTitle); assert.deepEqual(set.items.map(i => toHex(i.record)), g.setRaws);
for (const f of FIELDS)
  assert.deepEqual([...Array(f.max + 1).keys()].filter(v => zoneGap(f, v)), g.gaps[f.key], f.key);
assert.deepEqual(SIG, g.am4Tables.sig, "sigmoid table");
assert.deepEqual(TANH, g.am4Tables.tanh, "tanh table");
const bank = Bank.fromBytes(fromHex(g.bank));
// packs: the one written by Python reads here (with its AMP model); this one is read back by Python
const pk = parsePackFile(g.packPy);
assert.equal(pk.kind, "bank"); assert.equal(pk.title, "Pack"); assert.deepEqual(pk.banks, { 2: "Banco" });
assert.deepEqual(pk.presets.map(p => [p.slot, p.name]), [[4, "Uno ñ"], [5, null], [6, null], [7, null]]);
assert.equal(pk.amps.length, 1); assert.equal(pk.amps[0].slot, g.packAmp); assert.equal(pk.amps[0].data.length, 7868);
assert.equal(remapPack([pk.presets[0].record], { [g.packAmp]: 8 })[0][5], 8);
const jsPack = packFile(bank, [4, 5, 6, 7], { 4: "Uno ñ" }, { 2: "Banco" }, { [g.packAmp + 1]: "Mi AMP" }, { [g.packAmp]: pk.amps[0].data }, "Pack");
assert.deepEqual(jsPack.missing, []);
console.log(JSON.stringify({ preset: presetFile(fromHex(g.presetRaw), 5, g.presetName),
  set: setFile(bank, [4, 5, 6, 7], ["Uno", "", "Tres", "Cuatro"], "Mi banco"), pack: jsPack.text }));
