export const ROUTES = Object.freeze(["/", "/logs", "/nodes", "/account"]);

export function parseRoute(hash) {
  let raw = hash == null ? "" : String(hash);
  if (raw.charAt(0) === "#") raw = raw.slice(1);
  const pathOnly = raw.split("?")[0];
  if (pathOnly === "" || pathOnly === "/") return "/";
  const path = pathOnly.charAt(0) === "/" ? pathOnly : "/" + pathOnly;
  if (path.length > 1 && path.endsWith("/")) {
    const trimmed = path.slice(0, -1);
    return ROUTES.indexOf(trimmed) === -1 ? null : trimmed;
  }
  return ROUTES.indexOf(path) === -1 ? null : path;
}

export function stripOAuthParams(href) {
  const url = new URL(href, "http://127.0.0.1:8421");
  url.searchParams.delete("code");
  url.searchParams.delete("state");
  url.searchParams.delete("error");
  url.searchParams.delete("error_description");
  url.searchParams.delete("scope");
  url.searchParams.delete("authuser");
  url.searchParams.delete("prompt");
  url.searchParams.delete("iss");
  const search = url.searchParams.toString();
  return url.pathname + (search ? "?" + search : "") + url.hash;
}
