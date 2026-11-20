// Settings: key status, quota and usage, rate limits, account and logout.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type SettingsView } from "../api";
import { Button, Card, ErrorState, Skeleton } from "../components/ui";
import { errorDetail, errorTitle } from "./errors";
import { KeySetup } from "./KeySetup";

const fmt = (n: number) => n.toLocaleString("th-TH");

export function Settings({ onLogout, onAuthLost }: { onLogout: () => void; onAuthLost: () => void }) {
  const [view, setView] = useState<SettingsView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(() => {
    setError(null);
    api<SettingsView>("/api/settings").then(setView).catch((err: unknown) => {
      const e = err instanceof ApiError ? err : new ApiError("unknown", "โหลดไม่สำเร็จ", true);
      if (e.type === "auth") onAuthLost();
      setError(e);
    });
  }, [onAuthLost]);
  useEffect(load, [load]);

  if (error) return <ErrorState title={errorTitle(error)} detail={errorDetail(error)} action={{ label: "ลองใหม่", onClick: load }} />;
  if (!view) return <Card><Skeleton className="h-6 w-1/2" /></Card>;

  const pct = view.quota.limit ? Math.min(100, Math.round((view.quota.used / view.quota.limit) * 100)) : 0;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">ตั้งค่า</h1>
      <Card title="API key ของโมเดล">
        <KeySetup status={view.key} isAdmin={view.user.role === "admin"} onChange={(key) => setView({ ...view, key })} />
      </Card>
      <Card title="Quota และการใช้งานวันนี้">
        <p className="text-sm">
          ใช้ไป <span className="tabular">{fmt(view.quota.used)}</span> จาก <span className="tabular">{fmt(view.quota.limit)}</span> token
          (เหลือ <span className="tabular">{fmt(view.quota.remaining)}</span>)
        </p>
        <div role="progressbar" aria-label="การใช้ quota วันนี้" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
          className="mt-2 h-2 w-full overflow-hidden rounded-sm bg-surface-2">
          <div className={`h-full ${pct >= 90 ? "bg-bad" : pct >= 70 ? "bg-warn" : "bg-accent"}`} style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-1 text-xs text-muted">รีเซ็ตทุกวัน (เวลา UTC) · วันที่ {view.quota.day}</p>
      </Card>
      <Card title="Rate limit">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">ต่อผู้ใช้</dt><dd className="tabular">{view.rate_limit.user_per_min} ครั้ง/นาที (เหลือ {view.rate_limit.user_remaining})</dd>
          <dt className="text-muted">ต่อ IP</dt><dd className="tabular">{view.rate_limit.ip_per_min} ครั้ง/นาที</dd>
          <dt className="text-muted">ข้อความเข้า</dt><dd className="tabular">ไม่เกิน {fmt(view.limits.max_input_chars)} ตัวอักษร</dd>
          <dt className="text-muted">คำตอบ</dt><dd className="tabular">ไม่เกิน {fmt(view.limits.max_output_tokens)} token</dd>
        </dl>
      </Card>
      <Card title="บัญชี">
        <p className="mb-3 text-sm">{view.user.username} <span className="text-muted">({view.user.role === "admin" ? "ผู้ดูแลระบบ" : "ผู้ใช้"})</span></p>
        <Button variant="secondary" onClick={onLogout}>ออกจากระบบ</Button>
      </Card>
    </div>
  );
}
