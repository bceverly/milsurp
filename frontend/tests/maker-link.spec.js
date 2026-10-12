/**
 * Modern production, and the maker's page one click from a listing.
 *
 * Slice 1 of "New-gun prices, and the makers' own pages" in ROADMAP.md: a
 * reader looking at a used carry gun was searching Google for the maker's
 * page by hand. Which link a listing gets is the server's decision (see
 * services/makerlink.py and its tests); these check that the page shows what
 * it is sent, and that the armory edits the fields it is decided from.
 */
import { test, expect, openPage } from "./fixtures.js";
import { searchFor, openArmoryModels } from "./armory-helpers.js";

async function openListingWith(page, makerLink) {
  await page.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    const item = await response.json();
    item.maker_link = makerLink;
    await route.fulfill({ response, json: item });
  });
  await page.goto("/?availability=all");
  await page.locator(".item-card").first().click();
  await expect(page.locator(".detail__facts")).toBeVisible();
}

test.describe("the maker's page on a listing", () => {
  test("a search of the maker's own site, when the model has no page", async ({
    signedIn,
  }) => {
    const url = "https://www.google.com/search?q=site%3Ataurususa.com+Tracker";
    await openListingWith(signedIn, {
      url,
      kind: "search",
      maker: "Taurus",
      site: "taurususa.com",
    });
    const link = signedIn.getByTestId("maker-link");
    await expect(link).toHaveText("Search taurususa.com");
    await expect(link).toHaveAttribute("href", url);
    await expect(link).toHaveAttribute("target", "_blank");
  });

  test("the model's own page, when the armory has it", async ({ signedIn }) => {
    const url = "https://www.taurususa.com/revolvers/tracker";
    await openListingWith(signedIn, {
      url,
      kind: "page",
      maker: "Taurus",
      site: "taurususa.com",
    });
    const link = signedIn.getByTestId("maker-link");
    await expect(link).toHaveText("Taurus: product page");
    await expect(link).toHaveAttribute("href", url);
  });

  test("nothing at all for a gun no longer made", async ({ signedIn }) => {
    await openListingWith(signedIn, null);
    await expect(signedIn.getByRole("link", { name: /^View on / })).toBeVisible();
    await expect(signedIn.getByTestId("maker-link")).toHaveCount(0);
  });
});

test("the armory flags a model as still made and records its page", async ({
  signedIn,
}) => {
  await openArmoryModels(signedIn);
  await signedIn.getByRole("button", { name: "Add model" }).click();
  const name = `Modern Test ${Date.now()}`;
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel("Modern production").check();
  await dialog.getByLabel("Maker's page").fill("https://maker.example/carry");
  await dialog.getByRole("button", { name: "Add, awaiting approval" }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);

  await searchFor(signedIn, name);
  const row = signedIn.locator("tbody tr", { hasText: name });
  await expect(row.getByText("Still made")).toBeVisible();

  await row.getByRole("button", { name, exact: true }).click();
  dialog = signedIn.getByRole("dialog");
  await expect(dialog.getByLabel("Modern production")).toBeChecked();
  await expect(dialog.getByLabel("Maker's page")).toHaveValue(
    "https://maker.example/carry",
  );
  await dialog.getByLabel("Modern production").uncheck();
  await dialog.getByLabel("Maker's page").fill("");
  await dialog.getByRole("button", { name: /^Save/ }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);
  await expect(row.getByText("Still made")).toHaveCount(0);

  // Leave the armory as found.
  await signedIn.getByRole("button", { name: `Delete ${name}` }).click();
  await signedIn
    .getByRole("dialog")
    .getByRole("button", { name: /^Delete/ })
    .click();
  await expect(row).toHaveCount(0);
});

test("a maker's website is edited with the maker", async ({ signedIn }) => {
  await openPage(signedIn, "Armory");
  await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
  await signedIn.getByRole("button", { name: "Add manufacturer" }).click();
  const name = `Website Test ${Date.now()}`;
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel("Website").fill("websitetest.example");
  await dialog.getByRole("button", { name: "Add manufacturer" }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);

  await signedIn.getByLabel("Showing").selectOption("");
  await signedIn.getByLabel("Search").fill(name);
  await signedIn.getByRole("button", { name, exact: true }).click();
  dialog = signedIn.getByRole("dialog");
  // Saved as an address, scheme and all, whatever was typed.
  await expect(dialog.getByLabel("Website")).toHaveValue("https://websitetest.example");
  await dialog
    .getByRole("button", { name: /^Cancel|^Close/ })
    .first()
    .click();

  await signedIn.getByRole("button", { name: `Delete ${name}` }).click();
  await signedIn
    .getByRole("dialog")
    .getByRole("button", { name: /^Delete/ })
    .click();
  await expect(signedIn.getByRole("button", { name, exact: true })).toHaveCount(0);
});
