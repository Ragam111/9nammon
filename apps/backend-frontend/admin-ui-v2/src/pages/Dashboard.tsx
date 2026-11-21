import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type Stats } from "../lib/api";
import { formatBangkok } from "../lib/format";
import { BevelButton, BlockLoader, StateScreen, StatusBadge } from "../components/pixel/primitives";

function Kpi({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <section className="frame" aria-label={label}>
      <p className="kpi__label">{label}</p>
      <p className="kpi__value">{value}</p>
      {note && <p className="muted" style={{ fontSize: "var(--text-xs)", margin: 0 }}>{note}</p>}
    </section>
  );
}

export function Dashboard({ onAuthLost }: { onAuthLost: () => void }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(() => {
    setError(null);
    api<Stats>("/api/admin/stats")
      .then(setStats)
      .catch((err: unknown) => {
        const e = err instanceof ApiError ? err : new ApiError(0, "unknown", "โหลดสถิติไม่สำเร็จ", true);
        if (e.status === 401) onAuthLost();
        setError(e);
      });
  }, [onAuthLost]);

  useEffect(load, [load]);

  if (error) {
    return (
      <StateScreen kind="error" title="โหลดแดชบอร์ดไม่สำเร็จ" detail={error.message}
        action={error.retryable ? <BevelButton variant="secondary" onClick={load}>ลองอีกครั้ง</BevelButton> : undefined} />
    );
  }
  if (!stats) return <BlockLoader label="กำลังโหลดแดชบอร์ด" />;

  return (
    <div className="stack">
      <h1 className="h1">แดชบอร์ด</h1>
      <div className="kpis">
        <Kpi label="ผู้ใช้ทั้งหมด" value={stats.users.total} note={`ผู้ดูแลระบบ ${stats.users.admins} คน`} />
        <Kpi label="ผู้ใช้งาน 24 ชม." value={stats.active_users_24h} />
        <Kpi label="ผูกผู้ให้บริการภายนอก" value={stats.users.with_sign_in_provider} note="Google หรือ GitHub" />
        <Kpi label="โทเคนรอบนี้" value={stats.tokens_this_window.toLocaleString("th-TH")} note={`รอบ ${stats.window}`} />
      </div>
      <section className="frame stack" aria-label="การรันใน 24 ชั่วโมง">
        <h2 className="h2">การรันใน 24 ชั่วโมง</h2>
        <div className="row">
          <StatusBadge tone="ok">สำเร็จ {stats.runs_24h.ok}</StatusBadge>
          <StatusBadge tone="warn">บางส่วน {stats.runs_24h.partial}</StatusBadge>
          <StatusBadge tone="bad">ล้มเหลว {stats.runs_24h.error}</StatusBadge>
        </div>
        <p className="muted" style={{ fontSize: "var(--text-xs)", margin: 0 }}>
          อัปเดตเมื่อ {formatBangkok(stats.generated_at)}
        </p>
        <div className="row">
          <BevelButton variant="ghost" onClick={load}>รีเฟรช</BevelButton>
        </div>
      </section>
    </div>
  );
}
