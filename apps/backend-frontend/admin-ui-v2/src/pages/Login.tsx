import { type FormEvent, useState } from "react";
import { ApiError, api, jsonBody, type Me } from "../lib/api";
import { BevelButton } from "../components/pixel/primitives";

export function Login({ onSignedIn }: { onSignedIn: (me: Me["user"]) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<Me>("/api/auth/login", jsonBody("POST", { username, password }));
      onSignedIn(res.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "เข้าสู่ระบบไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="shell__main" style={{ maxWidth: 420, marginTop: "10vh" }}>
      <section className="frame stack">
        <h1 className="h1">เข้าสู่ระบบหลังบ้าน</h1>
        <form onSubmit={submit} className="stack" noValidate>
          <label className="field">
            <span className="field__label">ชื่อผู้ใช้</span>
            <input className="input" name="username" autoComplete="username" value={username}
              onChange={(e) => setUsername(e.target.value)} required />
          </label>
          <label className="field">
            <span className="field__label">รหัสผ่าน</span>
            <input className="input" type="password" name="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {error && <p role="alert" className="badge badge--bad" style={{ width: "fit-content" }}>{error}</p>}
          <BevelButton type="submit" variant="primary" loading={busy} disabled={!username || !password}>
            เข้าสู่ระบบ
          </BevelButton>
        </form>
        <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
          หน้านี้ใช้บัญชีเดียวกับแอปหลัก และต้องเป็นผู้ดูแลระบบ
        </p>
      </section>
    </main>
  );
}
