import { expect, test } from "@playwright/test";

// The agent runs on the Sprite as its own service. This test only talks to the
// UI/BFF: it reports an event, then watches the agent process it autonomously.
test("agent processes a reported event and shows its workflow timeline", async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const run = `${Date.now().toString(36)}-${info.project.name}`;
  const vol = await request.post("/api/ops/resources/volunteers", { data: { name: `[e2e] Driver ${run}`, role: "driver" } });
  expect(vol.status()).toBe(201);
  const ev = await request.post("/api/ops/events", {
    data: { idempotency_key: `e2e-p5-${run}`, event: { type: "VOLUNTEER_UNAVAILABLE", volunteer_id: (await vol.json()).id, reason: "[e2e] flu" } },
  });
  expect(ev.status()).toBe(201);
  const eventId = (await ev.json()).event.id;

  // wait for the autonomous agent (no UI involvement) to finish the execution
  await expect
    .poll(
      async () => {
        const rows = await (await request.get("/api/ops/agent/executions?limit=50")).json();
        return rows.find((r: { event_id: string }) => r.event_id === eventId)?.status ?? "none";
      },
      { timeout: 200_000, intervals: [3_000] },
    )
    .toBe("completed");

  await page.goto("/executions");
  await expect(page.getByLabel("Agent runtime")).toBeVisible();
  await page.getByRole("button", { name: /Execution volunteer unavailable completed/ }).first().click();
  const timeline = page.getByRole("list", { name: "Workflow timeline" });
  for (const node of ["receive_event", "validate_event", "analyze_dependencies", "assess_impact", "select_recovery_strategy", "record_outcome"]) {
    await expect(timeline).toContainText(node);
  }
  await expect(page.getByRole("region", { name: "Execution detail" })).toContainText("checkpoints");
});
