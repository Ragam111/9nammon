// Onboarding: when no API key is configured, the "go to work" button is disabled and a visible hint explains why,
// linked to the button with aria-describedby. The API is mocked with page.route, so only the Vite dev server is needed.
import { expect, type Page, type Route, test } from "@playwright/test";

const USER = { username: "e2e-user", role: "user" };
const HEALTH = { status: "ok", model: "claude-a", model_key_configured: false };
const LOCAL_HEALTH = { enabled: true, reachable: false, models: [], available_ram_gb: 16, models_detail: [] };

async function mockApi(page: Page): Promise<void> {
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return json(route, { user: USER });
    if (path === "/api/settings/key") return json(route, { configured: false, last4: "", source: "none" });
    if (path === "/api/health") return json(route, HEALTH);
    if (path === "/api/chat/local/health") return json(route, LOCAL_HEALTH);
    return route.fulfill({ status: 404, contentType: "application/json", body: "{\"error\":{\"type\":\"unknown\",\"message\":\"x\",\"retryable\":false}}" });
  });
}

test("go-to-work button is disabled without a key and is described by a visible hint", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockApi(page);
  await page.goto("/#/onboarding");
  const goWork = page.getByRole("button", { name: "ไปหน้าทำงาน" });
  await expect(goWork).toBeDisabled();
  await expect(goWork).toHaveAttribute("aria-describedby", "go-work-hint");
  const hint = page.locator("#go-work-hint");
  await expect(hint).toBeVisible();
  await expect(hint).toContainText("ต้องตั้ง API key ก่อนจึงไปหน้าทำงานได้");
  await expect(page.getByRole("button", { name: /^ข้าม/ })).toBeEnabled();
});
