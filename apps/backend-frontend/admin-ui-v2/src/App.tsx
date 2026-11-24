// Back-office shell: session check (admin role only), navigation, theme switch and the three pages.
import { useCallback, useEffect, useState } from "react";
import { api, type Me } from "./lib/api";
import { go, useRoute } from "./lib/router";
import { BevelButton, BlockLoader, StateScreen } from "./components/pixel/primitives";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { UserDetail } from "./pages/UserDetail";
import { Users } from "./pages/Users";

type Theme = "dark" | "light";
const THEME_KEY = "bf-admin-theme";

function readTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark"; // storage blocked: the default still applies
  }
}

type Session = { state: "loading" } | { state: "anonymous" } | { state: "forbidden"; username: string } | { state: "admin"; username: string };

export function App() {
  const route = useRoute();
  const [session, setSession] = useState<Session>({ state: "loading" });
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage blocked: the theme still applies for this page */
    }
  }, [theme]);

  useEffect(() => {
    api<Me>("/api/auth/me")
      .then((res) => setSession(sessionFrom(res.user)))
      .catch(() => setSession({ state: "anonymous" })); // 401, or the server is unreachable: ask to sign in
  }, []);

  const signedIn = useCallback((user: Me["user"]) => setSession(sessionFrom(user)), []);
  const signOut = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setSession({ state: "anonymous" });
    go("#/");
  }, []);
  const authLost = useCallback(() => setSession({ state: "anonymous" }), []);

  if (session.state === "loading") return <main className="shell__main"><BlockLoader label="กำลังตรวจสอบการเข้าสู่ระบบ" /></main>;
  if (session.state === "anonymous") return <Login onSignedIn={signedIn} />;
  if (session.state === "forbidden") {
    return (
      <main className="shell__main">
        <StateScreen kind="forbidden" title="ไม่มีสิทธิ์เข้าหน้านี้" detail="หน้านี้สำหรับผู้ดูแลระบบเท่านั้น"
          action={<BevelButton variant="secondary" onClick={() => void signOut()}>ออกจากระบบ</BevelButton>} />
      </main>
    );
  }

  return (
    <div className="shell">
      <header className="shell__header">
        <a href="#/" className="shell__brand" style={{ textDecoration: "none" }}>BACK-OFFICE</a>
        <nav aria-label="เมนูหลัก" className="shell__nav">
          <a href="#/" className="btn btn--ghost btn--nav" aria-current={route.name === "dashboard" ? "page" : undefined}>แดชบอร์ด</a>
          <a href="#/users" className="btn btn--ghost btn--nav"
            aria-current={route.name === "users" || route.name === "user" ? "page" : undefined}>ผู้ใช้</a>
        </nav>
        <div className="shell__spacer row">
          <label className="field">
            <span className="visually-hidden">ธีม</span>
            <select className="select" value={theme} onChange={(e) => setTheme(e.target.value as Theme)} aria-label="ธีม">
              <option value="dark">มืด</option>
              <option value="light">สว่าง</option>
            </select>
          </label>
          <span className="muted">{session.username}</span>
          <BevelButton variant="secondary" onClick={() => void signOut()}>ออกจากระบบ</BevelButton>
        </div>
      </header>
      <main className="shell__main" id="main">
        {route.name === "dashboard" && <Dashboard onAuthLost={authLost} />}
        {route.name === "users" && <Users search={route.search} onAuthLost={authLost} />}
        {route.name === "user" && <UserDetail id={route.id} onAuthLost={authLost} />}
        {route.name === "unknown" && (
          <StateScreen kind="notfound" title="ไม่พบหน้านี้" detail="ลองเลือกเมนูด้านบน"
            action={<a href="#/" className="btn btn--secondary">กลับไปแดชบอร์ด</a>} />
        )}
      </main>
    </div>
  );
}

function sessionFrom(user: Me["user"]): Session {
  return user.role === "admin" ? { state: "admin", username: user.username } : { state: "forbidden", username: user.username };
}
