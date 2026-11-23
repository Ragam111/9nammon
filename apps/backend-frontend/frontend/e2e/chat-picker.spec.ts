// Chat model picker at 375px: two optgroups, status suffixes, refused picks show the reason, no horizontal scroll.
// The API is mocked with page.route, so this spec needs only the Vite dev server (no backend).
import { expect, type Page, type Route, test } from "@playwright/test";

const USER = { username: "e2e-user", role: "user" };
const CONV = { id: "c-1", title: "ทดสอบ", model: "claude-a", updated_at: "2026-11-20T10:00:00Z" };

const MIXED = [
  { id: "claude-a", provider: "claude", label: "Claude A", configured: true, provider_kind: "cloud", status: "ready" },
  { id: "gpt-a", provider: "gpt", label: "GPT A", configured: false, provider_kind: "cloud", status: "not_configured" },
  {
    id: "qwen2.5-coder:1.5b", provider: "ollama", label: "Qwen 1.5B", configured: false, provider_kind: "local",
    status: "not_installed", required_ram_gb: 2, available_ram_gb: 6,
  },
  {
    id: "big:7b", provider: "ollama", label: "Big 7B", configured: false, provider_kind: "local",
    status: "not_enough_memory", required_ram_gb: 8, available_ram_gb: 3,
  },
];

const LOCAL_ONLY = [
  {
    id: "qwen2.5-coder:1.5b", provider: "ollama", label: "Qwen 1.5B", configured: false, provider_kind: "local",
    status: "not_installed", required_ram_gb: 2, available_ram_gb: 6,
  },
];

async function mockApi(page: Page, models: unknown[]): Promise<void> {
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return json(route, { user: USER });
    if (path === "/api/settings/key") return json(route, { configured: true, last4: "7788", source: "stored" });
    if (path === "/api/chat/models") return json(route, { models });
    if (path === "/api/chat/conversations") return json(route, { conversations: [CONV] });
    if (path === `/api/chat/conversations/${CONV.id}`) return json(route, { ...CONV, messages: [] });
    return route.fulfill({ status: 404, contentType: "application/json", body: "{\"error\":{\"type\":\"unknown\",\"message\":\"x\",\"retryable\":false}}" });
  });
}

test.use({ viewport: { width: 375, height: 812 } });

test("picker shows local and server groups, status suffixes, and the reason for a refused pick", async ({ page }) => {
  await mockApi(page, MIXED);
  await page.goto("/#/chat");
  const select = page.getByLabel("เลือกโมเดล");
  await expect(select).toBeVisible();

  const groupLabels = await select.locator("optgroup").evaluateAll((els) => els.map((el) => el.getAttribute("label")));
  expect(groupLabels).toEqual(["ในเครื่อง", "บนเซิร์ฟเวอร์"]);

  const notInstalled = select.locator("option", { hasText: "Qwen 1.5B" });
  await expect(notInstalled).toHaveAttribute("aria-disabled", "true");
  await expect(notInstalled).toHaveText("Qwen 1.5B (ยังไม่ได้ติดตั้ง)");

  // Picking a not-ready row is refused: the selection stays on the ready model and the reason is shown.
  // Playwright refuses to select aria-disabled options, but a user can still choose one (mouse or arrow keys),
  // which fires the same change event, so the event is dispatched directly.
  await select.evaluate((el: HTMLSelectElement, value: string) => {
    el.value = value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }, "qwen2.5-coder:1.5b");
  await expect(page.getByText("ติดตั้งโมเดลด้วยคำสั่ง ollama pull qwen2.5-coder:1.5b")).toBeVisible();
  await expect(select).toHaveValue("claude-a");

  // The reason line stays inside the viewport and the page does not scroll sideways.
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(375);
});

test("only local rows, none ready: the neutral banner shows and the composer is blocked", async ({ page }) => {
  await mockApi(page, LOCAL_ONLY);
  await page.goto("/#/chat");
  await expect(page.getByText("ยังไม่มีโมเดลที่พร้อมใช้งาน — ดูสถานะด้านบน")).toBeVisible();
  await expect(page.getByLabel("พิมพ์ข้อความ")).toBeDisabled();
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(375);
});
