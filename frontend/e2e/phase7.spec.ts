import { expect, test } from "@playwright/test";

test("command center shows live operational state", async ({ page }) => {
  await page.goto("/");
  const tiles = page.getByLabel("Operation summary");
  await expect(tiles).toContainText("Meals committed", { timeout: 30_000 });
  await expect(tiles).toContainText("Feasible right now");
  await expect(page.getByLabel("Inventory coverage chart")).toBeVisible();
});

test("reality recompilation renders the affected dependency graph", async ({ page }) => {
  await page.goto("/recompilation");
  await expect(page.getByLabel("Incoming event")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".react-flow__node").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Agent timeline")).toContainText("receive_event");
});

test("simulation laboratory is isolated from production", async ({ page, request }) => {
  const before = (await (await request.get("/api/ops/optimizer/runs?limit=1")).json())[0]?.id;
  await page.goto("/simulation");
  await page.getByRole("button", { name: /Volunteer shortage/ }).click();
  const result = page.getByRole("region", { name: "Simulation result" });
  await expect(result).toContainText("cooks are unavailable", { timeout: 60_000 });
  await expect(result).toContainText("isolated simulation");
  const after = (await (await request.get("/api/ops/optimizer/runs?limit=1")).json())[0]?.id;
  expect(after).toBe(before); // nothing persisted
});
