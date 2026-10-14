/**
 * A model's variants: edited in the model's dialog on the Armory page, and
 * shown on a listing as the version it is, or the versions it could be.
 * Which variant a listing matches is the server's business
 * (app/services/variants.py).
 */
import { test, expect } from "./fixtures.js";
import { searchFor, openArmoryModels } from "./armory-helpers.js";

async function openListingWith(page, changes) {
  await page.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), ...changes } });
  });
  await page.goto("/?availability=all");
  await page.locator(".item-card").first().click();
  await expect(page.locator(".detail__facts")).toBeVisible();
}

test("a listing names the version it is, with its MSRP", async ({ signedIn }) => {
  await openListingWith(signedIn, {
    barrel_inches: 4,
    barrel_quotes: { length: 'Used TAURUS TRACKER 44MAG 4" STAINLESS' },
    finish: "Stainless",
    variant: {
      id: 1,
      label: 'Tracker .44 Magnum 4" Stainless',
      msrp: 599.99,
      maker_url: "https://www.taurususa.com/tracker",
      upc: null,
    },
  });
  const note = signedIn.getByTestId("variant-note");
  await expect(note).toContainText("This version · MSRP $599.99");
  const row = note.locator("tbody tr");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText('Tracker .44 Magnum 4" Stainless');
  await expect(row.locator("td").nth(1)).toHaveText("$599.99");
  await expect(row.getByRole("link", { name: "manufacturer’s page" })).toHaveAttribute(
    "href",
    "https://www.taurususa.com/tracker",
  );
  const facts = signedIn.locator(".detail__facts");
  await expect(facts).toContainText('4"');
  await expect(facts).toContainText("Stainless");
});

test("a vague listing shows a table of the versions it could be", async ({
  signedIn,
}) => {
  await openListingWith(signedIn, {
    barrel_inches: null,
    variant: null,
    variant_candidates: [
      { id: 1, label: 'Tracker .44 4" Black', msrp: 549.99 },
      { id: 2, label: 'Tracker .44 4" Stainless', msrp: 599.99 },
      { id: 3, label: 'Tracker .44 6.5" Black', msrp: null },
    ],
  });
  const note = signedIn.getByTestId("variant-note");
  await expect(note).toContainText("Could be any of 3 versions · MSRP $549.99–$599.99");
  await expect(note.getByRole("columnheader")).toHaveText([
    "Version",
    "MSRP",
    "Street price",
  ]);
  await expect(note.locator("tbody tr")).toHaveCount(3);
  await expect(note.locator("tbody tr").nth(2).locator("td").nth(1)).toHaveText("—");
});

test("each version's street price, and the heading labels both ranges", async ({
  signedIn,
}) => {
  await openListingWith(signedIn, {
    current_price: 450,
    barrel_inches: 4,
    variant: null,
    variant_candidates: [
      {
        id: 1,
        label: 'Tracker .44 4" Black',
        msrp: 549.99,
        new_price: 462.23,
        new_stores: 12,
        new_price_url: "https://gun.deals/search/apachesolr_search/1",
      },
      {
        id: 2,
        label: 'Tracker .44 4" Stainless',
        msrp: 599.99,
        new_price: null,
        new_stores: 0,
        new_price_url: "https://gun.deals/search/apachesolr_search/2",
      },
    ],
  });
  const note = signedIn.getByTestId("variant-note");
  await expect(note).toContainText(
    'Could be any of 2 versions (with its 4" barrel) · MSRP $549.99–$599.99 · Street price $462.23',
  );
  const first = note.locator("tbody tr").first();
  await expect(first.getByRole("link", { name: "$462.23 at 12 stores" })).toHaveAttribute(
    "href",
    "https://gun.deals/search/apachesolr_search/1",
  );
  await expect(note.locator("tbody tr").nth(1)).toContainText("None in stock");
  // Under the highest street price: nothing in red.
  await expect(signedIn.getByTestId("over-street-price")).toHaveCount(0);
});

test("a price above every street price new is red, and says by how much", async ({
  signedIn,
}) => {
  await openListingWith(signedIn, {
    current_price: 650,
    price_drop: 0,
    variant: null,
    variant_candidates: [
      { id: 1, label: "PDP Compact 4", msrp: 699, new_price: 501.25, new_stores: 95 },
      { id: 2, label: "PDP Pro SD 4.6", msrp: 999, new_price: 549.99, new_stores: 90 },
    ],
  });
  await expect(signedIn.getByTestId("over-street-price")).toHaveText(
    "(exceeds maximum street price for new by $100.01)",
  );
  await expect(signedIn.locator(".detail__price-now")).toHaveClass(
    /detail__price-now--over/,
  );
});

test("one version shows how far under its street price this listing is", async ({
  signedIn,
}) => {
  await openListingWith(signedIn, {
    current_price: 400,
    variant: {
      id: 1,
      label: 'Tracker .44 Magnum 4" Black',
      msrp: 549.99,
      maker_url: null,
      upc: "725327351238",
      new_price: 500,
      new_stores: 12,
      new_price_url: "https://gun.deals/search/apachesolr_search/725327351238",
    },
  });
  await expect(signedIn.getByTestId("variant-note")).toContainText(
    "Street price $500 · 20% under street price",
  );
});

test("variants are added, changed and removed in the model's dialog", async ({
  signedIn,
}) => {
  await openArmoryModels(signedIn);
  await signedIn.getByRole("button", { name: "Add model" }).click();
  const name = `Variant Test ${Date.now()}`;
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel("Modern production").check();
  await dialog.getByRole("button", { name: "Add, awaiting approval" }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);

  await searchFor(signedIn, name);
  const row = signedIn.locator("tbody tr", { hasText: name });
  await row.getByRole("button", { name, exact: true }).click();
  dialog = signedIn.getByRole("dialog");
  const editor = dialog.getByTestId("variants-editor");
  await editor.getByLabel("Variant", { exact: true }).fill(`${name} 4" Black`);
  await editor.getByLabel("Barrel (inches)").fill("4");
  await editor.getByLabel("Finish").selectOption("Black");
  await editor.getByLabel("MSRP").fill("549.99");
  await editor.getByLabel("Finish").selectOption("Black");
  await editor.getByRole("button", { name: "Add variant" }).click();
  await expect(editor.locator("tbody tr")).toHaveCount(1);
  await expect(editor).toContainText("$549.99");
  // Added by hand it is approved; one from a maker's site would wait here.
  await expect(editor.getByRole("button", { name: /^Approve / })).toHaveCount(0);

  await editor.getByRole("button", { name: `Edit ${name} 4" Black` }).click();
  await editor.getByLabel("MSRP").fill("529.99");
  await editor.getByRole("button", { name: "Save variant" }).click();
  await expect(editor).toContainText("$529.99");

  await editor.getByRole("button", { name: `Delete ${name} 4" Black` }).click();
  await expect(editor.locator("tbody tr")).toHaveCount(0);

  await dialog
    .getByRole("button", { name: /^Cancel|^Close/ })
    .first()
    .click();
  await signedIn.getByRole("button", { name: `Delete ${name}` }).click();
  await signedIn
    .getByRole("dialog")
    .getByRole("button", { name: /^Delete/ })
    .click();
  await expect(row).toHaveCount(0);
});

test("the Variants tab lists every model's, and approves them in bulk", async ({
  signedIn,
}) => {
  // Stubbed: the list, and what each action asks for (2026-10-14).
  let pending = [
    {
      id: 11,
      model_id: 1,
      model_name: "Walther PDP",
      label: 'PDP Full Size 4.5"',
      status: "pending",
      enabled: true,
      msrp: 699,
      frame_size: "Full size",
    },
    {
      id: 12,
      model_id: 2,
      model_name: "Smith & Wesson M&P 5.7",
      label: "M&P 5.7 FDE",
      status: "pending",
      enabled: true,
      msrp: 729,
    },
  ];
  const asked = [];
  await signedIn.route("**/api/armory/variants**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "POST") {
      const { ids } = request.postDataJSON();
      asked.push([url.pathname, ids]);
      pending = pending.filter((row) => !ids.includes(row.id));
      await route.fulfill({
        json: { changed: ids.length, items_restamped: 0, message: "" },
      });
      return;
    }
    await route.fulfill({
      json: url.searchParams.get("status") === "pending" ? pending : [],
    });
  });
  await openArmoryModels(signedIn);
  const tab = signedIn.getByRole("tab", { name: /^Variants/ });
  await expect(tab).toHaveText("Variants (2)");
  await tab.click();

  const list = signedIn.getByTestId("variants-tab");
  await expect(list.getByRole("heading")).toHaveText("Variants awaiting approval (2)");
  await expect(list.locator("tbody tr")).toHaveCount(2);
  await expect(list.locator("tbody tr").first()).toContainText("Walther PDP");

  await list.getByRole("button", { name: 'Approve PDP Full Size 4.5"' }).click();
  await expect.poll(() => asked).toEqual([["/api/armory/variants/approve", [11]]]);
  await expect(list.locator("tbody tr")).toHaveCount(1);
  await expect(tab).toHaveText("Variants (1)");

  await list.getByRole("checkbox", { name: "Select M&P 5.7 FDE" }).check();
  await list.getByRole("button", { name: "Switch off" }).click();
  await expect.poll(() => asked.length).toBe(2);
  expect(asked[1]).toEqual(["/api/armory/variants/disable", [12]]);
  await expect(list).toContainText("Nothing here.");
});

test("a version with no street price leaves the listing unflagged", async ({
  signedIn,
}) => {
  await openListingWith(signedIn, {
    current_price: 1675,
    price_drop: 0,
    variant: null,
    variant_candidates: [
      { id: 1, label: "PDP Pro SD 4.6", msrp: 999, new_price: 749.99, new_stores: 89 },
      { id: 2, label: "PDP Steel Frame 4.5", msrp: 1899, new_price: null, new_stores: 0 },
    ],
  });
  await expect(signedIn.getByTestId("variant-note")).toBeVisible();
  await expect(signedIn.getByTestId("over-street-price")).toHaveCount(0);
});
