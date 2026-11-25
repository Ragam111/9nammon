// Node test for app/highlight.js: run with `node --test tests/highlight.test.mjs`.
// Loads the browser script in a vm sandbox (same as a classic <script> tag).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(here, "..", "app", "highlight.js"), "utf8");
const sandbox = { window: {} };
vm.runInNewContext(src, sandbox);
const HL = sandbox.window.LCAHighlight;

// Strip our own spans; what remains must be the escaped source text.
const strip = (html) => html.replace(/<span class="hl-[a-z]+">|<\/span>/g, "");
const unescape = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");

test("exposes highlight on window", () => {
  assert.equal(typeof HL.highlight, "function");
});

test("escapes HTML for unknown language and adds no spans", () => {
  const out = HL.highlight('<b>"x" & \'y\'</b>', "brainfuck");
  assert.equal(out, "&lt;b&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/b&gt;");
  assert.equal(HL.highlight("a<b", ""), "a&lt;b");
});

test("python sample gets keyword, string, comment, number spans", () => {
  const code = 'def add(a, b):\n    # sum two\n    return a + b * 2  # "c"\nprint("hi <x>")\n';
  const out = HL.highlight(code, "python");
  assert.match(out, /<span class="hl-kw">def<\/span>/);
  assert.match(out, /<span class="hl-kw">return<\/span>/);
  assert.match(out, /<span class="hl-com"># sum two<\/span>/);
  assert.match(out, /<span class="hl-num">2<\/span>/);
  assert.match(out, /<span class="hl-str">&quot;hi &lt;x&gt;&quot;<\/span>/);
  assert.equal(unescape(strip(out)), code);
});

test("XSS sample stays text in every language", () => {
  const evil = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
  for (const lang of ["python", "js", "ts", "json", "bash", "html", "css", "nope"]) {
    const out = HL.highlight(evil, lang);
    assert.ok(!out.includes("<img"), lang + ": raw <img leaked");
    assert.ok(!out.includes("<script"), lang + ": raw <script leaked");
    assert.equal(strip(out).replace(/<[^>]*>/g, ""), strip(out), lang + ": only hl spans allowed");
    assert.equal(unescape(strip(out)), evil, lang + ": text must round-trip");
  }
});

test("javascript, json, bash, css samples", () => {
  assert.match(HL.highlight("const x = `t`; // c", "javascript"), /hl-kw">const<.*hl-str">`t`<.*hl-com">\/\/ c</);
  assert.match(HL.highlight('{"a": true, "n": -1.5}', "json"), /hl-str">&quot;a&quot;<.*hl-kw">true<.*hl-num">-1.5</);
  assert.match(HL.highlight("echo 'hi' # note", "sh"), /hl-kw">echo<.*hl-str">&#39;hi&#39;<.*hl-com"># note</);
  assert.match(HL.highlight("a { color: #fff; }", "css"), /hl-kw">color<.*hl-num">#fff</);
  assert.equal(HL.normalizeLang("typescript app.ts"), "javascript");
  assert.equal(HL.normalizeLang("rust"), null);
});

test("css rules are linear on pathological input (no ReDoS)", () => {
  for (const code of ["1".repeat(200000) + "x", "a-".repeat(100000), "1".repeat(99000) + "x", "a-".repeat(49000)]) {
    const t0 = Date.now();
    HL.highlight(code, "css");
    const ms = Date.now() - t0;
    assert.ok(ms < 500, code.length + " chars took " + ms + "ms");
  }
});

test("css still highlights numbers, units and properties", () => {
  const out = HL.highlight("p { margin: -1.5px 10%; z-index: 2; }", "css");
  assert.match(out, /hl-kw">margin<.*hl-num">-1.5px<.*hl-num">10<.*hl-kw">z-index<.*hl-num">2</);
});

test("code over MAX_LENGTH is escaped only, no spans", () => {
  const big = '"""<b>' + "x".repeat(HL.MAX_LENGTH);
  const t0 = Date.now();
  const out = HL.highlight(big, "python");
  assert.ok(Date.now() - t0 < 500);
  assert.ok(!out.includes("<span"));
  assert.ok(out.startsWith("&quot;&quot;&quot;&lt;b&gt;"));
});

test("unterminated delimited tokens are linear (no O(n^2))", () => {
  const cases = [
    ['"a\\', ["python", "javascript", "json", "bash", "css"]],
    ["'a\\", ["python", "javascript"]],
    ["`a\\", ["javascript"]],
    ["/*a", ["javascript", "css"]],
    ["<!--a", ["html"]],
    ['"""a', ["python"]],
    ["'''a", ["python"]],
  ];
  for (const [unit, langs] of cases) {
    const code = unit.repeat(Math.floor(99000 / unit.length));
    for (const lang of langs) {
      const t0 = Date.now();
      const out = HL.highlight(code, lang);
      const ms = Date.now() - t0;
      assert.ok(ms < 500, lang + " " + JSON.stringify(unit) + " took " + ms + "ms");
      assert.equal(unescape(strip(out)), code, lang + ": text must round-trip");
      assert.ok(!/<(?!span class="hl-|\/span>)/.test(out), lang + ": only hl spans allowed");
    }
  }
});

test("unterminated strings and comments stop at end of line or input", () => {
  assert.match(HL.highlight('x = "open\ny = 1', "python"), /hl-str">&quot;open<\/span>\ny = <span class="hl-num">1</);
  assert.match(HL.highlight("a = 'open\\\nb", "javascript"), /hl-str">&#39;open\\<\/span>\nb/);
  assert.match(HL.highlight("x /* open", "javascript"), /hl-com">\/\* open<\/span>$/);
  assert.match(HL.highlight("<p><!-- open", "html"), /hl-com">&lt;!-- open<\/span>$/);
  assert.match(HL.highlight('s = """doc\nmore', "python"), /hl-str">&quot;&quot;&quot;doc\nmore<\/span>$/);
  assert.match(HL.highlight("`a ${b}\nc", "javascript"), /hl-str">`a \$\{b\}\nc<\/span>$/);
  assert.match(HL.highlight('"a" "b', "json"), /hl-str">&quot;a&quot;<\/span> <span class="hl-str">&quot;b<\/span>$/);
});
