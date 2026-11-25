// Node check: a hostile key name/owner must end up as plain text, never as markup.
// Usage: node tests/js/console_keys_xss.js app/console-keys.js
"use strict";
const assert = require("assert");
const path = require("path");

const created = [];
function makeNode(tag) {
  const node = {
    tagName: String(tag).toUpperCase(), children: [], attrs: {}, className: "", _text: "",
    appendChild(c) { this.children.push(c); return c; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    addEventListener() {},
    get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); },
    set textContent(v) { this._text = String(v); this.children = []; },
  };
  for (const sink of ["innerHTML", "outerHTML"]) {
    Object.defineProperty(node, sink, {
      get() { throw new Error(sink + " read"); },
      set() { throw new Error(sink + " written"); },
    });
  }
  node.insertAdjacentHTML = () => { throw new Error("insertAdjacentHTML used"); };
  created.push(node);
  return node;
}
const doc = { createElement: makeNode };

const mod = require(path.resolve(process.argv[2]));
const evil = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
const row = mod.buildRow(doc, {
  key_id: "k1", prefix: "lca_f_<b>x</b>", name: evil, owner: '"><svg onload=1>',
  created_by: "<i>ops</i>", tier: "free", daily_limit: 100, used_today: 3,
  created_at: "2026-11-26T10:00:00", active: true,
}, () => {});

const allowed = new Set(["TR", "TD", "SPAN", "DIV", "BUTTON", "I"]);
for (const n of created) assert.ok(allowed.has(n.tagName), "unexpected element " + n.tagName);
const text = row.textContent;
assert.ok(text.includes(evil), "name must be shown verbatim as text");
assert.ok(text.includes('"><svg onload=1>'), "owner must be shown verbatim as text");
assert.ok(text.includes("สร้างโดย <i>ops</i>"), "created_by must be text");
for (const n of created) {
  for (const [k, v] of Object.entries(n.attrs)) {
    assert.ok(!/^on/i.test(k), "event attribute " + k);
    assert.ok(!v.includes("<"), "markup in attribute " + k);
  }
}
// filters
const keys = [{ active: true, tier: "free" }, { active: false, tier: "paid" }];
assert.strictEqual(mod.filterKeys(keys, "active", "all").length, 1);
assert.strictEqual(mod.filterKeys(keys, "revoked", "paid").length, 1);
assert.strictEqual(mod.filterKeys(keys, "all", "free").length, 1);
console.log("OK");
