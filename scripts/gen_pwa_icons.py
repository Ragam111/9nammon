"""gen_pwa_icons.py — build the LCA PWA icons with the stdlib only (zlib + struct).

Run: python scripts/gen_pwa_icons.py   (writes app/icons/*.png)
Design: accent green square (#1f8a4c, from app.css) with a white "L" glyph.
The maskable icon keeps the glyph inside the 80% safe zone.
"""

import struct
import zlib
from pathlib import Path

ACCENT = (0x1F, 0x8A, 0x4C)
WHITE = (0xFF, 0xFF, 0xFF)
OUT_DIR = Path(__file__).resolve().parent.parent / "app" / "icons"


def _chunk(ctype: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)


def encode_png(size: int, pixel) -> bytes:
    """Encode an RGB size x size PNG; pixel(x, y) -> (r, g, b)."""
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter type: none
        for x in range(size):
            rows.extend(pixel(x, y))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _chunk(b"IEND", b""))


def glyph_pixel(size: int, inset: float):
    """Return a pixel function drawing an "L" inside a box inset by `inset` (0..0.5)."""
    lo, hi = size * (inset + 0.12), size * (1 - inset - 0.12)
    stroke = (hi - lo) * 0.28

    def pixel(x: int, y: int):
        in_box = lo <= x < hi and lo <= y < hi
        vertical = lo <= x < lo + stroke
        bottom = hi - stroke <= y < hi
        return WHITE if in_box and (vertical or bottom) else ACCENT
    return pixel


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = {
        "icon-192.png": (192, 0.08),
        "icon-512.png": (512, 0.08),
        "icon-maskable-512.png": (512, 0.18),  # glyph stays in the safe zone
        "apple-touch-icon.png": (180, 0.08),
    }
    for name, (size, inset) in targets.items():
        (OUT_DIR / name).write_bytes(encode_png(size, glyph_pixel(size, inset)))
        print(f"wrote {name} ({size}x{size})")


if __name__ == "__main__":
    main()
