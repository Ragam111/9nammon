import { useEffect, useState, type FormEvent } from "react";
import { ApiError, api, json, type User } from "../api";
import { Button, Card, ErrorState, Input } from "../components/ui";

const PROVIDER_LABEL: Record<string, string> = { google: "Google", github: "GitHub" };

export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [providers, setProviders] = useState<string[]>([]);
  const oauthFailed = window.location.hash.includes("error=oauth");
  const sessionMissing = window.location.hash.includes("error=session");

  useEffect(() => {
    api<{ providers: string[] }>("/api/auth/oauth/providers").then((r) => setProviders(r.providers)).catch(() => undefined);
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ user: User }>("/api/auth/login", json("POST", { username, password }));
      onLogin(res.user);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("unknown", "เข้าสู่ระบบไม่สำเร็จ", false));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-4 p-4">
      <h1 className="text-2xl font-semibold">เข้าสู่ระบบ</h1>
      {providers.length > 0 && (
        <Card>
          <div className="flex flex-col gap-2">
            {providers.map((p) => (
              <a key={p} href={`/api/auth/oauth/${p}/start`}
                className="inline-flex min-h-10 items-center justify-center rounded-sm border border-line bg-surface px-4 text-sm font-medium text-fg no-underline hover:bg-surface-2">
                เข้าสู่ระบบด้วย {PROVIDER_LABEL[p] ?? p}
              </a>
            ))}
          </div>
        </Card>
      )}
      {oauthFailed && <ErrorState title="เข้าสู่ระบบด้วยผู้ให้บริการไม่สำเร็จ" detail="ลองอีกครั้ง หรือใช้ชื่อผู้ใช้และรหัสผ่าน" />}
      {sessionMissing && <ErrorState title="ต้องเข้าสู่ระบบก่อนผูกบัญชี" detail="เข้าสู่ระบบแล้วกลับไปที่หน้าตั้งค่าเพื่อผูกวิธีอื่น" />}
      <Card>
        <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
          <Input label="ชื่อผู้ใช้" autoComplete="username" value={username} required
            onChange={(e) => setUsername(e.target.value)} />
          <Input label="รหัสผ่าน" type="password" autoComplete="current-password" value={password} required
            onChange={(e) => setPassword(e.target.value)} />
          <Button type="submit" variant="primary" loading={busy} disabled={!username || !password}>เข้าสู่ระบบ</Button>
        </form>
      </Card>
      {error && <ErrorState title="เข้าสู่ระบบไม่สำเร็จ" detail={error.message} />}
    </main>
  );
}
