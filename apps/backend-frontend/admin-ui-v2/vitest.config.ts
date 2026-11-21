import { defineConfig } from "vitest/config";

// Unit tests cover pure helpers in src/lib. Browser flows are not covered in phase 1.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
