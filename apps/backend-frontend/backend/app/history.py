"""Run history. Every query is scoped to the owner, so one user can never read another's runs."""

from __future__ import annotations

import secrets
from typing import Any

from .db import Database

STATUSES = ("ok", "partial", "error")
_LIST_FIELDS = (
    "id, model, substr(prompt, 1, 160) AS prompt_preview, status, error_type, "
    "tokens_in, tokens_out, latency_ms, created_at"
)


def start(db: Database, user_id: int, model: str, prompt: str) -> str:
    """Insert a run that starts as 'error' until finish() records the real outcome."""
    run_id = "run_" + secrets.token_hex(6)
    with db.session() as conn:
        conn.execute(
            "INSERT INTO runs (id, user_id, model, prompt, status) VALUES (?, ?, ?, ?, 'error')",
            (run_id, user_id, model, prompt),
        )
    return run_id


def finish(db: Database, run_id: str, *, status: str, output: str, error_type: str | None,
           tokens_in: int, tokens_out: int, latency_ms: int) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE runs SET status = ?, output = ?, error_type = ?, tokens_in = ?, tokens_out = ?, latency_ms = ? "
            "WHERE id = ?",
            (status, output, error_type, tokens_in, tokens_out, latency_ms, run_id),
        )


def list_runs(
    db: Database, user_id: int, *, q: str = "", status: str = "", limit: int = 20, offset: int = 0
) -> dict[str, Any]:
    """Search prompt/output text, filter by status, newest first. Returns items and the total."""
    where, args = ["user_id = ?"], [user_id]
    if q:
        where.append("(prompt LIKE ? ESCAPE '\\' OR output LIKE ? ESCAPE '\\')")
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args += [pattern, pattern]
    if status in STATUSES:
        where.append("status = ?")
        args.append(status)
    # `clause` joins only the fixed strings above; every user value goes through `args` as a bound parameter.
    clause = " AND ".join(where)
    count_sql = f"SELECT COUNT(*) FROM runs WHERE {clause}"  # noqa: S608
    page_sql = f"SELECT {_LIST_FIELDS} FROM runs WHERE {clause} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"  # noqa: S608, E501
    with db.session() as conn:
        total = conn.execute(count_sql, args).fetchone()[0]
        rows = conn.execute(page_sql, [*args, limit, offset]).fetchall()
    return {"items": [dict(r) for r in rows], "total": int(total)}


def get(db: Database, user_id: int, run_id: str) -> dict[str, Any] | None:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ? AND user_id = ?", (run_id, user_id)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data.pop("user_id", None)
    return data


def delete(db: Database, user_id: int, run_id: str) -> bool:
    with db.session() as conn:
        cur = conn.execute("DELETE FROM runs WHERE id = ? AND user_id = ?", (run_id, user_id))
    return cur.rowcount > 0
