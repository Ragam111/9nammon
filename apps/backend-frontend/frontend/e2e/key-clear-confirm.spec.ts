// Clearing a stored API key asks for confirmation first: the dialog opens without sending DELETE,
// cancelling sends nothing, and confirming sends exactly one DELETE. The API is mocked with page.route,
// so this spec needs only the Vite dev server.
import { expect, type Page, type Route, test } from "@playwright/test";

const USER = { username: "e2e-user", role: "admin" };
const DIALOG_TITLE = "ลบ API key ที่ตั้งไว้?";

function settingsView() {
  return {
    user: USER,
    model: "claude-a",
    key: { configured: true, last4: "7788", source: "stored" },
    quota: {
      window_hours: 5,
      buckets: [
        { name: "five_hour", used: 0, limit: 100_000, resets_at: "2026-11-25T10:00:00Z" },
        { name: "weekly", used: 0, limit: 100_000, resets_at: "2026-11-25T10:00:00Z" },
        { name: "heavy_weekly", used: 0, limit: 100_000, resets_at: "2026-11-25T10:00:00Z" },
      ],
    },
    rate_limit: { user_per_min: 10, ip_per_min: 30, user_remaining: 9 },
    limits: { max_input_chars: 8000, max_output_tokens: 4096 },
  };
}

/** Mocks the API and counts DELETE requests to the key endpoint. */
async function mockApi(page: Page): Promise<{ deletes: () => number }> {
  let deleteCount = 0;
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/auth/me") return json(route, { user: USER });
    if (path === "/api/settings") return json(route, settingsView());
    if (path === "/api/settings/key") {
      if (route.request().method() === "DELETE") {
        deleteCount += 1;
        return json(route, { configured: false, last4: "", source: "none" });
      }
      return json(route, { configured: true, last4: "7788", source: "stored" });
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: "{\"error\":{\"type\":\"unknown\",\"message\":\"x\",\"retryable\":false}}" });
  });
  return { deletes: () => deleteCount };
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
});

test("clearing a stored key opens a confirm dialog and does not DELETE yet", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "ลบ key ที่ตั้งไว้" }).click();
  const dialog = page.getByRole("dialog", { name: DIALOG_TITLE });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("ระบบจะลบ key ที่บันทึกไว้ในเซิร์ฟเวอร์")).toBeVisible();
  expect(api.deletes()).toBe(0);
});

test("cancelling the confirm dialog sends no DELETE", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "ลบ key ที่ตั้งไว้" }).click();
  const dialog = page.getByRole("dialog", { name: DIALOG_TITLE });
  await dialog.getByRole("button", { name: "ยกเลิก" }).click();
  await expect(dialog).toBeHidden();
  await page.waitForTimeout(300);
  expect(api.deletes()).toBe(0);
});

test("confirming the dialog sends exactly one DELETE", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "ลบ key ที่ตั้งไว้" }).click();
  const dialog = page.getByRole("dialog", { name: DIALOG_TITLE });
  await dialog.getByRole("button", { name: "ลบ key" }).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => api.deletes()).toBe(1);
});
