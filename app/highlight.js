/* LCA code highlighter — offline, no CDN, no dependencies.
 * highlight(code, lang) returns an HTML string where every piece of the
 * source is HTML-escaped first and only wrapped in <span class="hl-*">.
 * Unknown languages return the escaped code with no spans. */
(function (root) {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function words(list) {
    return "\\b(?:" + list.split(" ").join("|") + ")\\b";
  }

  const NUM = "\\b(?:0[xX][0-9a-fA-F]+|\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?)\\b";
  const DQ = '"(?:[^"\\\\\\n]|\\\\.)*"';
  const SQ = "'(?:[^'\\\\\\n]|\\\\.)*'";

  const PY_KW = "False None True and as assert async await break class continue def del elif else except " +
    "finally for from global if import in is lambda nonlocal not or pass raise return try while with yield self print";
  const JS_KW = "break case catch class const continue debugger default delete do else export extends finally for " +
    "function if import in instanceof let new of return super switch this throw try typeof var void while with yield " +
    "async await true false null undefined interface type enum implements private public protected readonly as from";
  const SH_KW = "if then else elif fi for while until do done case esac in function return local export echo " +
    "exit set unset source cd sudo";

  // Each rule: [css class, regex source]. Order matters: comments and strings first.
  // Rule sources must not contain capturing groups (use (?:...)); group index maps to class.
  const RULES = {
    python: [
      ["com", "#[^\\n]*"],
      ["str", '"""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'|[rbfRBF]{0,2}(?:' + DQ + "|" + SQ + ")"],
      ["kw", words(PY_KW)],
      ["num", NUM],
    ],
    javascript: [
      ["com", "//[^\\n]*|/\\*[\\s\\S]*?\\*/"],
      ["str", DQ + "|" + SQ + "|`(?:[^`\\\\]|\\\\.)*`"],
      ["kw", words(JS_KW)],
      ["num", NUM],
    ],
    json: [
      ["str", DQ],
      ["kw", words("true false null")],
      ["num", "-?" + NUM],
    ],
    bash: [
      ["com", "(?:^|(?<=\\s))#[^\\n]*"],
      ["str", DQ + "|'[^']*'"],
      ["kw", words(SH_KW)],
      ["num", NUM],
    ],
    html: [
      ["com", "<!--[\\s\\S]*?-->"],
      ["str", DQ + "|" + SQ],
      ["kw", "</?[A-Za-z][\\w-]*|/?>"],
    ],
    css: [
      ["com", "/\\*[\\s\\S]*?\\*/"],
      ["str", DQ + "|" + SQ],
      // Lookbehind anchors: a repeatable run may only start at its first char (no ReDoS).
      ["kw", "@[\\w-]+|![\\w]+|(?<![\\w-])[a-z][a-z-]*(?=\\s*:)"],
      ["num", "#[0-9a-fA-F]{3,8}\\b|(?<![\\w.#-])-?\\d+(?:\\.\\d+)?(?:px|em|rem|%|vh|vw|s|ms|deg)?\\b"],
    ],
  };

  const ALIASES = {
    py: "python", python: "python", python3: "python",
    js: "javascript", javascript: "javascript", jsx: "javascript", mjs: "javascript",
    ts: "javascript", typescript: "javascript", tsx: "javascript", node: "javascript",
    json: "json", jsonc: "json",
    sh: "bash", bash: "bash", shell: "bash", zsh: "bash", console: "bash",
    html: "html", htm: "html", xml: "html", svg: "html",
    css: "css",
  };

  const COMPILED = {};
  function compile(lang) {
    if (COMPILED[lang]) return COMPILED[lang];
    const rules = RULES[lang];
    const re = new RegExp(rules.map((r) => "(" + r[1] + ")").join("|"), "gm");
    COMPILED[lang] = { re, classes: rules.map((r) => r[0]) };
    return COMPILED[lang];
  }

  function normalizeLang(lang) {
    const key = String(lang || "").trim().split(/\s+/)[0].toLowerCase();
    return ALIASES[key] || null;
  }

  // Above this size we skip highlighting: guards against any super-linear regex path.
  const MAX_LENGTH = 100000;

  function highlight(code, lang) {
    const text = String(code == null ? "" : code);
    const name = normalizeLang(lang);
    if (!name || text.length > MAX_LENGTH) return esc(text);
    const { re, classes } = compile(name);
    re.lastIndex = 0;
    let out = "";
    let last = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m[0] === "") { re.lastIndex++; continue; }
      const idx = m.slice(1).findIndex((g) => g !== undefined);
      out += esc(text.slice(last, m.index));
      out += '<span class="hl-' + classes[idx] + '">' + esc(m[0]) + "</span>";
      last = m.index + m[0].length;
    }
    return out + esc(text.slice(last));
  }

  const api = { highlight, normalizeLang, escapeHtml: esc, MAX_LENGTH };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LCAHighlight = api;
})(typeof window !== "undefined" ? window : this);
