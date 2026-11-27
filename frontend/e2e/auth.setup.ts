import { expect, test as setup } from "@playwright/test";

import { e2eSecret } from "./secrets";

setup("sign in as the e2e approver", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Username").fill("e2e-approver");
  await page.getByLabel("Password").fill(e2eSecret("E2E_APPROVER_PASSWORD"));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Thanksgiving|CORNUCOPIA development/ })).toBeVisible({ timeout: 30_000 });
  await page.context().storageState({ path: "e2e/.auth/approver.json" });
});
