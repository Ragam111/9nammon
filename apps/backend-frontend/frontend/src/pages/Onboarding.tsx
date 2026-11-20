import { useEffect, useState } from "react";
import { ApiError, api, type Health, type KeyStatus, type User } from "../api";
import { Button, Card, ErrorState, Skeleton } from "../components/ui";
import { navigate } from "../router";
import { KeySetup } from "./KeySetup";

export function Onboarding({ user }: { user: User }) {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = () => {
    setError(null);
    Promise.all([api<KeyStatus>("/api/settings/key"), api<Health>("/api/health")])
      .then(([k, h]) => { setStatus(k); setHealth(h); })
      .catch((err: unknown) => setError(err instanceof ApiError ? err : new ApiError("unknown", "โหลดไม่สำเร็จ", true)));
  };
  useEffect(load, []);

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">เริ่มต้นใช้งาน</h1>
      <p className="text-sm text-muted">ขั้นแรก ตั้งค่า API key ของโมเดล key จะเก็บที่ server เท่านั้น</p>
      {error && <ErrorState title="โหลดสถานะไม่สำเร็จ" detail={error.message} action={{ label: "ลองใหม่", onClick: load }} />}
      {!status && !error && <Card><Skeleton className="h-6 w-1/2" /></Card>}
      {status && (
        <Card title={`API key สำหรับ ${health?.model ?? "โมเดล"}`}>
          <KeySetup status={status} isAdmin={user.role === "admin"} onChange={setStatus} />
        </Card>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={!status?.configured} onClick={() => navigate("workbench")}>ไปหน้าทำงาน</Button>
        <Button variant="ghost" onClick={() => navigate("workbench")}>ข้าม (โมเดลในเครื่องไม่ต้องใช้ key)</Button>
      </div>
    </div>
  );
}
