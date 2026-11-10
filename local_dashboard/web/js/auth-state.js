import { originBlockedMessage } from "./origin.js";

export function initialAuthState() {
  return { status: "signed_out", message: "", user: null, note: "" };
}

export function reduceAuth(state, event) {
  const current = state || initialAuthState();
  switch (event && event.type) {
    case "origin-blocked":
      return {
        status: "error",
        message: originBlockedMessage(event.origin),
        user: null,
        note: "",
      };
    case "start":
      return { status: "signing_in", message: "", user: null, note: "" };
    case "success":
      return {
        status: "signed_in",
        message: "",
        user: { name: event.name || "", email: event.email || "" },
        note: event.note || "",
      };
    case "signed-out":
      return { status: "signed_out", message: event.message || "", user: null, note: "" };
    case "error":
      return { status: "error", message: event.message || "เข้าสู่ระบบไม่สำเร็จ", user: null, note: "" };
    default:
      return current;
  }
}

export function displayUser(user) {
  if (!user) return "";
  if (user.name) return String(user.name);
  if (user.email) return String(user.email);
  return "";
}

export function authStatusLabel(state) {
  const current = state || initialAuthState();
  if (current.status === "signing_in") return "กำลังเข้าสู่ระบบ…";
  if (current.status === "signed_in") {
    const who = displayUser(current.user);
    let text = who ? "เข้าสู่ระบบแล้ว: " + who : "เข้าสู่ระบบแล้ว";
    if (current.note === "offline") text += " (เซิร์ฟเวอร์ offline)";
    if (current.note === "not implemented") text += " (เซสชันเซิร์ฟเวอร์ not implemented)";
    return text;
  }
  if (current.status === "error") return current.message || "เข้าสู่ระบบไม่สำเร็จ";
  if (current.message === "offline") return "offline — ตรวจสถานะจากเซิร์ฟเวอร์ไม่ได้";
  if (current.message === "not implemented") return "not implemented — เซิร์ฟเวอร์ยังไม่มีสถานะล็อกอิน";
  return "ยังไม่ได้เข้าสู่ระบบ";
}

/** kind: signin | signout | disabled | none */
export function authAction(state, originAllowed) {
  if (!originAllowed) return { kind: "disabled", label: "เข้าสู่ระบบด้วย Google" };
  if (state && state.status === "signing_in") return { kind: "none", label: "" };
  if (state && state.status === "signed_in") return { kind: "signout", label: "ออกจากระบบ" };
  if (state && state.status === "error") return { kind: "signin", label: "ลองใหม่" };
  return { kind: "signin", label: "เข้าสู่ระบบด้วย Google" };
}
