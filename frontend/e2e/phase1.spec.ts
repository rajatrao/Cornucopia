import { expect, test } from "@playwright/test";

test("shows live Sprite runtime and database health", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "CORNUCOPIA" })).toBeVisible();
  const runtime = page.locator("dl");
  await expect(runtime.getByText("sprite", { exact: true })).toBeVisible();
  await expect(runtime.getByText("gateway", { exact: true })).toBeVisible();
  await expect(runtime.getByText("ok", { exact: true })).toBeVisible();
});

test("writes a probe through the Sprite and reads it back", async ({ page }, info) => {
  const note = `e2e ${info.project.name} ${Date.now()}`;
  await page.goto("/");
  await page.getByLabel("Probe note").fill(note);
  await page.getByRole("button", { name: "Write probe" }).click();
  await expect(page.getByText(note)).toBeVisible({ timeout: 20_000 });
});

test("browser never receives backend credentials", async ({ page }) => {
  const bodies: string[] = [];
  page.on("response", async (r) => {
    if ((r.headers()["content-type"] ?? "").match(/javascript|html|json/)) {
      bodies.push(await r.text().catch(() => ""));
    }
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  const all = bodies.join("\n");
  for (const needle of ["sb_secret", "api.sprites.dev", "supabase.co", "Bearer "]) {
    expect(all, needle).not.toContain(needle);
  }
});

test("rejects invalid probe input server side", async ({ request }) => {
  const res = await request.post("/api/probes", { data: { note: "" } });
  expect(res.status()).toBe(422);
});
