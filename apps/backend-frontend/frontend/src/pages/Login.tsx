import { useState, type FormEvent } from "react";
import { ApiError, api, json, type User } from "../api";
import { Button, Card, ErrorState, Input } from "../components/ui";

export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

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
