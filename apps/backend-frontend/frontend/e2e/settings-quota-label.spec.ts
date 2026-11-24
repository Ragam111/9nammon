// Settings quota meters: each bucket shows a text level (not colour alone) once usage passes 70% (ใกล้เต็ม)
// and 90% (เกือบเต็ม). The API is mocked with page.route, so this spec needs only the Vite dev server.
import { expect, type Page, type Route, test } from "@playwright/test";

const USER = { username: "e2e-user", role: "user" };
const RESET = "2026-11-25T10:00:00Z";
const KEY_STATUS = { configured: true, last4: "7788", source: "stored" };

function settingsView(usedPct: { five_hour: number; weekly: number; heavy_weekly: number }) {
  const bucket = (name: "five_hour" | "weekly" | "heavy_weekly", pct: number) => ({
    name, used: pct * 1000, limit: 100_000, resets_at: RESET,
  });
  return {
    user: USER,
    model: "claude-a",
    key: KEY_STATUS,
    quota: {
      window_hours: 5,
      buckets: [
        bucket("five_hour", usedPct.five_hour),
        bucket("weekly", usedPct.weekly),
        bucket("heavy_weekly", usedPct.heavy_weekly),
      ],
    },
    rate_limit: { user_per_min: 10, ip_per_min: 30, user_remaining: 9 },
    limits: { max_input_chars: 8000, max_output_tokens: 4096 },
  };
}

async function mockApi(page: Page, view: ReturnType<typeof settingsView>): Promise<void> {
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return json(route, { user: USER });
    if (path === "/api/settings") return json(route, view);
    if (path === "/api/settings/key") return json(route, KEY_STATUS);
    return route.fulfill({ status: 404, contentType: "application/json", body: "{\"error\":{\"type\":\"unknown\",\"message\":\"x\",\"retryable\":false}}" });
  });
}

// The meter wrapper is the innermost div that contains this bucket's progressbar.
function meter(page: Page, label: string) {
  return page.locator("div", { has: page.getByRole("progressbar", { name: `การใช้ ${label}` }) }).last();
}

const FIVE_HOUR = "ทุกโมเดล · 5 ชั่วโมง";
const WEEKLY = "ทุกโมเดล · รายสัปดาห์";
const HEAVY = "โมเดลหนัก · รายสัปดาห์";

test("quota bucket at 75% shows the text level ใกล้เต็ม", async ({ page }) => {
  await mockApi(page, settingsView({ five_hour: 75, weekly: 0, heavy_weekly: 0 }));
  await page.goto("/#/settings");
  await expect(meter(page, FIVE_HOUR).getByText("ใกล้เต็ม", { exact: true })).toBeVisible();
  await expect(meter(page, FIVE_HOUR).getByText("เกือบเต็ม", { exact: true })).toHaveCount(0);
});

test("quota bucket at 95% shows the text level เกือบเต็ม", async ({ page }) => {
  await mockApi(page, settingsView({ five_hour: 0, weekly: 95, heavy_weekly: 0 }));
  await page.goto("/#/settings");
  await expect(meter(page, WEEKLY).getByText("เกือบเต็ม", { exact: true })).toBeVisible();
  await expect(meter(page, WEEKLY).getByText("ใกล้เต็ม", { exact: true })).toHaveCount(0);
});

test("quota bucket at 50% shows no level text", async ({ page }) => {
  await mockApi(page, settingsView({ five_hour: 0, weekly: 0, heavy_weekly: 50 }));
  await page.goto("/#/settings");
  await expect(meter(page, HEAVY).getByText("ใช้ไป", { exact: false })).toBeVisible();
  await expect(meter(page, HEAVY).getByText("ใกล้เต็ม", { exact: true })).toHaveCount(0);
  await expect(meter(page, HEAVY).getByText("เกือบเต็ม", { exact: true })).toHaveCount(0);
});
