// End-to-end tests for the three main flows (set key, main work, history), plus accessibility
// (axe, both themes) and the 360px layout. Runs against the real API with the fake model.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const USER = "e2e-admin";
const TEST_KEY = "sk-e2e-test-key-7788"; // fake value, never a real key

async function login(page: Page): Promise<void> {
  const password = process.env.E2E_PASSWORD;
  if (!password) throw new Error("E2E_PASSWORD is not set (playwright.config.ts sets it)");
  await page.goto("/");
  await page.getByLabel("ชื่อผู้ใช้").fill(USER);
  await page.getByLabel("รหัสผ่าน").fill(password);
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();
  await expect(page.getByRole("navigation", { name: "เมนูหลัก" })).toBeVisible();
}

async function send(page: Page, prompt: string): Promise<void> {
  await page.getByLabel("คำสั่งถึงโมเดล").fill(prompt);
  await page.getByRole("button", { name: "ส่ง", exact: true }).click();
}

test.describe.serial("main flows", () => {
  test("1. set the model key: only the last 4 characters are ever shown", async ({ page, context }) => {
    await login(page);
    await expect(page).toHaveURL(/#\/onboarding$/);
    const cookie = (await context.cookies()).find((c) => c.name === "bf_session");
    expect(cookie?.httpOnly).toBe(true);

    await page.getByLabel("API key ใหม่").fill(TEST_KEY);
    await page.getByRole("button", { name: "บันทึก key" }).click();
    await expect(page.getByText("••••7788")).toBeVisible();
    await expect(page.getByLabel("API key ใหม่")).toHaveValue("");
    expect(await page.content()).not.toContain(TEST_KEY);

    await page.getByRole("link", { name: "ตั้งค่า" }).click();
    await expect(page.getByText("••••7788")).toBeVisible();
    expect(await page.content()).not.toContain(TEST_KEY);
  });

  test("2. main work: streams an answer, keeps partial output, points to settings on a bad key", async ({ page }) => {
    await login(page);
    await page.goto("/#/");
    await send(page, "อธิบาย SSE สั้นๆ");
    await expect(page.getByText(/คำตอบจำลองสำหรับ: อธิบาย SSE/)).toBeVisible();
    await expect(page.getByText(/^สำเร็จ · /)).toBeVisible();

    await send(page, "test drop");
    await expect(page.getByText("ได้คำตอบบางส่วน")).toBeVisible();
    await expect(page.getByRole("alert")).toContainText("ผลที่ได้มาแล้วยังอยู่");
    await expect(page.getByRole("button", { name: "ลองใหม่" })).toBeVisible();

    await send(page, "test badkey");
    await expect(page.getByRole("alert")).toContainText("API key ของโมเดลไม่ถูกต้อง");
    await page.getByRole("button", { name: "ไปตั้งค่า API key" }).click();
    await expect(page).toHaveURL(/#\/settings$/);
  });

  test("3. history: search, filter, open the detail and delete", async ({ page }) => {
    // Creates its own runs with a unique marker, so it does not depend on what earlier tests left behind.
    await login(page);
    const marker = `marker-${Date.now().toString(36)}`;
    for (const prompt of [`อธิบาย ${marker}`, `test drop ${marker}`]) {
      const res = await page.request.post("/api/run", { data: { prompt } });
      expect(res.ok()).toBe(true);
      await res.text(); // read the whole stream so the run is finished and stored
    }

    await page.goto("/#/history");
    await page.getByLabel("ค้นหา").fill(marker);
    await expect(page.locator("tbody tr")).toHaveCount(2);

    await page.getByLabel("สถานะ").selectOption("partial");
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await expect(page.locator("tbody tr")).toContainText("บางส่วน");
    await page.getByLabel("สถานะ").selectOption("");

    await page.locator("tbody tr").filter({ hasText: `อธิบาย ${marker}` })
      .getByRole("button", { name: /ดูรายละเอียด/ }).click();
    await expect(page.getByRole("heading", { name: "รายละเอียด" })).toBeVisible();
    // The prompt also appears in the table row, so match the detail's paragraph only.
    await expect(page.getByRole("paragraph").filter({ hasText: `อธิบาย ${marker}` })).toBeVisible();

    await page.getByRole("button", { name: "ลบ", exact: true }).first().click();
    const dialog = page.getByRole("dialog", { name: "ลบประวัตินี้?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "ลบ", exact: true }).click();
    await expect(page.getByText("ลบประวัติแล้ว")).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(1);
  });
});

test.describe("quality", () => {
  const routes = ["#/", "#/history", "#/settings"];

  test("no serious or critical axe violations in light and dark", async ({ page }) => {
    await page.goto("/");
    const loginScan = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(loginScan.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);

    await login(page);
    for (const theme of ["light", "dark"]) {
      await page.getByLabel("ธีม").selectOption(theme);
      for (const route of routes) {
        await page.goto(`/${route}`);
        await expect(page.locator("main h1")).toBeVisible();
        const scan = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
        const bad = scan.violations
          .filter((v) => v.impact === "serious" || v.impact === "critical")
          .map((v) => `${theme} ${route}: ${v.id} (${v.nodes.length})`);
        expect(bad).toEqual([]);
      }
    }
  });

  test("no horizontal scroll at 360px", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await login(page);
    for (const route of routes) {
      await page.goto(`/${route}`);
      await expect(page.locator("main h1")).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, route).toBeLessThanOrEqual(0);
    }
  });
});
