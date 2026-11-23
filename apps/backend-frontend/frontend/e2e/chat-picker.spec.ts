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

type MockConv = { id: string; title: string; model: string; updated_at: string };

async function mockApi(page: Page, models: unknown[], convs: MockConv[] = [CONV]): Promise<void> {
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return json(route, { user: USER });
    if (path === "/api/settings/key") return json(route, { configured: true, last4: "7788", source: "stored" });
    if (path === "/api/chat/models") return json(route, { models });
    if (path === "/api/chat/conversations") return json(route, { conversations: convs });
    const detail = convs.find((c) => path === `/api/chat/conversations/${c.id}`);
    if (detail) return json(route, { ...detail, messages: [] });
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

const SECOND_CONV: MockConv = { id: "c-2", title: "สนทนาที่สอง", model: "claude-a", updated_at: "2026-11-20T09:00:00Z" };
const NOT_READY_CONV: MockConv = { id: "c-3", title: "โมเดลยังไม่พร้อม", model: "gpt-a", updated_at: "2026-11-20T08:00:00Z" };
const QWEN_REASON = "ติดตั้งโมเดลด้วยคำสั่ง ollama pull qwen2.5-coder:1.5b";

// P3 minor 1: a refused pick's reason must not follow the user into another conversation.
test("a refused pick's reason clears when the user opens another conversation", async ({ page }) => {
  await mockApi(page, MIXED, [CONV, SECOND_CONV]);
  await page.goto("/#/chat");
  const select = page.getByLabel("เลือกโมเดล");
  await expect(select).toBeVisible();
  await select.evaluate((el: HTMLSelectElement, value: string) => {
    el.value = value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }, "qwen2.5-coder:1.5b");
  await expect(page.getByText(QWEN_REASON)).toBeVisible();

  await page.getByRole("button", { name: "เปิดเมนู" }).click(); // the history drawer is closed at 375px
  await page.locator(`button[title="${SECOND_CONV.title}"]`).click();
  await expect(page.getByText(QWEN_REASON)).toBeHidden();
  await expect(select).toHaveValue("claude-a");
});

// P3 minor 2: the composer must be blocked when the conversation's own model is not ready,
// even if some other model in the list is ready.
test("composer is blocked when the open conversation's model is not ready", async ({ page }) => {
  await mockApi(page, MIXED, [NOT_READY_CONV]);
  await page.goto("/#/chat");
  await expect(page.locator(`button[title="${NOT_READY_CONV.title}"][aria-current="page"]`)).toHaveCount(1); // opens by itself
  await expect(page.getByLabel("พิมพ์ข้อความ")).toBeDisabled();
  await expect(page.getByRole("button", { name: "ส่ง" })).toBeDisabled();
});

// Review finding: while a conversation's detail is still loading, the model is the previous conversation's.
// The composer must not accept a message in that window.
test("composer is blocked while the next conversation is still loading", async ({ page }) => {
  await mockApi(page, MIXED, [CONV, { ...NOT_READY_CONV, title: "กำลังโหลด" }]);
  await page.route(`**/api/chat/conversations/${NOT_READY_CONV.id}`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 6000)); // long enough to assert inside the window
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...NOT_READY_CONV, messages: [] }) });
  });
  await page.goto("/#/chat");
  // Open a ready conversation first, so the model state holds a ready model before the slow one is opened.
  await page.getByRole("button", { name: "เปิดเมนู" }).click();
  await page.locator(`button[title="${CONV.title}"]`).click();
  await expect(page.getByLabel("เลือกโมเดล")).toHaveValue("claude-a");
  await page.getByRole("button", { name: "เปิดเมนู" }).click();
  await page.locator('button[title="กำลังโหลด"]').click();
  // Checked inside the 6 s window: the short timeout fails before the detail (gpt-a, not ready) arrives.
  await expect(page.getByLabel("พิมพ์ข้อความ")).toBeDisabled({ timeout: 2000 });
});
