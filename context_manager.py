"""
context_manager.py — auto-scan ไฟล์ในโปรเจกต์ใส่ context อัตโนมัติ (Phase 3, Day 2)
ทำงานคู่กับ /add เดิม (ไม่แทนที่) ตาม design doc ที่ตกลงไว้:

- auto-scan เป็น default, /add ยังบังคับใส่เพิ่มเองได้เสมอ (manual มีสิทธิ์เหนือกว่า)
- scan ใหม่ทุกครั้งก่อนส่งข้อความ (fresh เสมอ) แต่อ่านเนื้อหาไฟล์ซ้ำเฉพาะไฟล์ที่ mtime
  เปลี่ยนจากรอบก่อน (กันหน่วงบนเครื่อง RAM 8GB ถ้าโปรเจกต์มีไฟล์เยอะ)
- .lcaignore แบบ fnmatch/gitignore-style + default ignore list ที่ override ไม่ได้
- token budget: ใส่เนื้อหาได้ไม่เกิน ~60% ของ num_ctx ที่เหลือ, ข้ามไฟล์ >50KB
  (ให้ /add บังคับใส่เองถ้าจำเป็นจริงๆ)
"""

import fnmatch
from pathlib import Path
from typing import Dict, Tuple

LCAIGNORE_FILE_NAME = ".lcaignore"
MAX_FILE_SIZE_BYTES = 50 * 1024       # ไฟล์ใหญ่กว่านี้ข้าม auto-scan เสมอ
CONTEXT_BUDGET_RATIO = 0.6            # auto-context ใช้ได้ไม่เกิน 60% ของ num_ctx ที่เหลือ
CHARS_PER_TOKEN_ESTIMATE = 4          # ประมาณคร่าวๆ เหมือนที่ estimate_tokens() ใช้อยู่แล้ว

DEFAULT_IGNORE_PATTERNS = [
    ".git", ".git/*",
    "__pycache__", "__pycache__/*",
    "node_modules", "node_modules/*",
    "venv", "venv/*", ".venv", ".venv/*",
    ".local_coder_backup", ".local_coder_backup/*",
    "todos.json",
    "CHANGELOG_local.md",
    "config.json",
    ".lca_trust",
    ".lcaignore",
    "*.pyc", "*.pyo",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.pdf",
    "*.zip", "*.tar", "*.gz",
]

# cache ระดับโมดูล: {project_root_str: {rel_path: (mtime, content)}}
# อยู่ใน memory ระหว่างรันโปรแกรมเดียวเท่านั้น — ปิดโปรแกรมแล้ว cache หายไปเอง (ตั้งใจ)
_content_cache: Dict[str, Dict[str, Tuple]] = {}


def load_ignore_patterns(project_root: Path) -> list:
    """โหลด pattern จาก .lcaignore (ถ้ามี) รวมกับ default list เสมอ
    default list ห้าม override ทิ้งได้ — กันไฟล์ระบบ (todos.json, config.json ฯลฯ)
    หลุดเข้า context โดยไม่ตั้งใจ ต่อให้ผู้ใช้ไม่ได้ระบุใน .lcaignore เอง"""
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    ignore_file = project_root / LCAIGNORE_FILE_NAME
    if ignore_file.exists():
        try:
            for line in ignore_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        except OSError as e:
            print(f"[context][warn] อ่าน {LCAIGNORE_FILE_NAME} ไม่ได้: {e} (ใช้ default list อย่างเดียว)")
    return patterns


def _is_ignored(rel_path: str, patterns: list) -> bool:
    name = Path(rel_path).name
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False


def scan_workspace(project_root: Path) -> list:
    """คืน list ของไฟล์ทั้งหมดในโปรเจกต์ที่ไม่ถูก ignore (เป็น Path object)
    operation นี้เบา (แค่ walk + match pattern ไม่อ่านเนื้อหา) เรียกทุกข้อความได้"""
    patterns = load_ignore_patterns(project_root)
    results = []
    try:
        for path in project_root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(project_root))
            if _is_ignored(rel, patterns):
                continue
            results.append(path)
    except OSError as e:
        print(f"[context][warn] สแกนโปรเจกต์ไม่สำเร็จ: {e}")
    return results


def _get_cached_content(project_root: Path, path: Path) -> str:
    """อ่านเนื้อหาไฟล์โดยใช้ cache ถ้า mtime ไม่เปลี่ยนจากรอบก่อน
    คืนค่า None ถ้าอ่านไม่ได้ (binary/permission) — ผู้เรียกต้องข้ามไฟล์นั้นไปเงียบๆ"""
    key = str(project_root)
    rel = str(path.relative_to(project_root))
    cache = _content_cache.setdefault(key, {})

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    cached = cache.get(rel)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None  # ไฟล์ binary หรืออ่านไม่ได้ — ไม่ใช่ error ที่ผู้ใช้ต้องเห็นทุกครั้ง ข้ามเงียบๆ

    cache[rel] = (mtime, content)
    return content


def build_auto_context(project_root: Path, num_ctx: int, already_manual: set) -> dict:
    """คืน dict {rel_path: content} ของไฟล์ที่ auto-scan เลือกใส่ context รอบนี้
    already_manual = set ของไฟล์ที่ผู้ใช้ /add เองแล้ว — ไม่เอามาซ้ำ เพราะ manual
    มีสิทธิ์เหนือกว่าเสมอตาม design doc (ไม่นับ manual เข้า budget ของ auto ด้วย)"""
    candidates = []
    for path in scan_workspace(project_root):
        rel = str(path.relative_to(project_root))
        if rel in already_manual:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > MAX_FILE_SIZE_BYTES:
            continue
        candidates.append((rel, path, stat.st_size, stat.st_mtime))

    # เรียง: แก้ล่าสุดก่อน (mtime มาก -> น้อย), เท่ากันให้ไฟล์เล็กก่อน — ตาม design doc
    candidates.sort(key=lambda x: (-x[3], x[2]))

    budget_chars = int(num_ctx * CONTEXT_BUDGET_RATIO * CHARS_PER_TOKEN_ESTIMATE)
    used_chars = 0
    result = {}
    skipped_for_budget = 0

    for rel, path, size, mtime in candidates:
        content = _get_cached_content(project_root, path)
        if content is None:
            continue
        if used_chars + len(content) > budget_chars:
            skipped_for_budget += 1
            continue
        result[rel] = content
        used_chars += len(content)

    if skipped_for_budget:
        print(f"[context][auto] ข้าม {skipped_for_budget} ไฟล์เพราะ token budget เต็ม "
              f"(ใช้ /add <path> บังคับใส่ไฟล์ที่ต้องการจริงๆ)")

    return result
