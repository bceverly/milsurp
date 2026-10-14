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
  factory_source: "ammo-com",
  factory_url: "https://ammo.com/rifle/7.62x54r-ammo",
  factory_checked_at: new Date().toISOString(),
  lee_dies: true,
  lee_url: "https://leeprecision.com/762x54r-dies",
  lee_checked_at: new Date().toISOString(),
  projectile_cost: 0.2466,
  projectile_url:
    "https://grafs.com/products/speer-303-311-150gr-sp-bullet-spitzer-100bx",
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
    "Ammo.com",
  );
  await expect(panel.getByTestId("ammo-projectiles").getByRole("link")).toHaveText(
    "Graf & Sons",
  );
  await expect(panel.getByTestId("ammo-dies")).toContainText("Lee Precision makes them");
  await expect(panel.getByTestId("ammo-projectiles")).toContainText("25¢ each");
  // Per weight; a weight nobody offers says so rather than showing zero.
  await expect(panel.locator("tbody tr")).toHaveCount(2);
  await expect(panel.locator("tbody tr").nth(1)).toContainText("—");
  // Sized to its content, and never a sideways scrollbar (asked 2026-10-12).
  const body = signedIn.locator(".modal--fit .modal__body");
  expect(await body.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  expect(await body.evaluate((el) => el.clientWidth)).toBeGreaterThan(440);
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
  // Diameter, factory, dies, projectiles, new brass and the primer.
  await expect(panel.getByText("not known yet")).toHaveCount(6);
  await expect(panel.getByTestId("ammo-powder")).toHaveText("no load entered yet");
  await expect(panel.getByTestId("ammo-reload")).toHaveText(
    "not known until all four parts are",
  );
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

test("an administrator updates the caliber data a part at a time, or all of it", async ({
  signedIn,
}) => {
  // On Site settings, not on the Armory, which was asked to stay clean
  // (2026-10-12): a button for each part and one for all of them.
  await openPage(signedIn, "Site settings");
  const section = signedIn.getByTestId("caliber-data-section");
  const often = section.getByLabel("How often");
  await expect(often).toHaveValue("7");
  await often.selectOption("14");
  await expect(often).toHaveValue("14");
  await signedIn.reload();
  await expect(section.getByLabel("How often")).toHaveValue("14");
  await section.getByLabel("How often").selectOption("7");
  await expect(section.getByLabel("How often")).toHaveValue("7");

  const asked = signedIn.waitForRequest(
    (request) =>
      request.url().endsWith("/api/ammunition/refresh") && request.method() === "POST",
  );
  await section.getByRole("button", { name: "Update reloading prices" }).click();
  expect((await asked).postDataJSON()).toEqual({ parts: ["reloading"] });
  await expect(
    signedIn.getByText("An update of reloading prices starts within a minute."),
  ).toBeVisible();
  // One at a time: everything waits until the scheduler has taken it.
  for (const name of [
    "Update all",
    "Update Wikipedia facts",
    "Update reloading prices",
    "Update ammo prices",
  ]) {
    await expect(section.getByRole("button", { name })).toBeDisabled();
  }
  // And none of it on the Armory any more.
  await openPage(signedIn, "Armory");
  await signedIn.getByRole("tab", { name: "Calibers" }).click();
  await expect(signedIn.getByTestId("caliber-data-section")).toHaveCount(0);
});

test("a reloaded round is its four parts, each linked to where it was priced", async ({
  signedIn,
}) => {
  await answerWith(signedIn, {
    ...FACTS,
    primer_size: "Large rifle",
    primer_magnum: false,
    primer_source: "wikipedia",
    primer_cost: 0.0438,
    primer_url: "https://grafs.com/products/large-rifle",
    brass_cost: 0.6598,
    brass_url: "https://grafs.com/products/prvi-7-62x54r-brass",
    brass_checked_at: new Date().toISOString(),
    powder_name: "Hodgdon Varget",
    powder_charge_gr: 46.5,
    powder_bullet_gr: 150,
    powder_cost: 0.34623,
    powder_url: "https://grafs.com/products/varget",
    powder_per_pound: 52.12,
    powder_in_stock: true,
    bullet_cost: 0.196,
    reload_cost: 1.2458,
  });
  await signedIn.goto("/?availability=all");
  await signedIn.locator(".item-card").first().click();
  await signedIn.getByRole("button", { name: /^Ammunition information for / }).click();
  const panel = signedIn.getByTestId("ammunition-panel");
  await expect(panel.getByTestId("ammo-brass")).toContainText("66¢ a case");
  await expect(panel.getByTestId("ammo-primer")).toContainText(
    "Large rifle (from the article) · 4¢ each",
  );
  await expect(panel.getByTestId("ammo-powder")).toContainText(
    "46.5 gr of Hodgdon Varget under a 150 gr bullet · 35¢ a charge ($52.12 a pound",
  );
  await expect(panel.getByTestId("ammo-powder").getByRole("link")).toHaveAttribute(
    "href",
    "https://grafs.com/products/varget",
  );
  await expect(panel.getByTestId("ammo-reload")).toContainText("$1.25 a round");
  await expect(panel.getByTestId("ammo-reload")).toContainText(
    "bullet 20¢ + brass 66¢ + powder 35¢ + primer 4¢",
  );
});

test("a caliber's load is typed on its dialog, the powder picked from Graf's", async ({
  signedIn,
}) => {
  await signedIn.route(/\/api\/ammunition\/powders$/, (route) =>
    route.fulfill({
      json: [
        { name: "Hodgdon H4895", unit_price: 53.75, url: null, in_stock: true },
        { name: "Hodgdon Varget", unit_price: 52.12, url: null, in_stock: true },
        { name: "IMR 3031", unit_price: 55.5, url: null, in_stock: false },
      ],
    }),
  );
  await openPage(signedIn, "Armory");
  const name = `Load Test ${Date.now()}`;
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
  await signedIn
    .locator("tbody tr", { hasText: name })
    .getByRole("button", { name, exact: true })
    .click();
  const dialog = signedIn.getByRole("dialog");
  const fields = dialog.getByTestId("caliber-reloading");
  const powder = fields.getByLabel("Powder");
  await expect(powder.locator("option")).toHaveText([
    "No load",
    "Hodgdon H4895 — $53.75/lb",
    "Hodgdon Varget — $52.12/lb",
    "IMR 3031 (out of stock)",
  ]);
  await powder.selectOption("Hodgdon Varget");
  await fields.getByLabel("Charge (grains)").fill("46.5");
  // The magnum box waits for a primer.
  await expect(fields.getByLabel("Magnum primer")).toBeDisabled();
  const saved = signedIn.waitForRequest(
    (request) =>
      /\/api\/armory\/calibers\/\d+$/.test(request.url()) && request.method() === "PATCH",
  );
  await dialog.getByRole("button", { name: "Save" }).click();
  const body = (await saved).postDataJSON();
  expect(body).toMatchObject({ powder_name: "Hodgdon Varget", powder_charge_gr: 46.5 });
  // A primer left alone is not sent: the article's stays the article's.
  expect(body).not.toHaveProperty("primer_size");
  // This server has read no powders from Graf & Sons, so it refuses the name.
  await expect(dialog.locator(".alert--error")).toContainText(
    "Graf & Sons has no powder called 'Hodgdon Varget'",
  );
  await signedIn.keyboard.press("Escape");
  await signedIn.getByRole("tab", { name: "Models" }).click();
  await expect(signedIn.getByRole("tab", { name: "Models" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});
