"""agent_eval.py — เกณฑ์วัดคุณภาพ agent แบบ offline (ไม่ต้องมี Ollama)

ทำไมต้องมี: Q ใน ROADMAP = "ปรับ system prompt ให้ agent ตอบดีขึ้น" แต่จะปรับอย่าง
มีหลักการต้อง **วัดก่อน** ไม่งั้นคือเดา (หลัก 9arm: วัดก่อนตัดสิน). ไฟล์นี้คือ
baseline เป็น "ตัวเลข" ที่รันได้ทันทีใน CI ไม่ต้องรอ Ollama — ปรับ prompt/heuristic
แล้ววัดซ้ำ เทียบ before/after ได้ตรงๆ

วัด 3 มิติที่ตรวจได้แบบ deterministic โดย *ไม่เรียกโมเดลเลย* — เช็คพฤติกรรมของโค้ด
ประกอบ prompt/context ที่มีอยู่แล้วใน local_coder.py:
  1. routing   — classify_input() ส่งคำสั่งเข้าหมวดถูกไหม (general/code_edit/external)
  2. diff      — DIFF_BLOCK_RE แกะ SEARCH/REPLACE ที่โมเดล *ควร* ตอบออกมาได้ครบไหม
                 (ถ้า format contract นี้พัง = แก้ไฟล์ไม่ได้เลย = agent ใช้ไม่ได้)
  3. prompt    — system prompt บอก format + ภาษา + ทางหนี (คำถามทั่วไปตอบ plain text) ครบไหม

ส่วน context budget (build_auto_context) ต้องใช้ไฟล์จริง เลยวัดใน tests/ แทน
(ที่นี่เก็บเฉพาะมิติที่ pure — scorecard() เรียกที่ไหนก็ได้ ไม่แตะดิสก์/เน็ต)

รัน `python -m app.agent_eval` (หรือ `python app/agent_eval.py`) เพื่อพิมพ์ scorecard
"""

from __future__ import annotations

import sys
from pathlib import Path

# ให้ import local_coder (อยู่ที่ repo root) ได้ ไม่ว่าจะถูกเรียกจากไหน
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local_coder import (  # noqa: E402
    DIFF_BLOCK_RE,
    classify_input,
    get_system_prompt,
)

# ───────────────────────── มิติ 1: routing ─────────────────────────
# (text, has_files_in_context, expected_category) — เข้ารหัสพฤติกรรมที่ "ตั้งใจ"
# ให้เป็น baseline; เคสเลือกให้ชัด ไม่กำกวม เพื่อ lock ไม่ให้ heuristic ถอยหลัง
ROUTING_CASES = [
    # external_project — keyword ชัด (ตรวจก่อน code_edit เสมอ)
    ("ดึง issue จาก linear มาสรุป", False, "external_project"),
    ("sync ticket ใน jira ให้หน่อย", False, "external_project"),
    ("อัปเดต issue tracker ของทีม", False, "external_project"),
    # code_edit — มี keyword แก้โค้ด
    ("แก้บั๊กในฟังก์ชัน login", False, "code_edit"),
    ("ช่วย refactor โมดูลนี้ที", False, "code_edit"),
    ("add function สำหรับ parse config", False, "code_edit"),
    ("สร้างไฟล์ utils.py ใหม่", False, "code_edit"),
    ("implement rate limiter", False, "code_edit"),
    # code_edit — ไม่มี keyword แต่มีไฟล์ใน context (มีไฟล์ = ตั้งใจจะแก้)
    ("อันนี้ทำงานยังไง", True, "code_edit"),
    # general — ถามเฉยๆ ไม่มีไฟล์ ไม่มี keyword
    ("binary search ทำงานยังไง", False, "general"),
    ("อธิบาย big-O ให้ฟังหน่อย", False, "general"),
    ("ควรใช้ list หรือ dict ดีกว่ากัน", False, "general"),
]

# ───────────────────────── มิติ 2: diff format contract ─────────────────────────
# (response_text, expected_paths) — จำลองสิ่งที่โมเดล *ควร* ตอบตาม system prompt
# วัดว่า parser แกะ block ได้ตรง (path ที่ได้ = path ที่คาด)
_SINGLE = (
    "แก้ให้แล้วครับ\n"
    "app/util.py\n"
    "<<<<<<< SEARCH\n"
    "x = 1\n"
    "=======\n"
    "x = 2\n"
    ">>>>>>> REPLACE\n"
)
_MULTI = (
    "a.py\n<<<<<<< SEARCH\nold_a\n=======\nnew_a\n>>>>>>> REPLACE\n"
    "\nและอีกไฟล์\n"
    "b/c.py\n<<<<<<< SEARCH\nold_c\n=======\nnew_c\n>>>>>>> REPLACE\n"
)
_NEW_FILE = (  # ไฟล์ใหม่ = SEARCH block ว่าง (มีบรรทัดว่างคั่น ตาม format ใน system prompt)
    "สร้างไฟล์ใหม่ให้\n"
    "new.py\n<<<<<<< SEARCH\n\n=======\nprint('hi')\n>>>>>>> REPLACE\n"
)
_PLAIN = "ใช้ dict ดีกว่าครับ เพราะ lookup เป็น O(1)"  # คำถามทั่วไป ไม่มี block
_MALFORMED = (
    "app/util.py\n<<<<<<< SEARCH\nx = 1\n"  # ไม่มี ======= / REPLACE marker
)

DIFF_CASES = [
    (_SINGLE, ["app/util.py"]),
    (_MULTI, ["a.py", "b/c.py"]),
    (_NEW_FILE, ["new.py"]),
    (_PLAIN, []),         # คำตอบ plain ต้องแกะได้ 0 block (ไม่ false-positive)
    (_MALFORMED, []),     # block พังต้องไม่ถูกแกะมั่ว
]

# ───────────────────────── มิติ 3: system prompt contract ─────────────────────────
# marker ของ SEARCH/REPLACE ที่ต้องอยู่ใน prompt ทั้งสองภาษา (ไม่งั้นโมเดลไม่รู้ format)
_FORMAT_MARKERS = ("<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE")


def eval_routing() -> dict:
    """วัด classify_input กับ ROUTING_CASES — คืน {total, passed, failures}"""
    failures = []
    for text, has_files, expected in ROUTING_CASES:
        got = classify_input(text, has_files)
        if got != expected:
            failures.append({"text": text, "expected": expected, "got": got})
    total = len(ROUTING_CASES)
    return {"dimension": "routing", "total": total,
            "passed": total - len(failures), "failures": failures}


def _diff_paths(response: str) -> list:
    """แกะ path จากทุก SEARCH/REPLACE block ในคำตอบ (เรียงตามที่เจอ)"""
    return [path.strip() for path, _search, _replace in DIFF_BLOCK_RE.findall(response)]


def eval_diff_parsing() -> dict:
    """วัดว่า DIFF_BLOCK_RE แกะ block ได้ตรง expected_paths — คืน {total, passed, failures}"""
    failures = []
    for response, expected in DIFF_CASES:
        got = _diff_paths(response)
        if got != expected:
            failures.append({"expected": expected, "got": got})
    total = len(DIFF_CASES)
    return {"dimension": "diff_parsing", "total": total,
            "passed": total - len(failures), "failures": failures}


def eval_prompt_contract() -> dict:
    """วัดว่า system prompt ครบสัญญา: format markers + ภาษา + ทางหนี plain text
    นับเป็นรายเช็ค (ทั้ง th และ en) — คืน {total, passed, failures}"""
    failures = []
    checks = []  # (label, passed)

    th = get_system_prompt("th")
    en = get_system_prompt("en")

    for marker in _FORMAT_MARKERS:
        checks.append((f"th has {marker!r}", marker in th))
        checks.append((f"en has {marker!r}", marker in en))

    # ภาษาถูกสั่งให้ตอบตรงกับ lang
    checks.append(("th tells answer in Thai", "ภาษาไทย" in th))
    checks.append(("en tells answer in English", "English" in en))

    # ต้องมีทางหนี: คำถามทั่วไปให้ตอบ plain text (ไม่บังคับ diff format ตลอด)
    checks.append(("th allows plain-text answer", "plain" in th.lower() or "ปกติ" in th or "ข้อความ" in th))
    checks.append(("en allows plain-text answer", "plain text" in en.lower()))

    # เลือก lang ไม่รู้จัก → ต้อง fallback เป็น th (ไม่ crash / ไม่คืน en)
    checks.append(("unknown lang falls back to th", get_system_prompt("xx") == th))

    for label, ok in checks:
        if not ok:
            failures.append({"check": label})
    total = len(checks)
    return {"dimension": "prompt_contract", "total": total,
            "passed": total - len(failures), "failures": failures}


def scorecard() -> dict:
    """รวม 3 มิติเป็น scorecard เดียว + คะแนนรวม (เอาไปเทียบ before/after prompt ได้)"""
    dims = [eval_routing(), eval_diff_parsing(), eval_prompt_contract()]
    total = sum(d["total"] for d in dims)
    passed = sum(d["passed"] for d in dims)
    return {
        "dimensions": {d["dimension"]: d for d in dims},
        "overall": {
            "total": total,
            "passed": passed,
            "score_pct": round(passed / total * 100, 1) if total else 0.0,
        },
    }


def _print_scorecard(sc: dict) -> None:
    print("=== LCA agent quality — offline scorecard ===")
    for name, d in sc["dimensions"].items():
        mark = "OK " if d["passed"] == d["total"] else "!! "
        print(f"  [{mark}] {name:16s} {d['passed']}/{d['total']}")
        for f in d["failures"]:
            print(f"        - FAIL: {f}")
    ov = sc["overall"]
    print(f"  ---\n  overall: {ov['passed']}/{ov['total']} ({ov['score_pct']}%)")


if __name__ == "__main__":
    sc = scorecard()
    _print_scorecard(sc)
    # exit 1 ถ้ามีมิติไหนตก (ใช้เป็น gate เองได้ถ้าต้องการ)
    sys.exit(0 if sc["overall"]["passed"] == sc["overall"]["total"] else 1)
