// Run by tests/test_ui.py: cloud.js against a fake Google behind the APK bridge; argv[2] is a
// document written by tankg/cloud.py, which the APK must read.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const files = new Map();
let nextId = 1;
globalThis.AndroidMidi = {
  httpRequest(id, method, url, headersJson, body) {
    const headers = JSON.parse(headersJson);
    let status = 200, text = "{}";
    if (url.endsWith("/device/code")) text = JSON.stringify({ device_code: "d", user_code: "ABCD-EFGH", verification_url: "https://www.google.com/device", interval: 0, expires_in: 60 });
    else if (url.endsWith("/token")) text = body.includes("device_code") ? '{"access_token":"a","refresh_token":"r","expires_in":3600}' : '{"access_token":"a2","expires_in":3600}';
    else {
      assert.ok(headers.Authorization.startsWith("Bearer "));
      const fid = url.split("/").pop().split("?")[0];
      if (method === "GET" && url.includes("/files?")) text = JSON.stringify({ files: [...files].map(([i, f]) => ({ id: i, name: f.name, modifiedTime: "2026-10-27T12:00:00Z" })) });
      else if (method === "GET") text = files.get(fid).body;
      else if (method === "POST" && headers["X-HTTP-Method-Override"] === "PATCH") files.get(fid).body = body;
      else if (method === "POST") {
        const [, meta, payload] = body.split("\r\n\r\n");
        const id2 = `f${nextId++}`;
        files.set(id2, { name: JSON.parse(meta.split("\r\n--")[0]).name, body: payload.split("\r\n--")[0] });
      } else if (method === "DELETE") files.delete(fid);
    }
    setTimeout(() => globalThis.__httpDone(id, status, text), 0);
  },
};
const cloud = await import("../../android/ui/js/cloud.js");
const { Bank, fromHex } = await import("../../android/ui/js/protocol.js");

const pyDoc = JSON.parse(readFileSync(process.argv[2], "utf8"));
const fromPy = cloud.parseDoc(pyDoc);
assert.equal(fromPy.presets["1A"], "Limpio ñ"); assert.equal(fromPy.bank.toBytes().length, 758);

const drive = new cloud.Drive("r");
const bank = Bank.fromBytes(fromHex(pyDoc.bank));
await cloud.push(drive, cloud.makeDoc(bank, { "1A": "Desde Android" }, { 1: "Rock" }));
assert.equal(files.size, 1);
await cloud.push(drive, cloud.makeDoc(bank, { "1A": "Desde Android" }, { 1: "Rock" }));   // unchanged: no new version
assert.equal(files.size, 1);
const b2 = bank.copy(); b2.presets[0][6] = 99;
await cloud.push(drive, cloud.makeDoc(b2, { "1A": "Otra" }, {}));
assert.equal(files.size, 2);
const latest = cloud.parseDoc(await cloud.pull(drive));
assert.equal(latest.bank.presets[0][6], 99); assert.equal(latest.presets["1A"], "Otra");
const hist = await cloud.history(drive);
assert.equal(hist[0].name, cloud.LATEST); assert.equal(hist.length, 2);
assert.equal(await cloud.docKey(pyDoc), await cloud.docKey(JSON.parse(JSON.stringify(pyDoc))));
console.log("cloud ok");
