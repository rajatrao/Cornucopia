import { expect, type Page, test } from "@playwright/test";

// Runs against the real stack: Next.js -> Sprite API -> Sprites connector ->
// Supabase (development organization). Records are labelled [e2e].
test.describe.configure({ mode: "serial" });

const stamp = Date.now().toString(36);
let run = stamp;
let potato = "";
let recipe = "";
test.beforeEach(({}, info) => {
  run = `${stamp}-${info.project.name}`;
  potato = `[e2e] Potatoes ${run}`;
  recipe = `[e2e] Mash ${run}`;
});
const esc = (s: string) => new RegExp(s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

// select by element id: a <label> wrapping a <select> also contains every option's text
async function pick(page: Page, id: string, option: string) {
  const select = page.locator(`#${id}`);
  const label = id;
  const find = () =>
    select.evaluate(
      (el, text) => [...(el as HTMLSelectElement).options].find((o) => o.text.includes(text))?.value ?? "",
      option,
    );
  await expect.poll(find, { message: `option "${option}" in ${label}`, timeout: 20_000 }).not.toBe("");
  const value = await find();
  await select.selectOption(value);
}

test("resource CRUD through the UI", async ({ page }) => {
  await page.goto("/resources?kind=ingredients");
  const form = page.getByRole("form", { name: /Add Ingredients/ });
  await form.getByLabel("Name").fill(potato);
  await form.getByLabel("Category").selectOption("vegetable");
  await form.getByLabel("Base unit").selectOption("g");
  await form.getByLabel("Unit weight (g each)").fill("213");
  await form.getByRole("button", { name: "Create" }).click();
  await expect(page.locator("main").getByRole("status")).toHaveText("Created.");
  await expect(page.getByRole("cell", { name: potato, exact: true })).toBeVisible();

  await page.getByRole("button", { name: `Edit ${potato}` }).click();
  await expect(page.getByLabel("Base unit")).toHaveCount(0); // immutable after creation
  await page.getByRole("form", { name: /^Edit/ }).getByText("soy", { exact: true }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.locator("main").getByRole("status")).toHaveText("Saved.");
  await expect(page.getByRole("row", { name: esc(potato) })).toContainText("soy");

  await page.getByRole("button", { name: "Recipes", exact: true }).click();
  await page.getByLabel("Name").fill(recipe);
  await page.getByLabel("Yield (portions per batch)").fill("40");
  await page.getByLabel("Prep time per batch (min)").fill("50");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("cell", { name: recipe, exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Recipe ingredients", exact: true }).click();
  await pick(page, "f-recipe_id", recipe);
  await pick(page, "f-ingredient_id", potato);
  await page.getByLabel("Quantity").fill("10");
  await page.getByLabel("Unit").selectOption("cup");
  await page.getByRole("button", { name: "Create" }).click();
  // volume -> mass without a density is refused, not guessed
  await expect(page.locator("main").getByRole("alert")).toContainText("density");
  await page.getByLabel("Unit").selectOption("lb");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.locator("main").getByRole("status")).toHaveText("Created.");
  const riRow = page.getByRole("row", { name: esc(recipe) });
  await expect(riRow).toContainText("4535.924");

  page.once("dialog", (d) => void d.accept());
  await riRow.getByRole("button", { name: /^Delete/ }).click();
  await expect(page.locator("main").getByRole("status")).toHaveText("Deleted.");
});

test("donation event is journaled once and moves inventory", async ({ page }) => {
  await page.goto("/events");
  await page.getByLabel("Description").fill(`[e2e] potato donation ${run}`);
  await pick(page, "ev-lot-ing-0", potato);
  await page.getByLabel("Quantity").fill("120");
  await page.getByLabel("Unit").selectOption("lb");
  const submit = page.getByRole("button", { name: "Submit event" });
  await submit.click();
  await expect(page.locator("main").getByRole("status")).toContainText("Event journaled and applied");
  // same form, same idempotency key: a double submit must not apply twice
  await submit.click();
  await expect(page.locator("main").getByRole("status")).toContainText("Already recorded");

  await page.goto("/inventory");
  const card = page.getByRole("article", { name: `${potato} stock` });
  await expect(card).toContainText("120.0 lb");
  await expect(page.getByRole("row", { name: esc(potato) })).toHaveCount(1);
});

test("cancelling the donation removes its stock; integrity blocks deletes", async ({ page }) => {
  await page.goto("/events");
  await page.getByLabel("What happened?").selectOption("DONATION_CANCELLED");
  await pick(page, "ev-donation", `[e2e] potato donation ${run}`);
  await page.getByLabel("Reason").fill("[e2e] donor truck broke down");
  await page.getByRole("button", { name: "Submit event" }).click();
  await expect(page.locator("main").getByRole("status")).toContainText("lots_removed");

  await page.goto("/inventory");
  await expect(page.getByRole("article", { name: `${potato} stock` })).toContainText("0.0 lb");

  await page.goto("/resources?kind=ingredients");
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: `Delete ${potato}` }).click();
  await expect(page.locator("main").getByRole("alert")).toBeVisible(); // lots still reference it

  await page.goto("/history");
  await expect(page.getByRole("table", { name: "Audit log" })).toContainText("operator:e2e-approver");
});

test("event forms refuse incomplete facts", async ({ page }) => {
  await page.goto("/events");
  await page.getByLabel("What happened?").selectOption("COMMITMENT_CHANGED");
  // required fields are enforced in the browser; the server enforces them too
  const res = await page.request.post("/api/ops/events", {
    data: { idempotency_key: `e2e-${run}-bad`, event: { type: "DONATION_CANCELLED", reason: "x" } },
  });
  expect(res.status()).toBe(422);
  const bogus = await page.request.get("/api/ops/../../health");
  expect(bogus.status()).toBe(404);
});
