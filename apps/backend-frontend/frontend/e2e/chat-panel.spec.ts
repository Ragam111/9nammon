// Chat details panel: visible at xl width with the open conversation's model, message count and update time;
// hidden on phones. The API is mocked with page.route, so this spec needs only the Vite dev server.
import { expect, type Page, type Route, test } from "@playwright/test";

const USER = { username: "e2e-user", role: "user" };
const MODELS = [
  { id: "claude-a", provider: "claude", label: "Claude A", configured: true, provider_kind: "cloud", status: "ready" },
];
const CONV = { id: "c-9", title: "รายละเอียดทดสอบ", model: "claude-a", updated_at: "2026-11-20T10:00:00Z" };
const MESSAGES = [
  { id: "m-1", role: "user", content: "สวัสดี", status: "complete", created_at: "2026-11-20T10:00:00Z" },
  { id: "m-2", role: "assistant", content: "สวัสดีครับ", status: "complete", created_at: "2026-11-20T10:00:01Z" },
];

async function mockApi(page: Page): Promise<void> {
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return json(route, { user: USER });
    if (path === "/api/settings/key") return json(route, { configured: true, last4: "7788", source: "stored" });
    if (path === "/api/chat/models") return json(route, { models: MODELS });
    if (path === "/api/chat/conversations") return json(route, { conversations: [CONV] });
    if (path === `/api/chat/conversations/${CONV.id}`) return json(route, { ...CONV, messages: MESSAGES });
    return route.fulfill({ status: 404, contentType: "application/json", body: "{\"error\":{\"type\":\"unknown\",\"message\":\"x\",\"retryable\":false}}" });
  });
}

test("details panel shows the open conversation's model, message count and outputs placeholder at desktop width", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockApi(page);
  await page.goto("/#/chat");
  const panel = page.locator("aside", { has: page.getByRole("heading", { name: "รายละเอียดการสนทนา" }) });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Claude A", { exact: true })).toBeVisible();
  await expect(panel.getByText("จำนวนข้อความ")).toBeVisible();
  await expect(panel.locator("dd", { hasText: /^2$/ })).toBeVisible();
  await expect(panel.getByText("อัปเดตล่าสุด")).toBeVisible();
  await expect(panel.getByText("ยังไม่มีผลลัพธ์ในการสนทนานี้")).toBeVisible();
});

test("details panel is hidden at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockApi(page);
  await page.goto("/#/chat");
  await expect(page.getByRole("heading", { name: "รายละเอียดการสนทนา" })).toBeHidden();
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(375);
});
