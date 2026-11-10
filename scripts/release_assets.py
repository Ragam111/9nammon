"""Build (and optionally upload) the source package that install.ps1 / update.ps1 /
TokenLCAlimit.exe download from the latest GitHub Release.

    python scripts/release_assets.py                 # dist/lca-source.zip + .sha256 from HEAD
    python scripts/release_assets.py --upload v0.3.4 # also attach both to that Release (gh CLI)

- ``git archive`` of the ref (default HEAD; ``.gitattributes`` export-ignore drops
  tests/, .github/, .vscode/), top folder ``LocalCodeAssistant-<VERSION>/``.
- ``lca-source.zip.sha256`` in ``sha256sum`` format: ``<hex>  lca-source.zip``.
- ``--upload`` refuses when the tag is not ``v<VERSION>``; creates the Release if
  it does not exist, otherwise replaces the two assets (``--clobber``).

Stdlib + git (+ gh for --upload).
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP_NAME = "lca-source.zip"


def read_version(root: Path = ROOT, ref: str = "HEAD") -> str:
    out = subprocess.run(["git", "show", f"{ref}:VERSION"], cwd=root,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(out_dir: Path, ref: str = "HEAD", root: Path = ROOT) -> tuple[Path, Path, str]:
    version = read_version(root, ref)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / ZIP_NAME
    subprocess.run(["git", "archive", "--format=zip", f"--prefix=LocalCodeAssistant-{version}/",
                    "-o", str(zip_path), ref], cwd=root, check=True)
    digest = sha256_of(zip_path)
    sha_path = out_dir / f"{ZIP_NAME}.sha256"
    sha_path.write_text(f"{digest}  {ZIP_NAME}\n", encoding="ascii", newline="\n")
    return zip_path, sha_path, version


def upload(tag: str, version: str, files, root: Path = ROOT) -> None:
    if tag != f"v{version}":
        raise SystemExit(f"tag {tag} ไม่ตรงกับ VERSION ({version}) — แก้ VERSION หรือ tag ก่อน")
    exists = subprocess.run(["gh", "release", "view", tag], cwd=root,
                            capture_output=True).returncode == 0
    names = [str(f) for f in files]
    if exists:
        subprocess.run(["gh", "release", "upload", tag, *names, "--clobber"], cwd=root, check=True)
    else:
        subprocess.run(["gh", "release", "create", tag, *names, "--title", f"LCA {tag}",
                        "--notes", "ดู CHANGELOG.md"], cwd=root, check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", default="HEAD", help="git ref to package (default HEAD)")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="output folder (default dist/)")
    ap.add_argument("--upload", metavar="TAG", help="attach to this GitHub Release (gh CLI)")
    args = ap.parse_args(argv)
    ref = args.upload if args.upload and args.ref == "HEAD" else args.ref
    zip_path, sha_path, version = build(Path(args.out), ref)
    print(sha_path.read_text(encoding="ascii").strip())
    if args.upload:
        upload(args.upload, version, [zip_path, sha_path])
        print(f"uploaded to release {args.upload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
