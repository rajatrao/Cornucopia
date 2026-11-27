import { expect, test } from "@playwright/test";

// Real stack, dev organization with the labelled [sample] Thanksgiving data in
// its post-cancellation state (rice gone; quinoa stock varies with later
// tests). The answer is computed by CP-SAT on the Sprite; the assertions check
// that the UI shows the verified, persisted result and its alternatives.
test("optimizer result in the UI matches the persisted, verified run", async ({ page, request }) => {
  await page.goto("/optimizer");
  await page.getByRole("button", { name: "Run CP-SAT optimizer" }).click();
  const result = page.getByRole("region", { name: "Optimization result" });
  await expect(result).toBeVisible({ timeout: 30_000 });
  const [latest] = await (await request.get("/api/ops/optimizer/runs?limit=1")).json();
  expect(latest.verdict).toMatch(/^verified_/);
  expect(latest.solver_status).toBe("OPTIMAL");
  await expect(result).toContainText(`${latest.objectives.meals_served} / 500 meals`);
  await expect(result).toContainText(latest.verdict.replace("_", " "));
  const alts = page.getByRole("table", { name: "Alternative plans" });
  // rice is cancelled in the sample data: without substitutions nothing can be cooked
  await expect(alts.getByRole("row", { name: /^no substitutions/ })).toContainText("0");
  await expect(alts.getByRole("row", { name: /^recommended/ })).toContainText(String(latest.objectives.meals_served));
  await expect(page.getByRole("table", { name: "Objective stages" })).toContainText("OPTIMAL");
  await expect(page.getByRole("note", { name: "Diagnosis" })).toBeVisible();
});

test("without substitutions the optimizer refuses to invent meals", async ({ page }) => {
  await page.goto("/optimizer");
  await page.getByLabel("Allow ingredient substitutions").uncheck();
  await page.getByRole("button", { name: "Run CP-SAT optimizer" }).click();
  const result = page.getByRole("region", { name: "Optimization result" });
  await expect(result).toContainText("0 / 500 meals", { timeout: 30_000 });
  await expect(page.getByRole("note", { name: "Diagnosis" })).toContainText("[sample] Rice 120.0 lb");
  await expect(page.getByRole("list").filter({ hasText: "verified" }).first()).toBeVisible();
});
