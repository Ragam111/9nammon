"""
test_qr_js.py — offline QR encoder in app/qr.js (run through node, skipped if node is missing)

Checks against independent references:
  - Reed-Solomon: Thonky "HELLO WORLD" 1-M data codewords -> known 10 EC codewords
  - format info bits for level M, masks 0..7 (ISO/IEC 18004 table)
  - version info bits for version 7
  - byte-mode capacity per version (level M) and structural patterns of the matrix
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import promptpay  # noqa: E402

QR_JS = Path(__file__).resolve().parent.parent / "app" / "qr.js"
NODE = shutil.which("node")

RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const ctx = { module: { exports: {} } };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const QR = ctx.module.exports;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = {};
out.rs = QR._rsEncode(input.rsData, 10);
out.fmt = [0,1,2,3,4,5,6,7].map(m => QR._formatBits(m));
out.ver7 = QR._versionBits(7);
out.caps = [1,2,3,4,5,6,7,8,9,10].map(v => QR._byteCapacity(v));
const q = QR.encodeText(input.text);
out.size = q.size; out.version = q.version; out.mask = q.mask;
out.rows = q.modules.map(r => r.map(b => b ? 1 : 0).join(''));
const q8 = QR.encodeText(input.text8);
out.rows8 = q8.modules.map(r => r.map(b => b ? 1 : 0).join(''));
try { QR.encodeText('x'.repeat(400)); out.tooLong = false; } catch (e) { out.tooLong = true; }
process.stdout.write(JSON.stringify(out));
"""

HELLO_DATA = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
HELLO_EC = [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]
FORMAT_M = ["101010000010010", "101000100100101", "101111001111100", "101101101001011",
            "100010111111001", "100000011001110", "100111110010111", "100101010100000"]
VERSION7 = "000111110010010100"
# byte-mode capacity at level M, versions 1..10 (ISO/IEC 18004 table 7)
CAPS_M = [14, 26, 42, 62, 84, 106, 122, 152, 180, 213]
ECC_M = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
BLOCKS_M = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
TEXT8 = "LCA-ทดสอบ-" + "0123456789" * 12   # 140 bytes UTF-8 -> version 8, uneven blocks + version info


def _gf_mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
        b >>= 1
    return r


def _rs_remainder(data, degree):
    # generator = prod (x - 2^i), i < degree; long division, independent of qr.js
    gen, root = [1], 1
    for _ in range(degree):
        nxt = [0] * (len(gen) + 1)
        for i, c in enumerate(gen):
            nxt[i] ^= c
            nxt[i + 1] ^= _gf_mul(c, root)
        gen, root = nxt, _gf_mul(root, 2)
    buf = list(data) + [0] * degree
    for i in range(len(data)):
        f = buf[i]
        if f:
            for j, g in enumerate(gen):
                buf[i + j] ^= _gf_mul(g, f)
    return buf[len(data):]


def _function_map(ver):
    n = ver * 4 + 17
    fm = [[False] * n for _ in range(n)]

    def mark(x0, y0, w, h):
        for y in range(max(0, y0), min(n, y0 + h)):
            for x in range(max(0, x0), min(n, x0 + w)):
                fm[y][x] = True
    mark(0, 0, 9, 9); mark(n - 8, 0, 8, 9); mark(0, n - 8, 9, 8)    # finders + format
    mark(6, 0, 1, n); mark(0, 6, n, 1)                               # timing
    if ver >= 2:
        k = ver // 7 + 2
        step = -(-(ver * 4 + 4) // (k * 2 - 2)) * 2
        pos = [6] + sorted(n - 7 - i * step for i in range(k - 1))
        corners = {(6, 6), (6, pos[-1]), (pos[-1], 6)}  # overlap the finders
        for a in pos:
            for b in pos:
                if (a, b) not in corners:
                    mark(a - 2, b - 2, 5, 5)
    if ver >= 7:
        mark(n - 11, 0, 3, 6); mark(0, n - 11, 6, 3)
    return fm


MASK_FN = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
           lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
           lambda x, y: (x * y) % 2 + (x * y) % 3 == 0,
           lambda x, y: ((x * y) % 2 + (x * y) % 3) % 2 == 0,
           lambda x, y: ((x + y) % 2 + (x * y) % 3) % 2 == 0]


def decode(rows):
    """Tiny independent reader: format -> mask, zig-zag read, de-interleave, RS check, byte mode"""
    n = len(rows)
    ver = (n - 17) // 4
    fmt = "".join(rows[8][c] for c in (0, 1, 2, 3, 4, 5, 7, 8)) + "".join(rows[r][8] for r in (7, 5, 4, 3, 2, 1, 0))
    mask = FORMAT_M.index(fmt)
    fm = _function_map(ver)
    bits = []
    right = n - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(n):
            for j in range(2):
                x = right - j
                y = n - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not fm[y][x]:
                    bits.append(int(rows[y][x]) ^ int(MASK_FN[mask](x, y)))
        right -= 2
    raw = len(bits) // 8
    cw = [int("".join(map(str, bits[i * 8:i * 8 + 8])), 2) for i in range(raw)]
    nb, ec = BLOCKS_M[ver], ECC_M[ver]
    short = raw // nb
    n_short = nb - raw % nb
    lens = [short - ec + (0 if i < n_short else 1) for i in range(nb)]
    blocks, k = [[] for _ in range(nb)], 0
    for i in range(max(lens)):
        for b in range(nb):
            if i < lens[b]:
                blocks[b].append(cw[k]); k += 1
    eccs = [[] for _ in range(nb)]
    for i in range(ec):
        for b in range(nb):
            eccs[b].append(cw[k]); k += 1
    for b in range(nb):
        assert _rs_remainder(blocks[b], ec) == eccs[b], f"RS mismatch in block {b}"
    data = [x for blk in blocks for x in blk]
    stream = "".join(format(x, "08b") for x in data)
    assert stream[:4] == "0100", "not byte mode"
    cb = 8 if ver < 10 else 16
    length = int(stream[4:4 + cb], 2)
    body = bytes(int(stream[4 + cb + i * 8:12 + cb + i * 8], 2) for i in range(length))
    return ver, body.decode("utf-8")


@unittest.skipIf(NODE is None, "node not installed")
class QrJsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = promptpay.build_payload("0812345678", 299)
        inp = json.dumps({"rsData": HELLO_DATA, "text": cls.payload, "text8": TEXT8})
        res = subprocess.run([NODE, "-e", RUNNER, str(QR_JS)], input=inp, capture_output=True,
                             text=True, timeout=30)
        if res.returncode != 0:
            raise AssertionError(res.stderr)
        cls.out = json.loads(res.stdout)

    def test_reed_solomon_reference(self):
        self.assertEqual(self.out["rs"], HELLO_EC)

    def test_format_bits(self):
        self.assertEqual([format(b, "015b") for b in self.out["fmt"]], FORMAT_M)

    def test_version_bits(self):
        self.assertEqual(format(self.out["ver7"], "018b"), VERSION7)

    def test_byte_capacity(self):
        self.assertEqual(self.out["caps"], CAPS_M)

    def test_promptpay_payload_fits_version_5(self):
        self.assertEqual(len(self.payload), 84)
        self.assertEqual(self.out["version"], 5)
        self.assertEqual(self.out["size"], 37)
        self.assertIn(self.out["mask"], range(8))

    def test_matrix_structure(self):
        rows = self.out["rows"]
        n = len(rows)
        self.assertEqual(n, 37)
        finder = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"]
        for i in range(7):
            self.assertEqual(rows[i][:7], finder[i])          # top-left
            self.assertEqual(rows[i][n - 7:], finder[i])      # top-right
            self.assertEqual(rows[n - 7 + i][:7], finder[i])  # bottom-left
        timing = "".join(rows[6][i] for i in range(8, n - 8))
        self.assertEqual(timing, ("10" * n)[:len(timing)])
        self.assertEqual(rows[n - 8][8], "1")  # dark module
        # format info copy 1 (row 8) decodes to level M + chosen mask
        fmt = format(self.out["fmt"][self.out["mask"]], "015b")
        bits = [rows[8][c] for c in (0, 1, 2, 3, 4, 5, 7, 8)] + [rows[r][8] for r in (7, 5, 4, 3, 2, 1, 0)]
        self.assertEqual("".join(bits), fmt)

    def test_independent_decode_promptpay(self):
        ver, text = decode(self.out["rows"])
        self.assertEqual(ver, 5)
        self.assertEqual(text, self.payload)

    def test_independent_decode_version8_utf8(self):
        self.assertEqual(len(TEXT8.encode("utf-8")), 140)
        ver, text = decode(self.out["rows8"])
        self.assertEqual(ver, 8)
        self.assertEqual(text, TEXT8)

    def test_too_long_rejected(self):
        self.assertTrue(self.out["tooLong"])


if __name__ == "__main__":
    unittest.main()
