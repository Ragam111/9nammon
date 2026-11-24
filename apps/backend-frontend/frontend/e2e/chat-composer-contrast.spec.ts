// Disabled chat composer: the placeholder must keep at least 4.5:1 contrast against the textarea background
// in both themes (DESIGN.md). Contrast uses the computed colors, including the textarea's opacity.
// The API is mocked with page.route, so this spec needs only the Vite dev server (no backend).
import { expect, type Page, type Route, test } from "@playwright/test";

type Rgba = { r: number; g: number; b: number; a: number };

const USER = { username: "e2e-user", role: "user" };
const MODELS = [
  { id: "claude-a", provider: "claude", label: "Claude A", configured: true, provider_kind: "cloud", status: "ready" },
  { id: "gpt-a", provider: "gpt", label: "GPT A", configured: false, provider_kind: "cloud", status: "not_configured" },
];
// The open conversation uses gpt-a, which is not ready, so the composer is disabled and shows the blocked placeholder.
const BLOCKED_CONV = { id: "c-3", title: "โมเดลยังไม่พร้อม", model: "gpt-a", updated_at: "2026-11-20T08:00:00Z" };
const MIN_CONTRAST = 4.5;

async function mockApi(page: Page): Promise<void> {
  const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return json(route, { user: USER });
    if (path === "/api/settings/key") return json(route, { configured: true, last4: "7788", source: "stored" });
    if (path === "/api/chat/models") return json(route, { models: MODELS });
    if (path === "/api/chat/conversations") return json(route, { conversations: [BLOCKED_CONV] });
    if (path === `/api/chat/conversations/${BLOCKED_CONV.id}`) return json(route, { ...BLOCKED_CONV, messages: [] });
    return route.fulfill({ status: 404, contentType: "application/json", body: "{\"error\":{\"type\":\"unknown\",\"message\":\"x\",\"retryable\":false}}" });
  });
}

function parseColor(value: string): Rgba {
  const match = value.match(/rgba?\(([^)]+)\)/);
  if (!match) throw new Error(`unparseable color: ${value}`);
  const parts = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
  return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
}

// Source-over compositing of a translucent color onto an opaque one.
function over(top: Rgba, bottom: Rgba): Rgba {
  const a = top.a;
  return {
    r: top.r * a + bottom.r * (1 - a),
    g: top.g * a + bottom.g * (1 - a),
    b: top.b * a + bottom.b * (1 - a),
    a: 1,
  };
}

function channelLuminance(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(c: Rgba): number {
  return 0.2126 * channelLuminance(c.r) + 0.7152 * channelLuminance(c.g) + 0.0722 * channelLuminance(c.b);
}

function contrastRatio(a: Rgba, b: Rgba): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// The textarea paints its background and placeholder as one group, then the group is blended with opacity over the page.
function placeholderContrast(sample: { placeholder: string; background: string; opacity: string; page: string }): number {
  const opacity = Number(sample.opacity);
  const page = parseColor(sample.page);
  const elementBg = parseColor(sample.background);
  const placeholderInGroup = over(parseColor(sample.placeholder), elementBg);
  const bgOnPage = over({ ...elementBg, a: opacity }, page);
  const textOnPage = over({ ...placeholderInGroup, a: opacity }, page);
  return contrastRatio(textOnPage, bgOnPage);
}

for (const scheme of ["light", "dark"] as const) {
  test(`disabled composer placeholder keeps 4.5:1 contrast in the ${scheme} theme`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page);
    await page.goto("/#/chat");

    const textarea = page.getByLabel("พิมพ์ข้อความ");
    await expect(textarea).toBeDisabled();
    const sample = await textarea.evaluate((el) => {
      const style = getComputedStyle(el);
      return {
        placeholder: getComputedStyle(el, "::placeholder").color,
        background: style.backgroundColor,
        opacity: style.opacity,
        page: getComputedStyle(document.body).backgroundColor,
      };
    });

    const ratio = placeholderContrast(sample);
    expect(ratio, `placeholder contrast ${ratio.toFixed(2)}:1 (${JSON.stringify(sample)})`).toBeGreaterThanOrEqual(MIN_CONTRAST);
  });
}
