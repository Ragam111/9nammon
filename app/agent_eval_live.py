"""agent_eval_live.py — golden-prompt runner (วัดคุณภาพ "คำตอบจริง" จากโมเดล)

ต่อจาก agent_eval.py (offline): ตัวนั้นวัดโครง (routing/format/prompt) โดยไม่เรียกโมเดล
ไฟล์นี้วัด "คำตอบจริง" โดยยิง prompt ชุด golden เข้า Ollama แล้วเช็กผลแบบ deterministic
(ไม่ใช้ LLM-as-judge — เครื่องสเปกต่ำรันไม่ไหว และอยากได้ผลที่ทำซ้ำได้)

ออกแบบให้:
- รันใน CI ได้โดยไม่ต้องมี Ollama — ถ้าตรวจไม่พบ service จะ *skip* (ไม่ fail)
- เทสได้โดยไม่ต้องมี Ollama — ฉีด `responder` (callable(messages)->str) แทนโมเดลจริงได้
- เช็กแบบ "ผ่อนปรนแต่มีความหมาย" (โมเดล 0.5b คำตอบไม่เป๊ะ): ไม่ว่าง / ไม่ปฏิเสธมั่ว /
  มี keyword ที่ควรมี / งานแก้โค้ดต้องตอบเป็น SEARCH/REPLACE ที่ parser แกะได้จริง

ใช้ผลนี้เทียบ before/after ตอนปรับ system prompt (คู่กับ offline scorecard)
รัน: `python -m app.agent_eval_live` (ต้องมี `ollama serve` + โมเดลอยู่)
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local_coder import (  # noqa: E402
    DIFF_BLOCK_RE,
    build_context,
    call_ollama,
    get_system_prompt,
)

DEFAULT_MODEL = "qwen2.5-coder:0.5b"   # เล็กสุด — ตรงกับ pick_model บนเครื่องสเปกต่ำ
DEFAULT_NUM_CTX = 4096

# วลีปฏิเสธที่ "ไม่ควรโผล่" กับงานเขียนโค้ดพื้นฐาน (ถ้าโผล่ = คุณภาพแย่/prompt ไม่ดี)
_REFUSAL_MARKERS = (
    "i cannot", "i can't", "i'm sorry", "i am sorry", "as an ai",
    "ขอโทษ ฉันไม่สามารถ", "ไม่สามารถช่วย", "ฉันไม่สามารถ",
)


# ───────────────────────── checks (predicate over response) ─────────────────────────
def chk_nonempty(resp: str, _case) -> bool:
    return bool(resp and resp.strip())


def chk_not_refusal(resp: str, _case) -> bool:
    low = resp.lower()
    return not any(m in low for m in _REFUSAL_MARKERS)


def chk_contains(expected: str):
    def _c(resp: str, _case) -> bool:
        return expected.lower() in resp.lower()
    _c.__name__ = f"contains[{expected}]"
    return _c


def chk_parseable_diff_for(path: str):
    """คำตอบต้องมี SEARCH/REPLACE block ที่ parser แกะได้ และ path ตรง (งานแก้โค้ด)"""
    def _c(resp: str, _case) -> bool:
        paths = [p.strip() for p, _s, _r in DIFF_BLOCK_RE.findall(resp)]
        return path in paths
    _c.__name__ = f"parseable_diff[{path}]"
    return _c


# ───────────────────────── golden cases ─────────────────────────
# แต่ละเคส: lang, user, (optional) files สำหรับ context, checks
GOLDEN_CASES = [
    {
        "id": "th_write_add",
        "lang": "th",
        "user": "เขียนฟังก์ชัน python ชื่อ add ที่บวกเลขสองจำนวนแล้ว return ผลลัพธ์",
        "checks": [chk_nonempty, chk_not_refusal, chk_contains("def")],
    },
    {
        "id": "en_reverse_string",
        "lang": "en",
        "user": "Write a Python function that reverses a string.",
        "checks": [chk_nonempty, chk_not_refusal, chk_contains("def")],
    },
    {
        "id": "th_concept_binary_search",
        "lang": "th",
        "user": "binary search มี time complexity เท่าไร อธิบายสั้นๆ",
        "checks": [chk_nonempty, chk_not_refusal, chk_contains("log")],
    },
    {
        "id": "th_edit_change_value",
        "lang": "th",
        "user": "ในไฟล์ a.py เปลี่ยนค่า x จาก 1 เป็น 2 ให้หน่อย",
        "files": {"a.py": "x = 1\n"},
        "checks": [chk_nonempty, chk_parseable_diff_for("a.py")],
    },
]


def build_messages(case: dict) -> list:
    """ประกอบ messages เหมือนที่ server/CLI ทำ: system ตามภาษา + context (ถ้ามี) + คำสั่ง"""
    msgs = [{"role": "system", "content": get_system_prompt(case.get("lang", "th"))}]
    files = case.get("files")
    user = case["user"]
    if files:
        user = build_context(files) + "\n\n" + user
    msgs.append({"role": "user", "content": user})
    return msgs


def ollama_available(host: str = "127.0.0.1", port: int = 11434, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_case(case: dict, responder) -> dict:
    """ยิง 1 เคสผ่าน responder แล้วรัน checks — คืนผลรายเช็ก"""
    resp = responder(build_messages(case))
    results = []
    for chk in case["checks"]:
        name = getattr(chk, "__name__", repr(chk))
        try:
            ok = bool(chk(resp, case))
        except Exception as e:  # check ต้องไม่ทำ runner ล้ม
            ok = False
            name += f"(error:{e})"
        results.append({"check": name, "passed": ok})
    passed = sum(1 for r in results if r["passed"])
    return {"id": case["id"], "total": len(results), "passed": passed, "checks": results}


def run_live_eval(responder=None, model: str = DEFAULT_MODEL, num_ctx: int = DEFAULT_NUM_CTX) -> dict:
    """รัน golden cases ทั้งหมด
    - responder=None และไม่พบ Ollama → คืน {skipped: True} (ไม่ fail — ใช้ใน CI ได้)
    - responder=None และพบ Ollama → เรียกโมเดลจริงผ่าน call_ollama(model, ...)
    - ฉีด responder เองได้ (เทส/mock) — callable(messages)->str
    """
    if responder is None:
        if not ollama_available():
            return {"skipped": True, "reason": "ไม่พบ Ollama ที่ 127.0.0.1:11434", "model": model}
        responder = lambda messages: call_ollama(model, messages, num_ctx)  # noqa: E731

    cases = [run_case(c, responder) for c in GOLDEN_CASES]
    total = sum(c["total"] for c in cases)
    passed = sum(c["passed"] for c in cases)
    return {
        "skipped": False,
        "model": model,
        "cases": cases,
        "overall": {
            "total": total,
            "passed": passed,
            "score_pct": round(passed / total * 100, 1) if total else 0.0,
        },
    }


def _print_report(rep: dict) -> None:
    if rep.get("skipped"):
        print(f"[skip] golden-prompt runner: {rep['reason']} "
              f"(รัน `ollama serve` + `ollama pull {rep['model']}` ก่อน)")
        return
    print(f"=== LCA agent quality — live golden prompts (model={rep['model']}) ===")
    for c in rep["cases"]:
        mark = "OK " if c["passed"] == c["total"] else "!! "
        print(f"  [{mark}] {c['id']:28s} {c['passed']}/{c['total']}")
        for r in c["checks"]:
            if not r["passed"]:
                print(f"        - FAIL: {r['check']}")
    ov = rep["overall"]
    print(f"  ---\n  overall: {ov['passed']}/{ov['total']} ({ov['score_pct']}%)")


if __name__ == "__main__":
    _print_report(run_live_eval())
