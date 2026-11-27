import { defineConfig, devices } from "@playwright/test";

// E2E runs against a running frontend (default: `next start -p 3100`) whose
// server side is configured to reach the Sprite API.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  // Specs share one live organization, so they must not interleave.
  workers: 1,
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3100", trace: "off" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
