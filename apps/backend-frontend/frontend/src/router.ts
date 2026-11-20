// Minimal hash router: #/, #/history, #/settings, #/onboarding, #/showcase. No dependency needed.
import { useEffect, useState } from "react";

export type Route = "workbench" | "history" | "settings" | "onboarding" | "showcase";

const ROUTES: Record<string, Route> = {
  "": "workbench", "#/": "workbench", "#/history": "history", "#/settings": "settings",
  "#/onboarding": "onboarding", "#/showcase": "showcase",
};

export const hrefFor = (route: Route): string => (route === "workbench" ? "#/" : `#/${route}`);

export function currentRoute(): Route {
  return ROUTES[window.location.hash] ?? "workbench";
}

export function navigate(route: Route): void {
  window.location.hash = hrefFor(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(currentRoute);
  useEffect(() => {
    const onChange = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
