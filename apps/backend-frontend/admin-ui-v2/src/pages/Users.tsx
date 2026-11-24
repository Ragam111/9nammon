import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, type AdminUser, type UserPage } from "../lib/api";
import { buildUsersQuery, formatBangkok, providerLabel, roleLabel, type UsersQuery } from "../lib/format";
import { go } from "../lib/router";
import { BevelButton, BlockLoader, type Column, SlotTable, StateScreen, StatusBadge } from "../components/pixel/primitives";

const PAGE = 20;
const SORTS = new Set(["created_at", "username", "run_count", "last_run_at"]);

function readQuery(search: URLSearchParams): UsersQuery {
  const sort = search.get("sort") ?? "";
  const role = search.get("role") ?? "";
  const offset = Math.max(0, Number(search.get("offset")) || 0);
  return {
    q: search.get("q") ?? "",
    role: role === "user" || role === "admin" ? role : "",
    sort: (SORTS.has(sort) ? sort : "created_at") as UsersQuery["sort"],
    order: search.get("order") === "asc" ? "asc" : "desc",
    offset,
    limit: PAGE,
  };
}

const COLUMNS: Column<AdminUser>[] = [
  {
    key: "username", label: "ชื่อผู้ใช้", sortKey: "username",
    render: (u) => <a href={`#/users/${u.id}`}>{u.username}</a>,
  },
  {
    key: "role", label: "สิทธิ์",
    render: (u) => <StatusBadge tone={u.role === "admin" ? "info" : "neutral"}>{roleLabel(u.role)}</StatusBadge>,
  },
  {
    key: "providers", label: "วิธีเข้าสู่ระบบ",
    render: (u) => (u.providers.length ? u.providers.map(providerLabel).join(", ") : "รหัสผ่าน"),
  },
  { key: "run_count", label: "จำนวนการรัน", sortKey: "run_count", render: (u) => u.run_count.toLocaleString("th-TH") },
  { key: "last_run_at", label: "รันล่าสุด", sortKey: "last_run_at", render: (u) => formatBangkok(u.last_run_at) },
  { key: "created_at", label: "สร้างเมื่อ", sortKey: "created_at", render: (u) => formatBangkok(u.created_at) },
];

export function Users({ search, onAuthLost }: { search: URLSearchParams; onAuthLost: () => void }) {
  const query = useMemo(() => readQuery(search), [search]);
  const [text, setText] = useState(query.q);
  const [page, setPage] = useState<UserPage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  // Typing is debounced into the URL so the list state is shareable and survives a reload.
  useEffect(() => {
    if (text.trim() === query.q) return;
    const timer = window.setTimeout(() => go(`#/users${buildUsersQuery({ ...query, q: text, offset: 0 })}`), 300);
    return () => window.clearTimeout(timer);
  }, [text, query]);

  const queryString = buildUsersQuery(query);
  const requestId = useRef(0); // only the newest request may write its result
  const load = useCallback(() => {
    const id = ++requestId.current;
    setError(null);
    api<UserPage>(`/api/admin/users${queryString}`)
      .then((res) => {
        if (id === requestId.current) setPage(res);
      })
      .catch((err: unknown) => {
        if (id !== requestId.current) return;
        const e = err instanceof ApiError ? err : new ApiError(0, "unknown", "โหลดรายชื่อไม่สำเร็จ", true);
        if (e.status === 401) onAuthLost();
        setError(e);
      });
  }, [queryString, onAuthLost]);
  useEffect(() => load(), [load]);

  const update = (patch: Partial<UsersQuery>) => go(`#/users${buildUsersQuery({ ...query, offset: 0, ...patch })}`);
  const sortBy = (key: string) => {
    const same = query.sort === key;
    update({ sort: key as UsersQuery["sort"], order: same && query.order === "desc" ? "asc" : "desc" });
  };

  const filtered = Boolean(query.q || query.role);
  const shownTotal = page?.total ?? 0;

  return (
    <div className="stack">
      <h1 className="h1">ผู้ใช้</h1>
      <search className="row">
        <label className="field" style={{ flex: "1 1 220px" }}>
          <span className="field__label">ค้นหาชื่อผู้ใช้</span>
          <input className="input" type="search" value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">สิทธิ์</span>
          <select className="select" value={query.role} onChange={(e) => update({ role: e.target.value as UsersQuery["role"] })}>
            <option value="">ทั้งหมด</option>
            <option value="user">ผู้ใช้</option>
            <option value="admin">ผู้ดูแลระบบ</option>
          </select>
        </label>
      </search>

      {error && (
        <StateScreen kind="error" title="โหลดรายชื่อไม่สำเร็จ" detail={error.message}
          action={error.retryable ? <BevelButton variant="secondary" onClick={load}>ลองอีกครั้ง</BevelButton> : undefined} />
      )}
      {!error && !page && <BlockLoader label="กำลังโหลดรายชื่อ" />}
      {!error && page && page.total === 0 && !filtered && (
        <StateScreen kind="empty" title="ยังไม่มีข้อมูล" detail="ยังไม่มีผู้ใช้ในระบบ" />
      )}
      {!error && page && page.total === 0 && filtered && (
        <StateScreen kind="empty" title="ไม่พบผู้ใช้ที่ตรงกับตัวกรอง" detail="ลองเปลี่ยนคำค้นหาหรือสิทธิ์"
          action={<BevelButton variant="secondary" onClick={() => go("#/users")}>ล้างตัวกรอง</BevelButton>} />
      )}
      {!error && page && page.total > 0 && (
        <>
          <SlotTable caption="รายชื่อผู้ใช้" columns={COLUMNS} rows={page.items}
            sortKey={query.sort} order={query.order} onSort={sortBy} />
          <nav className="pager" aria-label="เปลี่ยนหน้า">
            <span className="muted">
              {query.offset + 1}–{Math.min(query.offset + PAGE, shownTotal)} จาก {shownTotal.toLocaleString("th-TH")}
            </span>
            <div className="row">
              <BevelButton variant="secondary" disabled={query.offset === 0}
                onClick={() => update({ offset: Math.max(0, query.offset - PAGE) })}>ก่อนหน้า</BevelButton>
              <BevelButton variant="secondary" disabled={query.offset + PAGE >= shownTotal}
                onClick={() => update({ offset: query.offset + PAGE })}>ถัดไป</BevelButton>
            </div>
          </nav>
        </>
      )}
    </div>
  );
}
