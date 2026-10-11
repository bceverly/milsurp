/**
 * Ammunition information: what a caliber costs to shoot, from the Armory and
 * from a listing, and the administrator's refresh on the Settings page.
 * What the figures are is the server's business (app/services/ammunition.py);
 * these tests hold the panel's shape, so its answer is supplied here.
 */
import { test, expect, openPage } from "./fixtures.js";

const FACTS = {
  caliber_id: 1,
  caliber: "7.62x54R",
  wikipedia_url: "https://en.wikipedia.org/wiki/7.62%C3%9754mmR",
  bullet_diameter_in: 0.3118,
  bullet_weights: [
    { grains: 150, source: "wikipedia", factory_cpr: 0.5437, projectile_cost: 0.196 },
    { grains: 174, source: "wikipedia", factory_cpr: null, projectile_cost: 0.2732 },
  ],
  factory_cpr: 0.6715,
  factory_source: "ammoseek",
  factory_url: "https://ammoseek.com/ammo/7.62x54r",
  factory_checked_at: new Date().toISOString(),
  lee_dies: true,
  lee_url: "https://leeprecision.com/762x54r-dies",
  lee_checked_at: new Date().toISOString(),
  projectile_cost: 0.2466,
  projectile_url: "https://ammoseek.com/",
  projectile_checked_at: new Date().toISOString(),
};

async function answerWith(page, facts) {
  await page.route(/\/api\/ammunition\?caliber=/, (route) =>
    route.fulfill({ json: facts }),
  );
}

test("a listing's caliber opens what it costs to shoot", async ({ signedIn }) => {
  await answerWith(signedIn, FACTS);
  await signedIn.goto("/?availability=all");
  await signedIn.locator(".item-card").first().click();
  await expect(signedIn.locator(".detail__facts")).toBeVisible();
  await signedIn.getByRole("button", { name: /^Ammunition information for / }).click();
  const panel = signedIn.getByTestId("ammunition-panel");
  await expect(panel).toContainText('.312" (7.92 mm)');
  await expect(panel.getByTestId("ammo-factory")).toContainText("67¢ a round");
  await expect(panel.getByTestId("ammo-factory").getByRole("link")).toHaveText(
    "AmmoSeek",
  );
  await expect(panel.getByTestId("ammo-dies")).toContainText("Lee Precision makes them");
  await expect(panel.getByTestId("ammo-projectiles")).toContainText("25¢ each");
  // Per weight; a weight nobody offers says so rather than showing zero.
  await expect(panel.locator("tbody tr")).toHaveCount(2);
  await expect(panel.locator("tbody tr").nth(1)).toContainText("—");
});

test("an unknown figure says so rather than leaving a blank", async ({ signedIn }) => {
  await answerWith(signedIn, {
    ...FACTS,
    bullet_diameter_in: null,
    bullet_weights: [],
    factory_cpr: null,
    lee_dies: null,
    projectile_cost: null,
  });
  await signedIn.goto("/?availability=all");
  await signedIn.locator(".item-card").first().click();
  await signedIn.getByRole("button", { name: /^Ammunition information for / }).click();
  const panel = signedIn.getByTestId("ammunition-panel");
  await expect(panel.getByText("not known yet")).toHaveCount(4);
});

test("each caliber in the Armory has the same button", async ({ signedIn }) => {
  await answerWith(signedIn, FACTS);
  await openPage(signedIn, "Armory");
  // A caliber of its own, rather than the shipped armory: loading that puts
  // hundreds of pending rows ahead of the specs that run after this one.
  const name = `Ammo Test ${Date.now()}`;
  const csrf = (await signedIn.context().cookies()).find(
    (c) => c.name === "milsurp_csrf",
  );
  const made = await signedIn.request.post("/api/armory/calibers", {
    headers: csrf ? { "X-CSRF-Token": csrf.value } : {},
    data: { name },
  });
  expect(made.ok()).toBe(true);
  await signedIn.getByRole("tab", { name: "Calibers" }).click();
  await signedIn.getByLabel("Search").fill(name);
  await expect(signedIn).toHaveURL(/[?&]q=/);
  const row = signedIn.locator("tbody tr", { hasText: name });
  await row.getByRole("button", { name: `Ammunition information for ${name}` }).click();
  await expect(signedIn.getByTestId("ammunition-panel")).toContainText("67¢ a round");
  // The Armory remembers its tab, and the specs after this one expect Models.
  await signedIn.keyboard.press("Escape");
  await signedIn.getByRole("tab", { name: "Models" }).click();
  await expect(signedIn.getByRole("tab", { name: "Models" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("an administrator sets how often the caliber data refreshes", async ({
  signedIn,
}) => {
  await signedIn.goto("/settings");
  const panel = signedIn.getByTestId("caliber-data");
  const select = panel.getByLabel("Refresh");
  await expect(select).toHaveValue("7");
  await select.selectOption("14");
  await expect(select).toHaveValue("14");
  await signedIn.reload();
  await expect(signedIn.getByTestId("caliber-data").getByLabel("Refresh")).toHaveValue(
    "14",
  );
  await signedIn.getByTestId("caliber-data").getByLabel("Refresh").selectOption("7");

  await signedIn.getByRole("button", { name: "Refresh now" }).click();
  await expect(
    signedIn.getByText("A full refresh starts within a minute."),
  ).toBeVisible();
  await expect(
    signedIn.getByRole("button", { name: "Refresh asked for" }),
  ).toBeDisabled();
});
