// Run by tests/test_ui.py: argv[2] is a JSON file written by Python with expected outputs of
// tankg/ai.py and tankg/library.py. Prints the JS-written files so Python can load them back.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { applyDesign, fromText, webPrompt, zoneGap } from "../../android/ui/js/ai.js";
import { FIELDS } from "../../android/ui/js/data.js";
import { parsePresetFile, parseSetFile, presetFile, setFile } from "../../android/ui/js/files.js";
import { Bank, fromHex, toHex } from "../../android/ui/js/protocol.js";

const g = JSON.parse(readFileSync(process.argv[2], "utf8"));
for (const c of g.designs) assert.equal(toHex(applyDesign(c.design, c.like ? fromHex(c.like) : null)), c.expect, JSON.stringify(c.design));
for (const c of g.prompts) assert.equal(webPrompt(c.desc, c.instrument, c.bank), c.expect);
const one = fromText("Aquí va:\n```json\n" + JSON.stringify({ ...g.designs[0].design, name: "X", explanation: "Y" }) + "\n```", false, [null]);
assert.equal(toHex(one.bytes), g.designs[0].expectBlank);
const p = parsePresetFile(g.presetPy);
assert.equal(toHex(p.record), g.presetRaw); assert.equal(p.name, g.presetName);
const set = parseSetFile(g.setPy);
assert.equal(set.title, g.setTitle); assert.deepEqual(set.items.map(i => toHex(i.record)), g.setRaws);
for (const f of FIELDS)
  assert.deepEqual([...Array(f.max + 1).keys()].filter(v => zoneGap(f, v)), g.gaps[f.key], f.key);
const bank = Bank.fromBytes(fromHex(g.bank));
console.log(JSON.stringify({ preset: presetFile(fromHex(g.presetRaw), 5, g.presetName),
  set: setFile(bank, [4, 5, 6, 7], ["Uno", "", "Tres", "Cuatro"], "Mi banco") }));
