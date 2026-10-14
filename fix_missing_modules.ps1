# fix_missing_modules.ps1
# แก้ ModuleNotFoundError: No module named 'folder_trust' (และ context_manager)
# สคริปต์นี้ "เขียนไฟล์ที่ขาดหายไปโดยตรง" ไม่ต้องดาวน์โหลด/copy ไฟล์เองเลย
# วิธีใช้: คลิกขวาไฟล์นี้ -> Run with PowerShell
#          (หรือเปิด PowerShell แล้วรัน: powershell -ExecutionPolicy Bypass -File fix_missing_modules.ps1)

$ErrorActionPreference = "Stop"

$AppDir = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant\app"

Write-Host "=== แก้ ModuleNotFoundError: folder_trust / context_manager ===" -ForegroundColor Cyan
Write-Host "เป้าหมาย: $AppDir"

if (-not (Test-Path $AppDir)) {
    Write-Host "[error] ไม่พบโฟลเดอร์ $AppDir — ยังไม่เคยติดตั้ง Local Code Assistant หรือ path ไม่ตรง" -ForegroundColor Red
    Write-Host "        เช็คว่าเคยรัน install.bat ที่เครื่องนี้แล้วหรือยัง" -ForegroundColor Yellow
    exit 1
}

# ---------- folder_trust.py ----------
$folderTrustContent = @'
"""
folder_trust.py -- confirm project folder trust before Local Code Assistant
scans/edits files, the first time a new folder is opened.

Prevents the case where the wrong folder was opened (e.g. a typo in the path)
and the system starts editing files without the user realizing which folder
it is actually working in.

Marker file: <project_root>/.lca_trust -- stores the timestamp of the first
confirmation only. Reopening the same project (marker already exists) will
not ask again.
"""

from datetime import datetime
from pathlib import Path

TRUST_MARKER_NAME = ".lca_trust"


def _marker_path(project_root: Path) -> Path:
    return project_root / TRUST_MARKER_NAME


def is_trusted(project_root: Path) -> bool:
    """Check whether a marker file already exists (previously confirmed)."""
    return _marker_path(project_root).exists()


def mark_trusted(project_root: Path) -> None:
    """Create the marker file -- call only after the user confirms with y."""
    marker = _marker_path(project_root)
    try:
        marker.write_text(
            f"trusted_at={datetime.now().isoformat(timespec='seconds')}\n",
            encoding="utf-8",
        )
    except OSError as e:
        print(f"[trust][warn] could not create {TRUST_MARKER_NAME}: {e} (will ask again next time)")


def ensure_trusted(project_root: Path) -> bool:
    """Call at program startup (before print_banner). If never confirmed,
    ask directly. Returns True if OK to continue (confirmed now or before).
    Returns False if the user declined (caller must stop the program)."""
    if is_trusted(project_root):
        return True

    print(f"[trust] This project has not been opened before: {project_root}")
    print("[trust] Local Code Assistant will be able to read/edit files in this folder from now on")
    try:
        answer = input("[trust] Confirm this is the project you want to work with? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if answer != "y":
        print("[trust] Cancelled -- not confirmed, so not starting work on this folder")
        return False

    mark_trusted(project_root)
    print(f"[trust] Saved -- opening this project again will not ask ({TRUST_MARKER_NAME})")
    return True
'@

# ---------- context_manager.py ----------
$contextManagerContent = @'
"""
context_manager.py -- auto-scan project files into context automatically
(Phase 3, Day 2). Works alongside the existing /add (does not replace it),
per the agreed design doc:

- auto-scan is the default; /add still lets the user force-add files
  manually (manual always takes priority)
- re-scans fresh before every message sent, but only re-reads file content
  for files whose mtime changed since the last round (avoids slowdown on
  8GB RAM machines with large projects)
- .lcaignore uses fnmatch/gitignore-style patterns + a default ignore list
  that cannot be overridden
- token budget: only fills up to ~60% of remaining num_ctx, skips files
  over 50KB (use /add to force-include them if truly needed)
"""

import fnmatch
from pathlib import Path

LCAIGNORE_FILE_NAME = ".lcaignore"
MAX_FILE_SIZE_BYTES = 50 * 1024       # files larger than this are always skipped by auto-scan
CONTEXT_BUDGET_RATIO = 0.6            # auto-context may use at most 60% of remaining num_ctx
CHARS_PER_TOKEN_ESTIMATE = 4          # rough estimate, matches estimate_tokens() elsewhere

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

# module-level cache: {project_root_str: {rel_path: (mtime, content)}}
# lives only in memory for the current run -- cleared when the program exits (intentional)
_content_cache: dict[str, dict[str, tuple]] = {}


def load_ignore_patterns(project_root: Path) -> list:
    """Load patterns from .lcaignore (if present) combined with the default
    list always. The default list cannot be overridden -- protects system
    files (todos.json, config.json, etc.) from accidentally leaking into
    context even if the user did not list them in .lcaignore themselves."""
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    ignore_file = project_root / LCAIGNORE_FILE_NAME
    if ignore_file.exists():
        try:
            for line in ignore_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        except OSError as e:
            print(f"[context][warn] could not read {LCAIGNORE_FILE_NAME}: {e} (using default list only)")
    return patterns


def _is_ignored(rel_path: str, patterns: list) -> bool:
    name = Path(rel_path).name
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False


def scan_workspace(project_root: Path) -> list:
    """Return a list of all files in the project that are not ignored (as
    Path objects). This operation is lightweight (just walks + matches
    patterns, does not read content) so it's safe to call on every message."""
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
        print(f"[context][warn] project scan failed: {e}")
    return results


def _get_cached_content(project_root: Path, path: Path) -> str:
    """Read file content using the cache if mtime hasn't changed since the
    last round. Returns None if unreadable (binary/permission) -- caller
    must silently skip that file."""
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
        return None  # binary or unreadable file -- not an error the user needs to see every time, skip silently

    cache[rel] = (mtime, content)
    return content


def build_auto_context(project_root: Path, num_ctx: int, already_manual: set) -> dict:
    """Return a dict {rel_path: content} of files auto-scan selected to
    include in context this round. already_manual = set of files the user
    already /add'd manually -- not duplicated here, since manual always
    takes priority per the design doc (and doesn't count against auto's
    budget either)."""
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

    # sort: most recently modified first (mtime high -> low), ties broken by smaller file first -- per design doc
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
        print(f"[context][auto] skipped {skipped_for_budget} file(s) due to token budget "
              f"(use /add <path> to force-include a file you really need)")

    return result
'@

$folderTrustPath = Join-Path $AppDir "folder_trust.py"
$contextManagerPath = Join-Path $AppDir "context_manager.py"

Set-Content -Path $folderTrustPath -Value $folderTrustContent -Encoding UTF8
Write-Host "[ok] เขียน folder_trust.py แล้ว" -ForegroundColor Green

Set-Content -Path $contextManagerPath -Value $contextManagerContent -Encoding UTF8
Write-Host "[ok] เขียน context_manager.py แล้ว" -ForegroundColor Green

Write-Host ""
Write-Host "=== ตรวจสอบผลลัพธ์ ===" -ForegroundColor Cyan
Get-ChildItem $AppDir -Filter "*.py" | Select-Object Name, Length | Format-Table -AutoSize

$expected = @("folder_trust.py", "context_manager.py", "config_manager.py", "desktop_archive.py", "linear_connector.py", "todo_store.py", "web_search.py")
$present = (Get-ChildItem $AppDir -Filter "*.py").Name
$missing = $expected | Where-Object { $_ -notin $present }

if ($missing.Count -eq 0) {
    Write-Host "[ok] ครบทุกไฟล์ที่ local_coder.py ต้องการแล้ว! ลองรัน lca ใหม่ได้เลยครับ" -ForegroundColor Green
} else {
    Write-Host "[warn] ยังขาดไฟล์: $($missing -join ', ')" -ForegroundColor Yellow
}
