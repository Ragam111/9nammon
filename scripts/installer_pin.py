"""Print installer_gui.py's PINNED_COMMIT or ZIP_SHA256 without importing it (no tkinter)."""

import ast
import sys
from pathlib import Path

NAMES = {"commit": "PINNED_COMMIT", "sha256": "ZIP_SHA256"}


def read_pin(name: str, path: Path = Path(__file__).resolve().parent.parent / "installer_gui.py") -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            value = node.value.value
            if isinstance(value, str):
                return value
    raise KeyError(name)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in NAMES:
        print("usage: installer_pin.py commit|sha256", file=sys.stderr)
        return 2
    print(read_pin(NAMES[argv[1]]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
