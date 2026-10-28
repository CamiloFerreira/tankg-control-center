// Run by tests/test_ui.py: cloud.js against a fake Google behind the APK bridge; argv[2] is a
// document written by tankg/cloud.py, which the APK must read.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const files = new Map(), folders = new Map();
let nextId = 1, polls = 0;
globalThis.AndroidMidi = {
  httpRequest(id, method, url, headersJson, body) {
    const headers = JSON.parse(headersJson);
    let status = 200, text = "{}";
    if (url.endsWith("/device/code")) text = JSON.stringify({ device_code: "d", user_code: "ABCD-EFGH", verification_url: "https://www.google.com/device", interval: 0, expires_in: 60 });
    else if (url.endsWith("/token") && body.includes("device_code") && ++polls === 1) status = 0;   // no network in the background
    else if (url.endsWith("/token")) text = body.includes("device_code") ? '{"access_token":"a","refresh_token":"r","expires_in":3600}' : '{"access_token":"a2","expires_in":3600}';
    else {
      assert.ok(headers.Authorization.startsWith("Bearer "));
      const fid = url.split("/").pop().split("?")[0];
      if (method === "GET" && url.includes("/files?")) {
        const q = new URL(url).searchParams.get("q");
        const found = q.includes("vnd.google-apps.folder") ? [...folders].filter(([, n]) => q.includes(`name = '${n}'`)).map(([i, n]) => ({ id: i, name: n }))
          : [...files].filter(([, f]) => q.includes(`'${f.parent}' in parents`)).map(([i, f]) => ({ id: i, name: f.name }));
        text = JSON.stringify({ files: found.map(f => ({ ...f, modifiedTime: "2026-10-27T12:00:00Z" })) });
      }
      else if (method === "GET") text = files.get(fid).body;
      else if (method === "POST" && headers["X-HTTP-Method-Override"] === "PATCH") files.get(fid).body = body;
      else if (method === "POST" && url.startsWith("https://www.googleapis.com/drive/v3/files?")) {
        const meta = JSON.parse(body);
        assert.equal(meta.mimeType, "application/vnd.google-apps.folder");
        const id2 = `d${nextId++}`;
        folders.set(id2, meta.name); text = JSON.stringify({ id: id2 });
      } else if (method === "POST") {
        const [, meta, payload] = body.split("\r\n\r\n");
        const m = JSON.parse(meta.split("\r\n--")[0]);
        assert.ok(folders.has(m.parents[0]));
        files.set(`f${nextId++}`, { name: m.name, parent: m.parents[0], body: payload.split("\r\n--")[0] });
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
assert.equal(fromPy.banks["1"], "Rock"); assert.deepEqual(fromPy.amps, { 3: "RANDALL Clean" });   // AMP names travel too
assert.equal("amps" in cloud.makeDoc(fromPy.bank, {}, {}, {}).aliases, false);   // like make_doc: only when there is one
assert.deepEqual(cloud.parseDoc(cloud.makeDoc(fromPy.bank, {}, {}, { 1: "X" })).amps, { 1: "X" });

const code = { deviceCode: "d", userCode: "ABCD-EFGH", url: "https://www.google.com/device", interval: 0, expiresIn: 60 };
assert.equal(await cloud.finishSignIn(code), "r");   // the network error while waiting is retried
assert.equal(polls, 2);
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
assert.deepEqual([...folders.values()], ["Tank-G Control Center"]);
assert.equal((await cloud.history(new cloud.Drive("r"))).length, 2);   // a new session finds the existing folder
assert.equal(folders.size, 1);
assert.equal(await cloud.docKey(pyDoc), await cloud.docKey(JSON.parse(JSON.stringify(pyDoc))));
console.log("cloud ok");
