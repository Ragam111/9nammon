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
from app.agent import core, harness, personas, worker as worker_mod  # noqa: E402


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
    w = sub.add_parser("worker", help="รัน agent 24/7 หยิบงานจากไฟล์คิว (1 task ต่อบรรทัด)")
    w.add_argument("--queue", default="agent_queue.txt", help="ไฟล์คิว: 1 บรรทัด = 1 โจทย์ (ลบบรรทัดเมื่อทำเสร็จ)")
    w.add_argument("--workspace", default=".")
    w.add_argument("--model", default=core.DEFAULT_MODEL)
    w.add_argument("--interval", type=float, default=5.0)
    w.add_argument("--once", action="store_true", help="ทำงานในคิวให้หมดแล้วออก (ไม่วน 24/7)")
    w.add_argument("--store", action="store_true",
                   help="หยิบงานจาก job queue (agent_jobs.json) ที่ n8n/API ป้อนเข้า แทนไฟล์ข้อความ")
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
        elif args.cmd == "worker":
            import time
            if args.store:
                # โหมด store: n8n/API enqueue เข้า agent_jobs.json แล้ว worker หยิบ+บันทึกผลกลับ
                from app.agent import jobs as _jobs
                _claimed = {"id": None}
                def claim():
                    job = _jobs.claim(root)
                    if job:
                        _claimed["id"] = job["id"]
                        return {"task": job["task"], "workspace": job.get("workspace", ".")}
                    return None
                def done(rec):
                    if _claimed["id"]:
                        _jobs.complete(root, _claimed["id"], rec)
                    print(f"[{'ok' if rec['ok'] else 'fail'}] {rec['duration_s']}s — {rec['task'][:60]}")
                wk = worker_mod.Worker(claim_fn=claim, done_fn=done, project_root=root,
                                       model=args.model, interval=args.interval)
                if args.once:
                    while wk.tick() is not None:
                        pass
                else:
                    print(f"[worker] 24/7 (store) เริ่มทำงาน — คิว: agent_jobs.json (Ctrl+C หยุด)")
                    wk.start()
                    try:
                        while True:
                            time.sleep(30); print(f"[stats] {wk.stats.summary()}")
                    except KeyboardInterrupt:
                        wk.stop(); print("\n[worker] หยุดแล้ว")
                print(f"=== สรุปผล ===\n{wk.stats.summary()}")
                return 0
            qpath = Path(args.queue)
            def claim():
                # หยิบบรรทัดแรกของไฟล์คิวมาเป็นงาน แล้วลบออก (atomic พอสำหรับ worker เดียว)
                try:
                    lines = qpath.read_text(encoding="utf-8").splitlines()
                except OSError:
                    return None
                tasks = [l.strip() for l in lines if l.strip()]
                if not tasks:
                    return None
                qpath.write_text("\n".join(tasks[1:]) + ("\n" if tasks[1:] else ""), encoding="utf-8")
                return {"task": tasks[0], "workspace": args.workspace}
            def done(rec):
                print(f"[{'ok' if rec['ok'] else 'fail'}] {rec['duration_s']}s {rec['steps']} step — {rec['task'][:60]}")
            wk = worker_mod.Worker(claim_fn=claim, done_fn=done, project_root=root,
                                   model=args.model, interval=args.interval)
            if args.once:
                while wk.tick() is not None:
                    pass
            else:
                print(f"[worker] 24/7 เริ่มทำงาน — คิว: {args.queue} (Ctrl+C เพื่อหยุด)")
                wk.start()
                try:
                    while True:
                        time.sleep(30)
                        print(f"[stats] {wk.stats.summary()}")
                except KeyboardInterrupt:
                    wk.stop(); print("\n[worker] หยุดแล้ว")
            print(f"=== สรุปผล ===\n{wk.stats.summary()}")
    except ValueError as e:
        print(f"[error] {e}"); return 2
    except model_backend.BackendError as e:
        print(f"[backend error] {e} — ต่อ LLM ไม่ได้ (เช็ค Ollama/โมเดล {args.model})"); return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
