"""Read-only admin API for the back-office: user list, user detail and dashboard stats.

Admin role is required on every route. Phase 1 returns account metadata and counts only:
prompts and model outputs are never returned here, even to an admin.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from . import auth, quota
from .errors import AppError

NOT_FOUND = "ไม่พบผู้ใช้นี้"
SORT_COLUMNS = {
    "created_at": "u.created_at",
    "username": "u.username",
    "run_count": "run_count",
    "last_run_at": "last_run_at",
}
RUNS_SINCE_24H = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 day')"
_USER_SELECT = """
SELECT u.id, u.username, u.role, u.created_at,
  (SELECT COUNT(*) FROM runs r WHERE r.user_id = u.id) AS run_count,
  (SELECT MAX(r.created_at) FROM runs r WHERE r.user_id = u.id) AS last_run_at,
  (SELECT GROUP_CONCAT(o.provider) FROM oauth_identities o WHERE o.user_id = u.id) AS providers
FROM users u
"""


def require_admin(request: Request) -> auth.User:
    """Resolve the session cookie. Anonymous callers get 401; signed-in non-admins get 403."""
    ctx = request.app.state.ctx
    user = auth.user_for_token(ctx.db, request.cookies.get(auth.SESSION_COOKIE))
    request.state.user_id = user.id
    if user.role != "admin":
        raise AppError("auth", "เฉพาะผู้ดูแลระบบเท่านั้นที่ทำรายการนี้ได้", http_status=403)
    return user


router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _user(row: Any) -> dict[str, Any]:
    providers = str(row["providers"] or "").split(",") if row["providers"] else []
    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "role": str(row["role"]),
        "created_at": str(row["created_at"]),
        "providers": sorted(p for p in providers if p),
        "run_count": int(row["run_count"]),
        "last_run_at": row["last_run_at"],
    }


@router.get("/stats")
def stats(request: Request) -> dict[str, Any]:
    """Headline numbers for the dashboard. Counts only; no user content."""
    db = request.app.state.ctx.db
    with db.session() as conn:
        users = conn.execute("SELECT COUNT(*) AS n, SUM(role = 'admin') AS admins FROM users").fetchone()
        linked = conn.execute("SELECT COUNT(DISTINCT user_id) AS n FROM oauth_identities").fetchone()
        by_status = conn.execute(
            f"SELECT status, COUNT(*) AS n FROM runs WHERE created_at >= {RUNS_SINCE_24H} GROUP BY status"  # noqa: S608
        ).fetchall()
        active = conn.execute(
            f"SELECT COUNT(DISTINCT user_id) AS n FROM runs WHERE created_at >= {RUNS_SINCE_24H}"  # noqa: S608
        ).fetchone()
    runs = {"ok": 0, "partial": 0, "error": 0}
    for row in by_status:
        runs[str(row["status"])] = int(row["n"])
    return {
        "users": {"total": int(users["n"]), "admins": int(users["admins"] or 0),
                  "with_sign_in_provider": int(linked["n"])},
        "runs_24h": runs,
        "active_users_24h": int(active["n"]),
        "window": quota.current_window(),
        "tokens_this_window": _tokens_in_window(db, quota.current_window()),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _tokens_in_window(db: Any, window: str) -> int:
    with db.session() as conn:
        row = conn.execute("SELECT COALESCE(SUM(tokens), 0) AS n FROM usage WHERE day = ?", (window,)).fetchone()
    return int(row["n"])


@router.get("/users")
def users(
    request: Request,
    q: str = Query("", max_length=64),
    role: str = Query("", pattern=r"^(|user|admin)$"),
    sort: str = Query("created_at", pattern=r"^(created_at|username|run_count|last_run_at)$"),
    order: str = Query("desc", pattern=r"^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """A page of accounts. Search matches the username; sort and order are whitelisted."""
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        clauses.append("u.username LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(q)}%")
    if role:
        clauses.append("u.role = ?")
        params.append(role)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    column = SORT_COLUMNS[sort]
    db = request.app.state.ctx.db
    with db.session() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM users u {where}", params).fetchone()  # noqa: S608
        rows = conn.execute(
            f"SELECT * FROM ({_USER_SELECT}) u {where} ORDER BY {column} {order.upper()}, u.id ASC LIMIT ? OFFSET ?",  # noqa: S608
            [*params, limit, offset],
        ).fetchall()
    return {"items": [_user(r) for r in rows], "total": int(total["n"]), "limit": limit, "offset": offset}


@router.get("/users/{user_id}")
def user_detail(user_id: int, request: Request) -> dict[str, Any]:
    """One account's metadata and current-window usage. Never the prompts or outputs of its runs."""
    db = request.app.state.ctx.db
    with db.session() as conn:
        row = conn.execute(f"{_USER_SELECT} WHERE u.id = ?", (user_id,)).fetchone()  # noqa: S608
    if row is None:
        raise AppError("validation", NOT_FOUND, http_status=404)
    return {
        "user": _user(row),
        "usage_this_window": {"window": quota.current_window(), "tokens": quota.used(db, user_id)},
    }
