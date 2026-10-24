"""CLI: เรียก agent สายเทค จากเทอร์มินัล

  python -m app.agent list                         # ดู persona ทั้งหมด
  python -m app.agent ask elon "ควรรีไรต์ด้วย Rust ไหม"
  python -m app.agent council "ควรรีไรต์ด้วย Rust ไหม"      # ประชุมสภาหลายมุม
  python -m app.agent council "..." --personas elon,jobs,carmack --model qwen2.5:0.5b

ต้องมี Ollama (หรือ backend ที่ตั้งใน config) + โมเดลที่เลือก (default qwen2.5:0.5b)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app import model_backend  # noqa: E402
from app.agent import core, harness, personas  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.agent", description="AI agent สายเทค (หลาย persona + harness)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="ดู persona ทั้งหมด")
    a = sub.add_parser("ask", help="ถาม persona เดียว")
    a.add_argument("persona"); a.add_argument("task")
    a.add_argument("--model", default=harness.DEFAULT_MODEL)
    c = sub.add_parser("council", help="ประชุมสภาหลายมุม")
    c.add_argument("task")
    c.add_argument("--personas", default="", help="คั่นด้วย comma (ว่าง=ชุดเริ่มต้น)")
    c.add_argument("--chair", default=None)
    c.add_argument("--model", default=harness.DEFAULT_MODEL)
    r = sub.add_parser("run", help="agent ลงมือทำงานจริงด้วย tools (ใน sandbox)")
    r.add_argument("task")
    r.add_argument("--workspace", default=".", help="โฟลเดอร์ที่ agent ทำงานได้ (default: ปัจจุบัน)")
    r.add_argument("--max-steps", type=int, default=core.DEFAULT_MAX_STEPS)
    r.add_argument("--model", default=core.DEFAULT_MODEL)
    args = ap.parse_args(argv)

    root = Path.cwd()
    if args.cmd == "list":
        for p in personas.list_personas():
            print(f"  {p['id']:10} {p['name']:14} — {p['title']}")
            print(f"             skills: {', '.join(p['skills'])}")
        return 0
    try:
        if args.cmd == "ask":
            res = harness.ask(root, args.persona, args.task, model=args.model)
            print(f"=== {res['name']} ({res['persona']}) ===\n{res['reply']}")
        elif args.cmd == "council":
            ids = [x.strip() for x in args.personas.split(",") if x.strip()] or None
            res = harness.council(root, args.task, personas_ids=ids, model=args.model, chair=args.chair)
            for o in res["opinions"]:
                print(f"--- {o['name']} ---\n{o['reply']}\n")
            print(f"=== ข้อสรุป (ประธาน: {res['chair']}) ===\n{res['synthesis']}")
        elif args.cmd == "run":
            res = core.run(root, args.task, workspace=args.workspace,
                           model=args.model, max_steps=args.max_steps)
            for i, s in enumerate(res["steps"], 1):
                if "final" in s:
                    continue
                if "error" in s:
                    print(f"[{i}] (parse error) ลองใหม่")
                else:
                    print(f"[{i}] {s.get('thought','')} → {s['tool']}({s['args']})\n    {s['observation'][:200]}")
            print(f"\n=== ผลสรุป ({res['stopped_reason']}) ===\n{res['final'] or '(ไม่จบใน max_steps)'}")
    except ValueError as e:
        print(f"[error] {e}"); return 2
    except model_backend.BackendError as e:
        print(f"[backend error] {e} — ต่อ LLM ไม่ได้ (เช็ค Ollama/โมเดล {args.model})"); return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
