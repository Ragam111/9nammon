// Hash router for the back-office. Routes: #/ (dashboard), #/users?… (list with filters), #/users/:id (detail).
import { useEffect, useState } from "react";

export type Route =
  | { name: "dashboard" }
  | { name: "users"; search: URLSearchParams }
  | { name: "user"; id: number }
  | { name: "unknown" };

export function parseRoute(hash: string): Route {
  const [path = "", query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts.length === 0) return { name: "dashboard" };
  if (parts[0] === "users" && parts.length === 1) return { name: "users", search: new URLSearchParams(query) };
  if (parts[0] === "users" && parts.length === 2 && /^\d+$/.test(parts[1])) {
    return { name: "user", id: Number(parts[1]) };
  }
  return { name: "unknown" };
}

export function go(hash: string): void {
  window.location.hash = hash;
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
