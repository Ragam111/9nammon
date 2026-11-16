import { AUTH_PATH, GOOGLE_CLIENT_ID } from "./config.js";
import { isAllowedOrigin, redirectUriFor } from "./origin.js";
import { initialAuthState, reduceAuth } from "./auth-state.js";

export function authRequestPath(origin, mode) {
  const url = new URL(AUTH_PATH, String(origin || "http://127.0.0.1:8421") + "/");
  url.searchParams.set("mode", mode);
  if (mode === "start") {
    url.searchParams.set("redirect_uri", redirectUriFor(origin));
    url.searchParams.set("client_id", GOOGLE_CLIENT_ID);
  }
  return url.pathname + url.search;
}

export function interpretAuthPayload(status, body) {
  if (status === 404 || status === 405 || status === 501) return { kind: "missing" };
  if (status === 302 || status === 303 || status === 307 || status === 308) {
    return { kind: "redirect", url: "" };
  }
  if (!(status >= 200 && status < 300)) return { kind: "offline" };
  if (!body || typeof body !== "object") return { kind: "missing" };
  if (typeof body.url === "string" && body.url) return { kind: "redirect", url: body.url };
  if (body.authenticated === true || body.status === "signed_in") {
    return { kind: "signed_in", name: body.name || "", email: body.email || "" };
  }
  if (body.authenticated === false || body.status === "signed_out" || body.ok === true) {
    return { kind: "signed_out" };
  }
  return { kind: "missing" };
}

function contentType(res) {
  if (!res.headers || !res.headers.get) return "";
  return res.headers.get("content-type") || "";
}

async function readAuth(res) {
  if (res && res.type === "opaqueredirect") return { kind: "redirect", url: "" };
  const ctype = contentType(res);
  if (res.status >= 200 && res.status < 300 && ctype && ctype.indexOf("json") === -1) {
    return { kind: "missing" };
  }
  let body = null;
  try { body = await res.json(); } catch (err) { body = null; }
  return interpretAuthPayload(res.status, body);
}

export function createAuthController(deps) {
  const fetchImpl = deps.fetchImpl;
  let state = initialAuthState();
  const listeners = new Set();

  function emit(next) {
    state = next;
    listeners.forEach(function (fn) { fn(state); });
  }

  async function refreshStatus() {
    try {
      const res = await fetchImpl(AUTH_PATH + "?mode=status", {
        headers: { Accept: "application/json" },
        cache: "no-store",
        redirect: "manual",
      });
      const kind = await readAuth(res);
      if (kind.kind === "redirect" || kind.kind === "missing") {
        emit(reduceAuth(state, { type: "signed-out", message: "not implemented" }));
        return state;
      }
      if (kind.kind === "offline") {
        emit(reduceAuth(state, { type: "signed-out", message: "offline" }));
        return state;
      }
      if (kind.kind === "signed_in") {
        emit(reduceAuth(state, { type: "success", name: kind.name, email: kind.email }));
        return state;
      }
      emit(reduceAuth(state, { type: "signed-out", message: "" }));
    } catch (err) {
      emit(reduceAuth(state, { type: "signed-out", message: "offline" }));
    }
    return state;
  }

  async function boot(loc) {
    if (!isAllowedOrigin(loc.origin)) {
      emit(reduceAuth(state, { type: "origin-blocked", origin: loc.origin }));
      return state;
    }
    const params = new URLSearchParams(loc.search || "");
    if (params.get("error")) {
      emit(reduceAuth(state, {
        type: "error",
        message: "Google ปฏิเสธการเข้าสู่ระบบ (" + params.get("error") + ")",
      }));
      return state;
    }
    const path = loc.pathname || "";
    if (params.get("code") && path.indexOf(AUTH_PATH) !== -1) {
      emit(reduceAuth(state, {
        type: "error",
        message: "not implemented — callback /auth/google ยังไม่ถูกเกตเวย์รับไว้",
      }));
      return state;
    }
    return refreshStatus();
  }

  async function signIn(loc) {
    if (!isAllowedOrigin(loc.origin)) {
      emit(reduceAuth(state, { type: "origin-blocked", origin: loc.origin }));
      return null;
    }
    emit(reduceAuth(state, { type: "start" }));
    const path = authRequestPath(loc.origin, "start");
    try {
      const res = await fetchImpl(path, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        redirect: "manual",
      });
      const kind = await readAuth(res);
      if (kind.kind === "redirect") {
        const target = kind.url || path;
        if (deps.assign) deps.assign(target);
        return target;
      }
      if (kind.kind === "missing") {
        emit(reduceAuth(state, { type: "error", message: "not implemented" }));
        return null;
      }
      emit(reduceAuth(state, { type: "error", message: kind.kind === "offline" ? "offline" : "เข้าสู่ระบบไม่สำเร็จ" }));
      return null;
    } catch (err) {
      emit(reduceAuth(state, { type: "error", message: "offline" }));
      return null;
    }
  }

  async function signOut() {
    try {
      await fetchImpl(AUTH_PATH + "?mode=logout", {
        method: "POST",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
    } catch (err) { /* เคลียร์สถานะบนจอต่อ */ }
    emit(reduceAuth(state, { type: "signed-out", message: "" }));
    return state;
  }

  return {
    getState: function () { return state; },
    subscribe: function (fn) {
      listeners.add(fn);
      return function () { listeners.delete(fn); };
    },
    boot: boot,
    signIn: signIn,
    signOut: signOut,
    refreshStatus: refreshStatus,
  };
}
