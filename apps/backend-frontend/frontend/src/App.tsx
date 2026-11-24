// App shell: session check, header navigation, theme switch, and the five flows.
import { useCallback, useEffect, useState } from "react";
import { api, json, type KeyStatus, type User } from "./api";
import { Select, Skeleton, ToastProvider } from "./components/ui";
import { Chat } from "./pages/Chat";
import { History } from "./pages/History";
import { Login } from "./pages/Login";
import { Onboarding } from "./pages/Onboarding";
import { Settings } from "./pages/Settings";
import { Workbench } from "./pages/Workbench";
import { hrefFor, navigate, useRoute, type Route } from "./router";
import { Showcase } from "./Showcase";

type Theme = "system" | "light" | "dark";
const THEME_KEY = "bf-theme";

function readTheme(): Theme {
  try {
    const t = window.localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

function applyTheme(theme: Theme): void {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try { window.localStorage.setItem(THEME_KEY, theme); } catch { /* storage blocked: theme still applies */ }
}

const NAV: { route: Route; label: string }[] = [
  { route: "workbench", label: "หน้าทำงาน" }, { route: "chat", label: "แชท" }, { route: "history", label: "ประวัติ" }, { route: "settings", label: "ตั้งค่า" },
];

export function App() {
  const route = useRoute();
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => applyTheme(theme), [theme]);
  useEffect(() => {
    api<{ user: User }>("/api/auth/me").then((r) => setUser(r.user)).catch(() => setUser(null));
  }, []);

  const onLogin = useCallback(async (u: User) => {
    setUser(u);
    const key = await api<KeyStatus>("/api/settings/key").catch(() => null);
    if (key && !key.configured) navigate("onboarding");
  }, []);
  const onAuthLost = useCallback(() => setUser(null), []);
  const onLogout = useCallback(async () => {
    await api("/api/auth/logout", json("POST")).catch(() => undefined);
    setUser(null);
    navigate("workbench");
  }, []);

  if (route === "showcase") return <Showcase />;

  return (
    <ToastProvider>
      {user === undefined && <main className="p-4"><Skeleton className="h-8 w-48" /></main>}
      {user === null && <Login onLogin={(u) => void onLogin(u)} />}
      {user && (
        <>
          <header className="border-b border-line bg-surface">
            <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
              <a href={hrefFor("workbench")} className="font-semibold text-fg">Backend-frontend</a>
              <nav aria-label="เมนูหลัก" className="flex flex-wrap gap-1">
                {NAV.map((n) => (
                  <a key={n.route} href={hrefFor(n.route)} aria-current={route === n.route ? "page" : undefined}
                    className={`rounded-sm px-3 py-1.5 text-sm ${route === n.route ? "bg-accent-weak text-fg font-medium" : "text-muted hover:text-fg"}`}>
                    {n.label}
                  </a>
                ))}
              </nav>
              <div className="ml-auto w-36">
                <Select label="ธีม" value={theme} onChange={(e) => setTheme(e.target.value as Theme)} options={[
                  { value: "system", label: "ตามระบบ" }, { value: "light", label: "สว่าง" }, { value: "dark", label: "มืด" },
                ]} />
              </div>
            </div>
          </header>
          <main className="mx-auto max-w-5xl p-4">
            {route === "workbench" && <Workbench onAuthLost={onAuthLost} />}
            {route === "chat" && <Chat onAuthLost={onAuthLost} />}
            {route === "history" && <History onAuthLost={onAuthLost} />}
            {route === "settings" && <Settings onLogout={() => void onLogout()} onAuthLost={onAuthLost} />}
            {route === "onboarding" && <Onboarding user={user} />}
          </main>
        </>
      )}
    </ToastProvider>
  );
}
