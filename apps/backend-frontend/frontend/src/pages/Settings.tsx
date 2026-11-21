// Settings: key status, quota and usage, rate limits, account and logout.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type SettingsView } from "../api";
import { Card, ErrorState, Skeleton } from "../components/ui";
import { errorDetail, errorTitle } from "./errors";
import { AccountCard } from "./AccountCard";
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

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">ตั้งค่า</h1>
      <Card title="API key ของโมเดล">
        <KeySetup status={view.key} isAdmin={view.user.role === "admin"} onChange={(key) => setView({ ...view, key })} />
      </Card>
      <Card title="การใช้งานและโควตา">
        <div className="flex flex-col gap-5">
          {view.quota.buckets.map((b) => <QuotaMeter key={b.name} bucket={b} />)}
        </div>
      </Card>
      <Card title="Rate limit">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">ต่อผู้ใช้</dt><dd className="tabular">{view.rate_limit.user_per_min} ครั้ง/นาที (เหลือ {view.rate_limit.user_remaining})</dd>
          <dt className="text-muted">ต่อ IP</dt><dd className="tabular">{view.rate_limit.ip_per_min} ครั้ง/นาที</dd>
          <dt className="text-muted">ข้อความเข้า</dt><dd className="tabular">ไม่เกิน {fmt(view.limits.max_input_chars)} ตัวอักษร</dd>
          <dt className="text-muted">คำตอบ</dt><dd className="tabular">ไม่เกิน {fmt(view.limits.max_output_tokens)} token</dd>
        </dl>
      </Card>
      <AccountCard onLogout={onLogout} onAuthLost={onAuthLost} />
    </div>
  );
}

const BUCKET_LABEL: Record<string, string> = {
  five_hour: "ทุกโมเดล · 5 ชั่วโมง",
  weekly: "ทุกโมเดล · รายสัปดาห์",
  heavy_weekly: "โมเดลหนัก · รายสัปดาห์",
};

function QuotaMeter({ bucket }: { bucket: SettingsView["quota"]["buckets"][number] }) {
  const label = BUCKET_LABEL[bucket.name] ?? bucket.name;
  const pct = bucket.limit ? Math.min(100, Math.round((bucket.used / bucket.limit) * 100)) : 0;
  return (
    <div>
      <p className="text-sm">
        {label} · ใช้ไป <span className="tabular">{pct}%</span> (<span className="tabular">{fmt(bucket.used)}</span> / <span className="tabular">{fmt(bucket.limit)}</span> token)
      </p>
      <div role="progressbar" aria-label={`การใช้ ${label}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
        className="mt-2 h-2 w-full overflow-hidden rounded-sm bg-surface-2">
        <div className={`h-full ${pct >= 90 ? "bg-bad" : pct >= 70 ? "bg-warn" : "bg-accent"}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-muted">
        รีเซ็ต {new Date(bucket.resets_at).toLocaleString("th-TH", { timeZone: "Asia/Bangkok", weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} (เวลาไทย)
      </p>
    </div>
  );
}
