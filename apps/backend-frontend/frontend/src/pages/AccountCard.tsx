// Account card: sign-in methods (link or unlink a provider), switch account, and permanent delete.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, json } from "../api";
import { Button, Card, ErrorState, Input } from "../components/ui";
import { errorDetail, errorTitle } from "./errors";

type Account = {
  username: string;
  role: string;
  password: boolean;
  providers: string[];
  available_providers: string[];
};

const PROVIDER_LABEL: Record<string, string> = { google: "Google", github: "GitHub" };

/** Notice shown after returning from a link attempt, read from the hash (e.g. #/settings?linked=github). */
function linkNotice(): string {
  const hash = window.location.hash;
  const match = /linked=(google|github)/.exec(hash);
  if (match) return `ผูกกับ ${PROVIDER_LABEL[match[1]]} แล้ว`;
  if (!hash.includes("link=error")) return "";
  const msg = new URLSearchParams(hash.split("?")[1] ?? "").get("msg");
  return msg ? `ผูกไม่สำเร็จ: ${msg}` : "ผูกบัญชีไม่สำเร็จ ลองใหม่อีกครั้ง";
}

export function AccountCard({ onLogout, onAuthLost }: { onLogout: () => void; onAuthLost: () => void }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [notice] = useState(linkNotice);

  const load = useCallback(() => {
    api<Account>("/api/account")
      .then(setAccount)
      .catch((err: unknown) => {
        const e = err instanceof ApiError ? err : new ApiError("unknown", "โหลดข้อมูลบัญชีไม่สำเร็จ", true);
        if (e.type === "auth") onAuthLost();
        setError(e);
      });
  }, [onAuthLost]);
  useEffect(load, [load]);

  const unlink = async (provider: string) => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/account/unlink/${provider}`, json("POST"));
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("unknown", "ถอดการผูกไม่สำเร็จ", false));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!account) return;
    setBusy(true);
    setError(null);
    try {
      await api("/api/account", json("DELETE", { confirm }));
      onLogout();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("unknown", "ลบบัญชีไม่สำเร็จ", false));
    } finally {
      setBusy(false);
    }
  };

  if (error && !account) return <ErrorState title={errorTitle(error)} detail={errorDetail(error)} />;
  if (!account) return <Card title="บัญชี"><p className="text-sm text-muted">กำลังโหลด…</p></Card>;

  return (
    <Card title="บัญชี">
      <div className="flex flex-col gap-5">
        <p className="text-sm">
          {account.username} <span className="text-muted">({account.role === "admin" ? "ผู้ดูแลระบบ" : "ผู้ใช้"})</span>
        </p>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">วิธีเข้าสู่ระบบ</h3>
          <p className="text-xs text-muted">{account.password ? "มีรหัสผ่านสำหรับเข้าสู่ระบบ" : "ไม่มีรหัสผ่าน เข้าสู่ระบบด้วยผู้ให้บริการเท่านั้น"}</p>
          {account.available_providers.length === 0 && <p className="text-sm text-muted">ยังไม่ได้เปิดใช้การเข้าสู่ระบบด้วยผู้ให้บริการ</p>}
          {account.available_providers.map((p) => {
            const linked = account.providers.includes(p);
            return (
              <div key={p} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>{PROVIDER_LABEL[p] ?? p} · {linked ? "ผูกแล้ว" : "ยังไม่ได้ผูก"}</span>
                {linked ? (
                  <Button variant="secondary" loading={busy} onClick={() => void unlink(p)}>ถอดการผูก</Button>
                ) : (
                  <a href={`/api/auth/oauth/${p}/start?link=1`}
                    className="inline-flex min-h-10 items-center rounded-sm border border-line bg-surface px-3 text-sm text-fg no-underline hover:bg-surface-2">
                    ผูกกับ {PROVIDER_LABEL[p] ?? p}
                  </a>
                )}
              </div>
            );
          })}
          {notice && <p className="text-sm text-accent" role="status">{notice}</p>}
        </section>

        <div>
          <Button variant="secondary" onClick={onLogout}>ออกจากระบบ / เปลี่ยนบัญชี</Button>
        </div>

        {error && <ErrorState title={errorTitle(error)} detail={errorDetail(error)} />}

        <section className="flex flex-col gap-2 border-t border-line pt-4">
          <h3 className="text-sm font-semibold text-bad">ลบบัญชีถาวร</h3>
          <p className="text-xs text-muted">
            ประวัติการแชท การใช้โควตา และการผูกบัญชีจะถูกลบและกู้คืนไม่ได้ พิมพ์ <span className="mono">{account.username}</span> เพื่อยืนยัน
          </p>
          <Input label="ยืนยันด้วยชื่อผู้ใช้" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
          <div>
            <Button variant="danger" loading={busy} disabled={confirm !== account.username} onClick={() => void remove()}>
              ลบบัญชีนี้
            </Button>
          </div>
        </section>
      </div>
    </Card>
  );
}
