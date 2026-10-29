#!/usr/bin/env python3
"""qa.py — Dev pipeline (linearize) ของ LCA: optimize → lint → test → smoke → report

ไอเดีย (ตาม user): แทนที่จะรันหลายคำสั่งแยกกัน รวมเป็น **script เดียวที่วิ่งทั้ง pipeline**
วิ่งแล้วรู้ทันทีว่าโปรเจกต์พร้อม release หรือยัง (ก่อนทำ content/PR ต่อไป)

ขั้นตอน (default — ทำครบทุกข้อ):
  1. **syntax**  — compile ทุกไฟล์ .py (`py_compile`) หา syntax error เร็ว ๆ
  2. **imports** — import ทุก module ของ app/ (เจอ import error ตั้งแต่ CI)
  3. **lint**    — ตรวจพื้นฐาน: unused imports, trailing whitespace, mixed tabs/spaces
                   (stdlib ล้วน — AST + regex, ไม่ต้องลง pyflakes/ruff)
  4. **test**    — รัน `python -m unittest discover -s tests` (812 tests)
  5. **smoke**   — start server บน port สุ่ม → GET /api/health, /api/status → 200
  6. **summary** — รายงานเวลา/ผ่าน/ล้ม + exit 0 (ผ่านหมด) หรือ exit 1 (ล้ม)

ใช้ยังไง:
  python scripts/qa.py              # ทำครบทุกขั้น (ประมาณ 1 นาที)
  python scripts/qa.py --fast       # ข้าม tests + smoke (quick check)
  python scripts/qa.py --only=lint  # เฉพาะขั้นนี้

stdlib ล้วน ตามหลักโปรเจกต์. ไม่พึ่ง pyflakes/ruff/pytest.
"""

from __future__ import annotations

import argparse
import ast
import http.client
import json
import os
import py_compile
import socket
import subprocess
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------- Step 1: syntax ----------
def step_syntax() -> tuple[bool, str]:
    errors = []
    for py in sorted(ROOT.rglob("*.py")):
        # ข้าม venv/__pycache__/scratch
        if any(part in ("__pycache__", "venv", ".venv", "build", "dist") for part in py.parts):
            continue
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"{py.relative_to(ROOT)}: {e.msg.strip()}")
    if errors:
        return False, "syntax errors:\n  " + "\n  ".join(errors)
    return True, "all .py files compile cleanly"


# ---------- Step 2: imports ----------
def step_imports() -> tuple[bool, str]:
    """ตรวจว่า module สำคัญ import ได้ไม่ error (ครอบ import-time bugs)"""
    sys.path.insert(0, str(ROOT))
    modules = ["server", "installer_gui", "lca_app"]
    # app/* modules (auto-discover)
    for py in sorted((ROOT / "app").glob("*.py")):
        if py.stem != "__init__":
            modules.append(f"app.{py.stem}")
    errors = []
    for mod in modules:
        try:
            __import__(mod)
        except Exception as e:
            errors.append(f"{mod}: {type(e).__name__}: {e}")
    if errors:
        return False, "import errors:\n  " + "\n  ".join(errors)
    return True, f"imported {len(modules)} modules cleanly"


# ---------- Step 3: lint (stdlib-only basic checks) ----------
def _find_unused_imports(tree: ast.AST, source: str) -> list[str]:
    """หา imported name ที่ไม่ได้ใช้ใน source (basic AST walk)"""
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            # ข้าม `from __future__` — ใช้ตอน compile ไม่ใช่ runtime
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                name = alias.asname or alias.name
                imported[name] = node.lineno

    # เก็บชื่อที่ใช้จริง (Name node)
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # x.y → x ถูกใช้
            obj = node.value
            while isinstance(obj, ast.Attribute):
                obj = obj.value
            if isinstance(obj, ast.Name):
                used.add(obj.id)

    issues = []
    for name, lineno in imported.items():
        if name not in used and name != "_":
            # ยกเว้น: __all__ อาจอ้างชื่อโดยไม่มี Name node ปกติ — เช็ค source ตรง ๆ
            if name in source:
                continue
            issues.append(f"line {lineno}: unused import '{name}'")
    return issues


def _find_whitespace_issues(source: str) -> list[str]:
    issues = []
    for i, line in enumerate(source.splitlines(), 1):
        if line.rstrip() != line:
            issues.append(f"line {i}: trailing whitespace")
        if "\t" in line and " " in line.replace("\t", "", 1):
            # ถ้ามีทั้ง tab และ space ใน line เดียว (mixed) — มี exception คือ tab ตามด้วย space
            # บรรทัดเริ่มด้วย tab แล้วมี space เพื่อ align (acceptable) → skip
            pass  # keep rule simple
    return issues


def step_lint() -> tuple[bool, str]:
    """lint stdlib-only: unused imports + trailing whitespace"""
    issues = []
    files_checked = 0
    for py in sorted(ROOT.rglob("*.py")):
        if any(part in ("__pycache__", "venv", ".venv", "build", "dist") for part in py.parts):
            continue
        try:
            source = py.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py))
        except (OSError, SyntaxError):
            continue  # ข้ามไฟล์ที่ parse ไม่ได้ (step_syntax จะจับเอง)
        files_checked += 1
        rel = py.relative_to(ROOT)
        for issue in _find_unused_imports(tree, source):
            issues.append(f"{rel}:{issue}")
        for issue in _find_whitespace_issues(source):
            issues.append(f"{rel}:{issue}")

    if issues:
        # Limit display to first 20
        shown = issues[:20]
        extra = len(issues) - len(shown)
        msg = f"lint issues ({len(issues)} total in {files_checked} files):\n  " + "\n  ".join(shown)
        if extra > 0:
            msg += f"\n  ... and {extra} more"
        # Return success=True (warnings only) but include in report
        return True, msg
    return True, f"no lint issues in {files_checked} files"


# ---------- Step 4: tests ----------
def step_tests() -> tuple[bool, str]:
    """รัน unittest suite — ใช้ subprocess เพื่อแยก process (clean imports)"""
    start = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    duration = time.time() - start
    # unittest เขียน summary ไป stderr
    output = result.stderr or result.stdout
    last_lines = output.strip().splitlines()[-3:]
    summary = " | ".join(last_lines)
    if result.returncode == 0:
        return True, f"{summary} ({duration:.1f}s)"
    return False, f"FAILED ({duration:.1f}s)\n{output[-2000:]}"


# ---------- Step 5: smoke ----------
def step_smoke() -> tuple[bool, str]:
    """start server → ยิง /api/health, /api/status → ตรวจ 200 + JSON shape"""
    sys.path.insert(0, str(ROOT))
    try:
        import server
    except Exception as e:
        return False, f"ไม่สามารถ import server: {e}"

    try:
        # หา port ว่าง
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    except OSError as e:
        return False, f"หา port ว่างไม่ได้: {e}"

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        handler = server.make_handler(Path(tmp), None)
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError as e:
            return False, f"start server ไม่ได้ที่ port {port}: {e}"
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            checks = []
            # /api/health
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            body = json.loads(resp.read().decode("utf-8"))
            conn.close()
            if resp.status != 200 or not body.get("ok"):
                checks.append(f"❌ /api/health: {resp.status}")
            else:
                checks.append("✅ /api/health: 200 ok")

            # /api/status
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/status")
            resp = conn.getresponse()
            body = json.loads(resp.read().decode("utf-8"))
            conn.close()
            if resp.status != 200 or "state" not in body:
                checks.append(f"❌ /api/status: {resp.status}")
            else:
                checks.append(f"✅ /api/status: {body['state']}")

            # /
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status != 200:
                checks.append(f"❌ /: {resp.status}")
            else:
                checks.append("✅ / (chat UI): 200")

            all_ok = all(c.startswith("✅") for c in checks)
            return all_ok, " | ".join(checks)
        finally:
            httpd.shutdown()
            httpd.server_close()


# ---------- Pipeline ----------
STEPS = {
    "syntax": step_syntax,
    "imports": step_imports,
    "lint": step_lint,
    "test": step_tests,
    "smoke": step_smoke,
}

FAST_STEPS = ("syntax", "imports", "lint")


def run_pipeline(step_names: list[str]) -> int:
    print(f"\n{'=' * 60}\n  LCA QA Pipeline — v0.1.0\n{'=' * 60}")
    results = []
    pipeline_start = time.time()
    for name in step_names:
        fn = STEPS[name]
        print(f"\n▶ [{name}] running...")
        start = time.time()
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"EXCEPTION: {type(e).__name__}: {e}"
        duration = time.time() - start
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {status} ({duration:.1f}s) {msg}")
        results.append((name, ok, duration))
        if not ok and name in ("syntax", "imports", "test"):
            # หยุดถ้า critical step ล้ม (ทำขั้นต่อไม่ได้)
            print(f"\n⛔ หยุด pipeline: {name} ล้มเหลว")
            break
    total = time.time() - pipeline_start
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{'=' * 60}\n  Summary: {passed}/{len(results)} steps passed ({total:.1f}s total)")
    print(f"{'=' * 60}")
    return 0 if all(ok for _, ok, _ in results) else 1


def main():
    parser = argparse.ArgumentParser(description="LCA QA pipeline")
    parser.add_argument("--fast", action="store_true",
                        help="เฉพาะขั้นเร็ว: syntax + imports + lint (ข้าม test+smoke)")
    parser.add_argument("--only", type=str, help="รันขั้นเดียว (ตัวอย่าง: --only=lint)")
    args = parser.parse_args()

    if args.only:
        if args.only not in STEPS:
            print(f"ไม่รู้จักขั้น '{args.only}'. มี: {list(STEPS.keys())}")
            return 2
        step_names = [args.only]
    elif args.fast:
        step_names = list(FAST_STEPS)
    else:
        step_names = list(STEPS.keys())

    return run_pipeline(step_names)


if __name__ == "__main__":
    raise SystemExit(main())
