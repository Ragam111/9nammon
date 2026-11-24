import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, type UserDetail as Detail } from "../lib/api";
import { formatBangkok, providerLabel, roleLabel } from "../lib/format";
import { BevelButton, BlockLoader, StateScreen, StatusBadge } from "../components/pixel/primitives";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <span className="field__label">{label}</span>
      <span>{children}</span>
    </div>
  );
}

export function UserDetail({ id, onAuthLost }: { id: number; onAuthLost: () => void }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const requestId = useRef(0); // only the newest request may write its result

  const load = useCallback(() => {
    const current = ++requestId.current;
    setError(null);
    setDetail(null);
    api<Detail>(`/api/admin/users/${id}`)
      .then((res) => {
        if (current === requestId.current) setDetail(res);
      })
      .catch((err: unknown) => {
        if (current !== requestId.current) return;
        const e = err instanceof ApiError ? err : new ApiError(0, "unknown", "โหลดข้อมูลผู้ใช้ไม่สำเร็จ", true);
        if (e.status === 401) onAuthLost();
        setError(e);
      });
  }, [id, onAuthLost]);
  useEffect(() => load(), [load]);

  if (error?.status === 404) {
    return <StateScreen kind="notfound" title="ไม่พบผู้ใช้นี้" detail="อาจถูกลบไปแล้ว"
      action={<a href="#/users" className="btn btn--secondary">กลับไปรายชื่อผู้ใช้</a>} />;
  }
  if (error) {
    return <StateScreen kind="error" title="โหลดข้อมูลผู้ใช้ไม่สำเร็จ" detail={error.message}
      action={error.retryable ? <BevelButton variant="secondary" onClick={load}>ลองอีกครั้ง</BevelButton> : undefined} />;
  }
  if (!detail) return <BlockLoader label="กำลังโหลดข้อมูลผู้ใช้" />;

  const u = detail.user;
  return (
    <div className="stack">
      <a href="#/users" style={{ width: "fit-content" }}>← กลับไปรายชื่อผู้ใช้</a>
      <h1 className="h1">{u.username}</h1>
      <section className="frame stack" aria-label="ข้อมูลบัญชี">
        <div className="row">
          <StatusBadge tone={u.role === "admin" ? "info" : "neutral"}>{roleLabel(u.role)}</StatusBadge>
        </div>
        <Field label="วิธีเข้าสู่ระบบ">
          {u.providers.length ? u.providers.map(providerLabel).join(", ") : "รหัสผ่าน"}
        </Field>
        <Field label="สร้างเมื่อ">{formatBangkok(u.created_at)}</Field>
        <Field label="จำนวนการรัน">{u.run_count.toLocaleString("th-TH")}</Field>
        <Field label="รันล่าสุด">{formatBangkok(u.last_run_at)}</Field>
        <Field label={`โทเคนรอบ ${detail.usage_this_window.window}`}>
          {detail.usage_this_window.tokens.toLocaleString("th-TH")}
        </Field>
        <p className="muted" style={{ fontSize: "var(--text-sm)", margin: 0 }}>
          หน้านี้แสดงข้อมูลบัญชีและตัวเลขเท่านั้น ไม่แสดงข้อความหรือคำตอบของผู้ใช้
        </p>
      </section>
    </div>
  );
}
