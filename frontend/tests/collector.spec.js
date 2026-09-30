/**
 * What a collector asks, what it costs delivered, what left the shelf, and
 * what you already own.
 *
 * One spec for the September 2026 batch, because the pieces lean on each
 * other: the collector details read on a listing are what the inventory
 * filters by and what a collection values like with like, and the delivered
 * price is on the same page as "I bought this".
 */
import { test, expect, openPage } from "./fixtures.js";

const K98 = "GERMAN K98 Mauser rifle, matching numbers";

/**
 * Open the seeded listing with this title.
 *
 * Not the Demo Vendor's: its scraper has listings of the same names, and once
 * the scan test has run they are the newest -- with the fixture's one-line
 * description rather than the seeded prose these tests read.
 */
async function openListing(page, title) {
  await page.goto(`/?availability=all&search=${encodeURIComponent(`"${title}"`)}`);
  const card = page
    .locator(".item-card, .item-row", { hasText: title })
    .filter({ hasNotText: "Demo Vendor" })
    .first();
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.locator(".detail__facts")).toBeVisible();
}

test.describe("collector details", () => {
  test("a listing quotes what its vendor said", async ({ signedIn }) => {
    await openListing(signedIn, K98);
    const facts = signedIn.locator(".detail__facts");
    await expect(facts).toContainText("Very good");
    await expect(facts).toContainText("Overall condition is very good");
    await expect(facts).toContainText("All matching");
    await expect(facts.locator(".fact__quote").first()).toBeVisible();
  });

  test("the inventory filters by them", async ({ signedIn }) => {
    await signedIn.goto("/?availability=all");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();
    await signedIn.locator("summary", { hasText: "Collector details" }).click();
    await expect(signedIn.locator(".facet__group", { hasText: "Numbers" })).toBeVisible();
    await signedIn.getByRole("checkbox", { name: /All matching/ }).check();
    await expect(signedIn.locator(".item-card, .item-row").first()).toContainText(
      /matching/i,
    );
    await expect(signedIn.locator(".active-filters")).toContainText("All matching");

    await signedIn.locator("summary", { hasText: "Condition" }).click();
    await signedIn.getByRole("checkbox", { name: /Excellent/ }).check();
    await expect(signedIn.locator(".item-card, .item-row")).toHaveCount(1);
    await expect(signedIn.locator(".item-card, .item-row").first()).toContainText("K31");
  });
});

test.describe("delivered price", () => {
  test("a missing part is named, and the fee is set where it is used", async ({
    signedIn,
  }) => {
    await openListing(signedIn, K98);
    const delivered = signedIn.getByTestId("delivered-price");
    await expect(delivered).toContainText("At least");
    await expect(delivered).toContainText("your transfer fee");

    await delivered.getByRole("button", { name: /Set your fee|Change fee/ }).click();
    await signedIn.getByLabel("Your dealer’s transfer fee").fill("-3");
    await delivered.getByRole("button", { name: "Save" }).click();
    await expect(delivered.locator(".alert--error")).toBeVisible();

    await signedIn.getByLabel("Your dealer’s transfer fee").fill("25");
    await delivered.getByRole("button", { name: "Save" }).click();
    await expect(delivered).toContainText("$25");
    await expect(delivered.getByRole("button", { name: "Change fee" })).toBeVisible();
    await expect(delivered).toContainText("$25 transfer");

    await delivered.getByRole("button", { name: "Change fee" }).click();
    await delivered.getByRole("button", { name: "Cancel" }).click();
    await expect(delivered.locator("form")).toHaveCount(0);
  });

  test("an administrator can override a shop's shipping", async ({ signedIn }) => {
    await openPage(signedIn, "Sites");
    await signedIn.getByRole("link", { name: "History", exact: true }).first().click();
    const panel = signedIn.getByTestId("site-shipping");
    await expect(panel).toBeVisible();
    await panel.getByRole("button", { name: "Change" }).click();
    await panel.getByLabel("Long gun ($)").fill("33");
    await panel.getByLabel("Note").fill("Set by hand in a test");
    await panel.getByRole("button", { name: "Save" }).click();
    await expect(panel).toContainText("$33");
    await expect(panel).toContainText("Overridden");

    await panel.getByRole("button", { name: "Change" }).click();
    await panel.getByRole("button", { name: "Back to the declared figures" }).click();
    await expect(panel).not.toContainText("Overridden");
  });
});

test.describe("what left the shelf", () => {
  test("the market page has its own section", async ({ signedIn }) => {
    await openPage(signedIn, "Market");
    const section = signedIn.locator("section", {
      has: signedIn.getByRole("heading", { name: "What they left the shelf at" }),
    });
    await expect(section).toBeVisible();
    await expect(
      section.getByTestId("departures-empty").or(section.getByTestId("departures-table")),
    ).toBeVisible();
    await section.getByRole("tab", { name: "Caliber" }).click();
    await expect(section.getByRole("tab", { name: "Caliber" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

test.describe("want lists", () => {
  test("a search saved with the alert on says it is a want list", async ({
    signedIn,
  }) => {
    await signedIn.goto("/?kind=rifle&max_price=900");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();
    await signedIn.getByRole("button", { name: "Save this search" }).click();
    await signedIn.getByLabel("Name for this search").fill("Rifles under 900");
    await signedIn.getByLabel("Alert me the moment a new one appears").check();
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();
    await expect(signedIn.locator(".alert--success")).toContainText("Rifles under 900");

    await signedIn.goto("/saved-searches");
    const card = signedIn.locator(".saved-search", { hasText: "Rifles under 900" });
    await expect(card.locator(".saved-search__note--alert")).toContainText("$900");

    await card.getByLabel("Alert me the moment one appears").uncheck();
    await expect(card.locator(".saved-search__note--alert")).toHaveCount(0);
  });

  test("the filters it keeps are described in words", async ({ signedIn }) => {
    await signedIn.goto("/?trait=all_matching&grade=excellent");
    await expect(signedIn.getByText(/listings? match your filters/)).toBeVisible();
    await signedIn.getByRole("button", { name: "Save this search" }).click();
    await signedIn.getByLabel("Name for this search").fill("Clean and matching");
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();
    await signedIn.goto("/saved-searches");
    await expect(
      signedIn
        .locator(".saved-search", { hasText: "Clean and matching" })
        .locator(".saved-search__filters"),
    ).toContainText("Details: All matching");
  });
});

test.describe("the collection", () => {
  test("added by hand, valued or not, edited and removed", async ({ signedIn }) => {
    await openPage(signedIn, "Collection");
    await signedIn.getByRole("button", { name: "Add a gun" }).click();
    const dialog = signedIn.getByRole("dialog");
    await dialog.getByLabel("What it is").fill("Grandad's Mosin M91/30");
    await dialog.getByLabel("Paid").fill("250");
    await dialog.getByLabel("Condition").selectOption("good");
    await dialog.getByLabel("When").fill("2019-05-04");
    await dialog.getByLabel("Where from").fill("A gun show");
    await dialog.getByLabel("Notes").fill("Cleaned twice.");
    await dialog.getByRole("button", { name: "Save" }).click();

    const row = signedIn.locator("tr", { hasText: "Grandad's Mosin" });
    await expect(row).toBeVisible();
    await expect(row).toContainText("$250");
    await expect(signedIn.getByTestId("collection-totals")).toContainText("paid");

    await row
      .getByRole("button", { name: "Grandad's Mosin M91/30", exact: true })
      .click();
    const editor = signedIn.getByRole("dialog");
    const notIt = editor.getByRole("button", { name: "That is not it" });
    if (await notIt.isVisible()) {
      await notIt.click();
      await expect(editor).toContainText("cannot be valued");
      await editor.getByRole("button", { name: "Match it again" }).click();
    }
    await editor.getByLabel("Paid").fill("275");
    await editor.getByRole("button", { name: "Save" }).click();
    await expect(row).toContainText("$275");

    await expect(signedIn.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/collection/export",
    );

    await row.getByRole("button", { name: /^Remove/ }).click();
    await signedIn.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
    await expect(signedIn.locator("tr", { hasText: "Grandad's Mosin" })).toHaveCount(0);
  });

  test("I bought this, from a listing", async ({ signedIn }) => {
    await openListing(signedIn, K98);
    await signedIn.getByRole("button", { name: "I bought this" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText("collection");
    await signedIn.getByRole("link", { name: "Open it" }).click();
    await expect(signedIn.locator("tr", { hasText: K98 })).toBeVisible();

    // Leave it as found for whoever runs next.
    const row = signedIn.locator("tr", { hasText: K98 }).first();
    await row.getByRole("button", { name: /^Remove/ }).click();
    await signedIn.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
  });
});

test.describe("the navigation", () => {
  test("is grouped, with the administration last", async ({ signedIn }) => {
    const rail = signedIn.getByRole("navigation", { name: "Main navigation" });
    const headings = rail.locator(".rail__heading");
    await expect(headings).toHaveText(["Catalog", "Yours", "Account", "Administration"]);
    await expect(rail.getByRole("list", { name: "Yours" }).getByRole("link")).toHaveText([
      "Saved searches",
      "Watchlist",
      "Collection",
    ]);
  });
});
