import { describe, expect, it } from "vitest";
import { buildUsersQuery, formatBangkok, parseServerTime, providerLabel, roleLabel } from "./format";

describe("parseServerTime", () => {
  it("reads a SQLite UTC timestamp with no zone as UTC", () => {
    expect(parseServerTime("2026-11-21 10:00:00").toISOString()).toBe("2026-11-21T10:00:00.000Z");
  });

  it("keeps a timestamp that already has a Z suffix", () => {
    expect(parseServerTime("2026-11-21T10:00:00Z").toISOString()).toBe("2026-11-21T10:00:00.000Z");
  });

  it("keeps an explicit offset", () => {
    expect(parseServerTime("2026-11-21T10:00:00+07:00").toISOString()).toBe("2026-11-21T03:00:00.000Z");
  });
});

describe("formatBangkok", () => {
  it("shows 10:00 UTC as 17:00 in Bangkok", () => {
    expect(formatBangkok("2026-11-21 10:00:00")).toContain("17:00");
  });

  it("handles missing and invalid values", () => {
    expect(formatBangkok(null)).toBe("ยังไม่มี");
    expect(formatBangkok("not a date")).toBe("ไม่ทราบเวลา");
  });
});

describe("labels", () => {
  it("maps roles and providers to Thai and display names", () => {
    expect(roleLabel("admin")).toBe("ผู้ดูแลระบบ");
    expect(roleLabel("user")).toBe("ผู้ใช้");
    expect(providerLabel("github")).toBe("GitHub");
    expect(providerLabel("apple")).toBe("apple");
  });
});

describe("buildUsersQuery", () => {
  const base = { q: "", role: "" as const, sort: "created_at" as const, order: "desc" as const, offset: 0, limit: 20 };

  it("leaves out defaults so the URL stays short", () => {
    expect(buildUsersQuery(base)).toBe("");
  });

  it("includes only what differs from the default and trims the search text", () => {
    expect(buildUsersQuery({ ...base, q: "  ali ", role: "admin", sort: "username", order: "asc", offset: 20 }))
      .toBe("?q=ali&role=admin&sort=username&order=asc&offset=20");
  });
});
