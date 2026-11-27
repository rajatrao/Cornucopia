import { defineConfig, devices } from "@playwright/test";

// E2E runs against a running frontend (default: `next start -p 3100`) whose
// server side reaches the Sprite API. Specs share one live organization, so
// they run serially.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3100", trace: "off" },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    { name: "desktop", use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/approver.json" }, dependencies: ["setup"], testIgnore: /auth\.setup\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"], storageState: "e2e/.auth/approver.json" }, dependencies: ["setup"], testIgnore: [/auth\.setup\.ts/, /phase6/] },
  ],
});
