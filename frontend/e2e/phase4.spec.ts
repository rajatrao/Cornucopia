import { expect, test } from "@playwright/test";

// Real stack, dev organization with the labelled [sample] Thanksgiving data in
// its post-cancellation state (rice gone, 40 lb quinoa on hand). The answer is
// computed by CP-SAT on the Sprite; the assertions check it is explained,
// verified and consistent, and compare it against the alternatives.
test("optimizer recovers what the stock allows and explains the rest", async ({ page }) => {
  await page.goto("/optimizer");
  await page.getByRole("button", { name: "Run CP-SAT optimizer" }).click();
  const result = page.getByRole("region", { name: "Optimization result" });
  await expect(result).toBeVisible({ timeout: 30_000 });
  await expect(result).toContainText("verified partial");
  await expect(result).toContainText("166 / 500 meals");
  await expect(page.getByRole("note", { name: "Diagnosis" })).toContainText("[sample] Rice 80.0 lb");
  await expect(result).toContainText("[sample] Rice →");
  const alts = page.getByRole("table", { name: "Alternative plans" });
  await expect(alts.getByRole("row", { name: /^baseline/ })).toContainText("0");
  await expect(alts.getByRole("row", { name: /^no substitutions/ })).toContainText("0");
  await expect(alts.getByRole("row", { name: /^recommended/ })).toContainText("166");
  await expect(page.getByRole("table", { name: "Objective stages" })).toContainText("OPTIMAL");
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
