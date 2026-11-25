/*
 * qr.js — minimal offline QR Code encoder (byte mode, error correction level M, versions 1–10)
 * No external library / no CDN. Enough for PromptPay payloads (~84–90 bytes → version 5–6).
 * Algorithm follows ISO/IEC 18004: Reed-Solomon over GF(256) (poly 0x11D), BCH format/version
 * info, zig-zag placement, 8 masks scored with the 4 standard penalty rules.
 *
 * Browser: window.LcaQR.encodeText(text) / window.LcaQR.toSvg(qr, {scale, border})
 * Node (tests): module.exports
 */
(function (root) {
  "use strict";

  var ECC_PER_BLOCK = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];  // level M, index = version
  var NUM_BLOCKS = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5];
  var MAX_VERSION = 10;

  function rawModules(ver) {
    var r = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
      var na = Math.floor(ver / 7) + 2;
      r -= (25 * na - 10) * na - 55;
      if (ver >= 7) r -= 36;
    }
    return r;
  }

  function dataCodewords(ver) {
    return Math.floor(rawModules(ver) / 8) - ECC_PER_BLOCK[ver] * NUM_BLOCKS[ver];
  }

  function countBits(ver) { return ver < 10 ? 8 : 16; }

  function byteCapacity(ver) {
    return Math.floor((dataCodewords(ver) * 8 - 4 - countBits(ver)) / 8);
  }

  // ---------- Reed-Solomon ----------
  function gfMul(x, y) {
    var z = 0;
    for (var i = 7; i >= 0; i--) {
      z = (z << 1) ^ ((z >>> 7) * 0x11D);
      z ^= ((y >>> i) & 1) * x;
    }
    return z & 0xFF;
  }

  function rsDivisor(degree) {
    var result = [];
    for (var i = 0; i < degree - 1; i++) result.push(0);
    result.push(1);
    var r = 1;
    for (var k = 0; k < degree; k++) {
      for (var j = 0; j < result.length; j++) {
        result[j] = gfMul(result[j], r);
        if (j + 1 < result.length) result[j] ^= result[j + 1];
      }
      r = gfMul(r, 0x02);
    }
    return result;
  }

  function rsRemainder(data, divisor) {
    var result = divisor.map(function () { return 0; });
    data.forEach(function (b) {
      var factor = b ^ result.shift();
      result.push(0);
      for (var i = 0; i < divisor.length; i++) result[i] ^= gfMul(divisor[i], factor);
    });
    return result;
  }

  function rsEncode(data, degree) { return rsRemainder(data, rsDivisor(degree)); }

  // ---------- BCH info bits ----------
  function formatBits(mask) {
    var data = (0 << 3) | mask;  // level M = 00
    var rem = data;
    for (var i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    return ((data << 10) | rem) ^ 0x5412;
  }

  function versionBits(ver) {
    var rem = ver;
    for (var i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
    return (ver << 12) | rem;
  }

  // ---------- data codewords ----------
  function utf8(text) {
    var out = [];
    for (var i = 0; i < text.length; i++) {
      var c = text.codePointAt(i);
      if (c > 0xFFFF) i++;
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xC0 | (c >> 6), 0x80 | (c & 63));
      else if (c < 0x10000) out.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      else out.push(0xF0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }

  function buildCodewords(bytes, ver) {
    var bits = [];
    function put(val, len) { for (var i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1); }
    put(4, 4);
    put(bytes.length, countBits(ver));
    bytes.forEach(function (b) { put(b, 8); });
    var cap = dataCodewords(ver) * 8;
    put(0, Math.min(4, cap - bits.length));
    put(0, (8 - bits.length % 8) % 8);
    for (var pad = 0xEC; bits.length < cap; pad ^= 0xEC ^ 0x11) put(pad, 8);
    var data = [];
    for (var i = 0; i < bits.length; i += 8) {
      var v = 0;
      for (var j = 0; j < 8; j++) v = (v << 1) | bits[i + j];
      data.push(v);
    }
    // split into blocks, add ECC, interleave
    var nb = NUM_BLOCKS[ver], ecLen = ECC_PER_BLOCK[ver];
    var raw = Math.floor(rawModules(ver) / 8);
    var shortLen = Math.floor(raw / nb), nShort = nb - raw % nb;
    var blocks = [], eccs = [], k = 0;
    for (var bi = 0; bi < nb; bi++) {
      var len = shortLen - ecLen + (bi < nShort ? 0 : 1);
      var blk = data.slice(k, k + len);
      k += len;
      blocks.push(blk);
      eccs.push(rsEncode(blk, ecLen));
    }
    var out = [];
    for (var i2 = 0; i2 <= shortLen - ecLen; i2++) {
      blocks.forEach(function (b) { if (i2 < b.length) out.push(b[i2]); });
    }
    for (var e = 0; e < ecLen; e++) eccs.forEach(function (c) { out.push(c[e]); });
    return out;
  }

  // ---------- matrix ----------
  function Matrix(ver) {
    this.size = ver * 4 + 17;
    this.m = [];
    this.f = [];
    for (var y = 0; y < this.size; y++) {
      this.m.push(new Array(this.size).fill(false));
      this.f.push(new Array(this.size).fill(false));
    }
  }
  Matrix.prototype.set = function (x, y, dark) { this.m[y][x] = !!dark; this.f[y][x] = true; };

  function alignmentPositions(ver) {
    if (ver === 1) return [];
    var n = Math.floor(ver / 7) + 2, size = ver * 4 + 17;
    var step = Math.ceil((ver * 4 + 4) / (n * 2 - 2)) * 2;
    var result = [6];
    for (var pos = size - 7; result.length < n; pos -= step) result.splice(1, 0, pos);
    return result;
  }

  function drawFunctionPatterns(mx, ver) {
    var s = mx.size, i;
    for (i = 0; i < s; i++) { mx.set(6, i, i % 2 === 0); mx.set(i, 6, i % 2 === 0); }
    [[3, 3], [s - 4, 3], [3, s - 4]].forEach(function (c) {
      for (var dy = -4; dy <= 4; dy++) {
        for (var dx = -4; dx <= 4; dx++) {
          var x = c[0] + dx, y = c[1] + dy;
          if (x < 0 || y < 0 || x >= s || y >= s) continue;
          var d = Math.max(Math.abs(dx), Math.abs(dy));
          mx.set(x, y, d !== 2 && d !== 4);
        }
      }
    });
    var ap = alignmentPositions(ver), last = ap.length - 1;
    for (var a = 0; a < ap.length; a++) {
      for (var b = 0; b < ap.length; b++) {
        if ((a === 0 && b === 0) || (a === 0 && b === last) || (a === last && b === 0)) continue;
        for (var dy2 = -2; dy2 <= 2; dy2++) {
          for (var dx2 = -2; dx2 <= 2; dx2++) {
            mx.set(ap[a] + dx2, ap[b] + dy2, Math.max(Math.abs(dx2), Math.abs(dy2)) !== 1);
          }
        }
      }
    }
    drawFormat(mx, 0);
    if (ver >= 7) {
      var vb = versionBits(ver);
      for (i = 0; i < 18; i++) {
        var bit = (vb >>> i) & 1, p = s - 11 + i % 3, q = Math.floor(i / 3);
        mx.set(p, q, bit);
        mx.set(q, p, bit);
      }
    }
  }

  function drawFormat(mx, mask) {
    var bits = formatBits(mask), s = mx.size, i;
    function bit(n) { return (bits >>> n) & 1; }
    for (i = 0; i <= 5; i++) mx.set(8, i, bit(i));
    mx.set(8, 7, bit(6));
    mx.set(8, 8, bit(7));
    mx.set(7, 8, bit(8));
    for (i = 9; i < 15; i++) mx.set(14 - i, 8, bit(i));
    for (i = 0; i < 8; i++) mx.set(s - 1 - i, 8, bit(i));
    for (i = 8; i < 15; i++) mx.set(8, s - 15 + i, bit(i));
    mx.set(8, s - 8, true);
  }

  function drawCodewords(mx, data) {
    var s = mx.size, i = 0;
    for (var right = s - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (var vert = 0; vert < s; vert++) {
        for (var j = 0; j < 2; j++) {
          var x = right - j, upward = ((right + 1) & 2) === 0;
          var y = upward ? s - 1 - vert : vert;
          if (!mx.f[y][x] && i < data.length * 8) {
            mx.m[y][x] = ((data[i >>> 3] >>> (7 - (i & 7))) & 1) === 1;
            i++;
          }
        }
      }
    }
  }

  var MASKS = [
    function (x, y) { return (x + y) % 2 === 0; },
    function (x, y) { return y % 2 === 0; },
    function (x) { return x % 3 === 0; },
    function (x, y) { return (x + y) % 3 === 0; },
    function (x, y) { return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; },
    function (x, y) { return (x * y) % 2 + (x * y) % 3 === 0; },
    function (x, y) { return ((x * y) % 2 + (x * y) % 3) % 2 === 0; },
    function (x, y) { return ((x + y) % 2 + (x * y) % 3) % 2 === 0; }
  ];

  function applyMask(mx, mask) {
    for (var y = 0; y < mx.size; y++) {
      for (var x = 0; x < mx.size; x++) {
        if (!mx.f[y][x] && MASKS[mask](x, y)) mx.m[y][x] = !mx.m[y][x];
      }
    }
  }

  function penalty(mx) {
    var s = mx.size, m = mx.m, score = 0, dark = 0, x, y;
    function lineScore(get) {
      var sc = 0, run = 1, str = "";
      for (var i = 0; i < s; i++) {
        var v = get(i);
        str += v ? "1" : "0";
        if (i > 0 && v === get(i - 1)) { run++; } else { if (run >= 5) sc += run - 2; run = 1; }
      }
      if (run >= 5) sc += run - 2;
      var padded = "0000" + str + "0000", idx = -1;
      while ((idx = padded.indexOf("00001011101", idx + 1)) !== -1) sc += 40;
      idx = -1;
      while ((idx = padded.indexOf("10111010000", idx + 1)) !== -1) sc += 40;
      return sc;
    }
    for (y = 0; y < s; y++) score += lineScore(function (i) { return m[y][i]; });
    for (x = 0; x < s; x++) score += lineScore(function (i) { return m[i][x]; });
    for (y = 0; y < s - 1; y++) {
      for (x = 0; x < s - 1; x++) {
        var c = m[y][x];
        if (c === m[y][x + 1] && c === m[y + 1][x] && c === m[y + 1][x + 1]) score += 3;
      }
    }
    for (y = 0; y < s; y++) for (x = 0; x < s; x++) if (m[y][x]) dark++;
    var total = s * s;
    score += (Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1) * 10;
    return score;
  }

  function encodeText(text) {
    var bytes = utf8(String(text));
    var ver = 1;
    while (ver <= MAX_VERSION && bytes.length > byteCapacity(ver)) ver++;
    if (ver > MAX_VERSION) throw new Error("ข้อความยาวเกินกว่าที่ QR (version " + MAX_VERSION + ") รองรับ");
    var data = buildCodewords(bytes, ver);
    var mx = new Matrix(ver);
    drawFunctionPatterns(mx, ver);
    drawCodewords(mx, data);
    var best = -1, bestScore = Infinity;
    for (var mask = 0; mask < 8; mask++) {
      applyMask(mx, mask);
      drawFormat(mx, mask);
      var sc = penalty(mx);
      if (sc < bestScore) { best = mask; bestScore = sc; }
      applyMask(mx, mask);  // XOR again = undo
    }
    applyMask(mx, best);
    drawFormat(mx, best);
    return { version: ver, size: mx.size, mask: best, modules: mx.m };
  }

  function toSvg(qr, opts) {
    opts = opts || {};
    var border = opts.border == null ? 4 : opts.border;
    var n = qr.size + border * 2, path = [];
    for (var y = 0; y < qr.size; y++) {
      for (var x = 0; x < qr.size; x++) {
        if (qr.modules[y][x]) path.push("M" + (x + border) + "," + (y + border) + "h1v1h-1z");
      }
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + n + " " + n +
      '" shape-rendering="crispEdges" role="img" aria-label="QR code">' +
      '<rect width="100%" height="100%" fill="#fff"/><path d="' + path.join("") + '" fill="#000"/></svg>';
  }

  var api = {
    encodeText: encodeText, toSvg: toSvg,
    _rsEncode: rsEncode, _formatBits: formatBits, _versionBits: versionBits,
    _byteCapacity: byteCapacity
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LcaQR = api;
})(this);
