import { expect, test } from "@playwright/test";

// Real stack, dev organization with the labelled [sample] Thanksgiving data
// (scripts/seed_sample.py). Each run adds a rice donation, verifies the
// compiled plan, cancels it again and inspects the dependency impact.
test.describe.configure({ mode: "serial" });

let run = Date.now().toString(36);
let donationEventId = "";
let cancelEventId = "";

test.beforeAll(async ({ request }, info) => {
  run = `${Date.now().toString(36)}-${info.project.name}`;
  const ings = await (await request.get("/api/ops/resources/ingredients")).json();
  const rice = ings.find((i: { name: string }) => i.name === "[sample] Rice");
  expect(rice, "sample data seeded").toBeTruthy();
  const res = await request.post("/api/ops/events", {
    data: {
      idempotency_key: `e2e-p3-rice-${run}`,
      event: { type: "DONATION_CREATED", description: `[e2e] rice ${run}`, received: true, lots: [{ ingredient_id: rice.id, quantity: "180", unit: "lb" }] },
    },
  });
  expect(res.status()).toBe(201);
  donationEventId = (await res.json()).event.id;
});

test("baseline plan with rice is fully feasible and validated", async ({ page }) => {
  await page.goto("/compiler");
  const summary = page.getByRole("definition").first();
  await expect(summary).toHaveText("500 / 500", { timeout: 20_000 });
  await expect(page.getByText(/valid · \d+ checks/)).toBeVisible();
  const table = page.getByRole("table", { name: "Commitment feasibility" });
  await expect(table.getByRole("row", { name: /Riverside Shelter/ })).toContainText("feasible");
  await expect(table.getByRole("row", { name: /Oak Street Senior Center/ })).toContainText("omits");
});

test("cancelling the rice is recompiled into infeasibility with a shortage", async ({ page, request }) => {
  const donations = await (await request.get("/api/ops/inventory/donations")).json();
  const mine = donations.find((d: { description: string }) => d.description === `[e2e] rice ${run}`);
  const res = await request.post("/api/ops/events", {
    data: { idempotency_key: `e2e-p3-cancel-${run}`, event: { type: "DONATION_CANCELLED", donation_id: mine.id, reason: "[e2e] rice donation cancelled" } },
  });
  expect(res.status()).toBe(201);
  cancelEventId = (await res.json()).event.id;

  await page.goto("/compiler");
  await expect(page.getByRole("definition").first()).toHaveText("0 / 500", { timeout: 20_000 });
  const table = page.getByRole("table", { name: "Commitment feasibility" });
  await expect(table.getByRole("row", { name: /Riverside Shelter/ })).toContainText("infeasible");
  await expect(table.getByRole("row", { name: /Riverside Shelter/ })).toContainText("ingredients: [sample] Rice");
  await expect(page.getByRole("table", { name: "Ingredient balance" }).getByRole("row", { name: /\[sample\] Rice/ })).toContainText("short 120.0 lb");
  await expect(page.getByText(/replace \[sample\] Rice with \[sample\] Quinoa/)).toBeVisible();
});

test("impact analysis follows the dependency graph", async ({ page }) => {
  await page.goto("/compiler");
  await page.locator("#impact-event").selectOption(cancelEventId);
  const panel = page.getByLabel("Impact analysis");
  await expect(panel).toContainText("3 commitment(s) affected");
  await expect(panel).toContainText("[sample] Rice pilaf");
  await expect(panel).not.toContainText("[sample] Mashed potatoes");
  expect(donationEventId).not.toBe("");
});
