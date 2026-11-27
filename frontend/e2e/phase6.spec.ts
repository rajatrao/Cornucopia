import { expect, type APIRequestContext, test } from "@playwright/test";

import { e2eSecret } from "./secrets";

// Full approval loop on the real stack: an operator reports a donation, the
// agent on the Sprite proposes a recovery, an operator without approval rights
// is refused (and recorded), the approver confirms, the agent commits
// atomically, and the Command Center shows the committed plan.
test.describe.configure({ mode: "serial" });

async function latestPending(request: APIRequestContext, after: number) {
  const rows = await (await request.get("/api/ops/approvals?limit=10")).json();
  return rows.find((r: { status: string; created_at: string }) => r.status === "pending" && Date.parse(r.created_at) >= after);
}

test("approval loop: propose, refuse unauthorized, confirm, commit", async ({ page, request, browser }) => {
  test.setTimeout(420_000);
  const run = Date.now().toString(36);
  const start = Date.now() - 5_000;
  const ings = await (await request.get("/api/ops/resources/ingredients")).json();
  const quinoa = ings.find((i: { name: string }) => i.name === "[sample] Quinoa");
  const ev = await request.post("/api/ops/events", {
    data: { idempotency_key: `e2e-p6-quinoa-${run}`, event: { type: "DONATION_CREATED", description: `[e2e] quinoa ${run}`, received: true, lots: [{ ingredient_id: quinoa.id, quantity: "100", unit: "lb" }] } },
  });
  expect(ev.status()).toBe(201);

  let pending: { id: string; fingerprint: string; state_version: number } | undefined;
  await expect
    .poll(async () => (pending = await latestPending(request, start)) !== undefined, { timeout: 240_000, intervals: [4_000] })
    .toBe(true);

  // an operator (not an approver) is refused, and the refusal is recorded
  const ctx = await browser.newContext();
  const login = await ctx.request.post("/api/auth/login", { data: { username: "e2e-operator", password: e2eSecret("E2E_OPERATOR_PASSWORD") } });
  expect(login.status()).toBe(200);
  const refused = await ctx.request.post(`/api/ops/approvals/${pending!.id}/decision`, {
    data: { decision: "approve", fingerprint: pending!.fingerprint, state_version: pending!.state_version, confirm: true },
  });
  expect(refused.status()).toBe(403);
  await ctx.close();

  await page.goto("/approvals");
  await page.getByRole("button", { name: /Proposal v\d+ pending/ }).first().click();
  const detail = page.getByRole("region", { name: "Proposal detail" });
  await expect(detail).toContainText("refused (unauthorized)");
  const approve = detail.getByRole("button", { name: "Approve and commit" });
  await expect(approve).toBeDisabled(); // explicit confirmation required
  await detail.getByRole("checkbox").check();
  await approve.click();
  await expect(detail.getByRole("status")).toContainText("Approved");

  // the agent on the Sprite resumes and commits
  await expect
    .poll(async () => (await (await request.get(`/api/ops/approvals/${pending!.id}`)).json()).request.status, { timeout: 180_000, intervals: [4_000] })
    .toBe("committed");
  await page.goto("/");
  await expect(page.getByLabel("Operation summary")).toContainText(/plan v\d+/);

  // restore the sample state for the next run: cancel our donation (the agent proposes again)
  const donations = await (await request.get("/api/ops/inventory/donations")).json();
  const mine = donations.find((d: { description: string }) => d.description === `[e2e] quinoa ${run}`);
  await request.post("/api/ops/events", { data: { idempotency_key: `e2e-p6-cancel-${run}`, event: { type: "DONATION_CANCELLED", donation_id: mine.id, reason: "[e2e] cleanup" } } });
});
