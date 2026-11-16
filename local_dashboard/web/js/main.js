import { authAction, authStatusLabel } from "./auth-state.js";
import { GOOGLE_CLIENT_ID } from "./config.js";
import { el } from "./dom.js";
import { createAuthController } from "./oauth.js";
import { isAllowedOrigin, originBlockedMessage, redirectUriFor } from "./origin.js";
import { parseRoute, stripOAuthParams } from "./router.js";

const auth = createAuthController({
  fetchImpl: fetch.bind(window),
  assign: function (url) { window.location.assign(url); },
});

const view = document.getElementById("view");
const authBar = document.getElementById("auth-bar");
const banner = document.getElementById("origin-banner");
let disposePanel = function () {};
let generation = 0;

function paintAuth(state) {
  authBar.replaceChildren();
  authBar.append(el("span", { id: "auth-label" }, authStatusLabel(state)));
  const action = authAction(state, isAllowedOrigin(window.location.origin));
  if (action.kind === "none") return;
  const button = el("button", {
    type: "button",
    id: action.kind === "signout" ? "auth-signout" : "auth-signin",
  }, action.label);
  if (action.kind === "disabled") button.disabled = true;
  button.addEventListener("click", function () {
    if (button.disabled) return;
    if (action.kind === "signout") auth.signOut();
    else auth.signIn(window.location);
  });
  authBar.append(button);
  const accountStatus = document.getElementById("account-status");
  if (accountStatus) accountStatus.textContent = authStatusLabel(state);
}

function renderHome() {
  view.append(
    el("h2", null, "ภาพรวม"),
    el("p", null, "แดชบอร์ดหลักบนพอร์ต 8421 สำหรับ Windows 10 Pro, Intel Core i5-7400 (4C/4T), RAM 8GB, HDD/SSD, การ์ดจอออนบอร์ด. แผงล็อกกับแผงโหนดจะโหลดเมื่อเปิดเท่านั้น"),
    el("ul", null),
  );
  const list = view.querySelector("ul");
  list.append(
    el("li", null, "ล็อกเทอร์มินัล — สตรีมทีละก้อนไม่เกิน 32KB และเก็บบนจอไม่เกิน 500 บรรทัด"),
    el("li", null, "สถานะโหนด — พอร์ต 8420 คือโหนดงาน และ 8421 คือแดชบอร์ดนี้"),
    el("li", null, "บัญชี Google — ใช้ได้เมื่อเปิดจาก origin ที่ลงทะเบียนไว้เท่านั้น"),
  );
}

function renderMissing() {
  view.append(
    el("h2", null, "ไม่พบหน้านี้"),
    el("p", null, "เส้นทางนี้ไม่มีในแดชบอร์ด"),
    el("a", { href: "#/" }, "กลับภาพรวม"),
  );
}

function renderAccount() {
  const allowed = isAllowedOrigin(window.location.origin);
  view.append(
    el("h2", null, "บัญชี"),
    el("p", { id: "account-status" }, authStatusLabel(auth.getState())),
    el("p", null, "Client ID: " + GOOGLE_CLIENT_ID),
    el("p", null, allowed
      ? "Redirect URI ที่จะส่งให้ Google คือ " + redirectUriFor(window.location.origin)
      : originBlockedMessage(window.location.origin)),
    el("p", { class: "muted" }, "หน้านี้ไม่เก็บความลับของไคลเอนต์ และไม่เขียนโทเคนลงที่เก็บถาวรของเบราว์เซอร์"),
  );
}

async function show(next) {
  const ticket = ++generation;
  disposePanel();
  disposePanel = function () {};
  view.replaceChildren();
  document.querySelectorAll("nav a").forEach(function (link) {
    if (link.getAttribute("data-route") === next) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  if (next === "/") {
    renderHome();
    return;
  }
  if (next === "/account") {
    renderAccount();
    return;
  }
  if (next == null) {
    renderMissing();
    return;
  }
  view.append(el("p", null, "กำลังเปิดแผง…"));
  try {
    if (next === "/logs") {
      const mod = await import("./log-panel.js");
      if (ticket !== generation) return;
      view.replaceChildren();
      disposePanel = mod.mountLogPanel(view);
    } else if (next === "/nodes") {
      const mod = await import("./node-panel.js");
      if (ticket !== generation) return;
      view.replaceChildren();
      disposePanel = mod.mountNodePanel(view);
    }
  } catch (err) {
    if (ticket !== generation) return;
    view.replaceChildren(el("p", null, "เปิดแผงไม่ได้"));
  }
}

function bootOriginBanner() {
  if (isAllowedOrigin(window.location.origin)) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.textContent = originBlockedMessage(window.location.origin);
}

window.addEventListener("hashchange", function () {
  show(parseRoute(window.location.hash));
});

auth.subscribe(paintAuth);
bootOriginBanner();
paintAuth(auth.getState());
show(parseRoute(window.location.hash));

auth.boot(window.location).then(function () {
  if (/[?&](code|state|error)=/.test(window.location.search)) {
    const next = stripOAuthParams(window.location.href);
    if (next !== window.location.pathname + window.location.search + window.location.hash) {
      history.replaceState(null, "", next);
    }
  }
  paintAuth(auth.getState());
});

if (isAllowedOrigin(window.location.origin) && "serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch(function () {});
}
