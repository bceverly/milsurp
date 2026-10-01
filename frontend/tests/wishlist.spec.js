/**
 * The wishlist: guns somebody means to buy, priced to the door and set against
 * what they are worth.
 *
 * Adding, the fee and the license, and taking off run against the seeded
 * catalog. The demo market is too thin to value much, so the mixed states --
 * a gun sold since, a total that is only "at least", a waived fee, a loss --
 * are drawn from an answer the server would give, as collection-states does.
 */
import { test, expect, openPage } from "./fixtures.js";

async function clearWishlist(page) {
  await page.goto("/wishlist");
  await expect(page.getByRole("heading", { name: "Wishlist" })).toBeVisible();
  await expect(page.getByText("Loading…")).toHaveCount(0);
  const remove = page.getByRole("button", { name: /off the wishlist$/ });
  for (let left = await remove.count(); left > 0; left -= 1) {
    await remove.first().click();
    await expect(remove).toHaveCount(left - 1);
  }
}

test.describe("wishlist", () => {
  test.beforeEach(async ({ signedIn }) => {
    await clearWishlist(signedIn);
  });

  test("a listing is added from its page and taken off on the wishlist", async ({
    signedIn,
  }) => {
    await signedIn.goto("/?availability=all");
    const card = signedIn.locator(".item-card").first();
    await expect(card).toBeVisible();
    await card.click();
    await expect(signedIn.locator(".detail__facts")).toBeVisible();
    const title = await signedIn.locator("h1").first().innerText();

    await signedIn.getByRole("button", { name: "Add to wishlist", exact: true }).click();
    const on = signedIn.getByRole("button", { name: "On your wishlist" });
    await expect(on).toHaveAttribute("aria-pressed", "true");

    await signedIn.getByRole("link", { name: "See the wishlist" }).click();
    const table = signedIn.getByTestId("wishlist-table");
    await expect(table).toContainText(title);
    await expect(signedIn.getByTestId("wishlist-totals")).toBeVisible();

    // The fee and the license are saved where they change the totals.
    const fee = signedIn.getByLabel("Your dealer’s transfer fee");
    await fee.fill("35");
    await fee.press("Enter");
    await expect(fee).toHaveValue("35");
    const license = signedIn.getByLabel(/I hold a C&R license/);
    await license.check();
    await expect(license).toBeChecked();
    await license.uncheck();
    await expect(license).not.toBeChecked();

    await signedIn
      .getByRole("button", { name: `Take ${title} off the wishlist` })
      .click();
    await expect(signedIn.getByText("Nothing here yet.")).toBeVisible();
  });

  test("taken off again from the listing's own page", async ({ signedIn }) => {
    await signedIn.goto("/?availability=all");
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn.locator(".detail__facts")).toBeVisible();
    await signedIn.getByRole("button", { name: "Add to wishlist", exact: true }).click();
    await signedIn.getByRole("button", { name: "On your wishlist" }).click();
    await expect(
      signedIn.getByRole("button", { name: "Add to wishlist", exact: true }),
    ).toBeVisible();
  });

  test("the cart on a browse card adds and removes", async ({ signedIn }) => {
    // Found by its listing's link rather than its title: two listings can
    // share a title, and the suite before this one may have made one.
    await signedIn.goto("/?availability=all");
    const first = signedIn.locator(".item-tile").first();
    await expect(first).toBeVisible();
    const href = await first.locator("a").first().getAttribute("href");
    const cart = (page) =>
      page
        .locator(".item-tile", { has: page.locator(`a[href="${href}"]`) })
        .locator(".wish-button");

    await expect(cart(signedIn)).toHaveAttribute("aria-pressed", "false");
    await cart(signedIn).click();
    await expect(cart(signedIn)).toHaveAttribute("aria-pressed", "true");
    await expect(cart(signedIn)).toHaveAttribute("aria-label", /^On your wishlist: /);

    // The list view has the cart too, in the state the server says.
    await signedIn.goto("/?availability=all&view=list");
    await expect(cart(signedIn)).toHaveAttribute("aria-pressed", "true");
    await cart(signedIn).click();
    await expect(cart(signedIn)).toHaveAttribute("aria-pressed", "false");
    await expect(cart(signedIn)).toHaveAttribute("aria-label", /^Add to wishlist: /);
  });

  test("bought it moves a gun to the collection", async ({ signedIn }) => {
    await signedIn.goto("/?availability=all");
    const first = signedIn.locator(".item-tile").first();
    await expect(first).toBeVisible();
    const href = await first.locator("a").first().getAttribute("href");
    const title = await first.locator(".item-card__title").innerText();
    await first.locator(".wish-button").click();
    await expect(first.locator(".wish-button")).toHaveAttribute("aria-pressed", "true");

    await signedIn.goto("/wishlist");
    await expect(signedIn.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/wishlist/export",
    );
    const row = signedIn.locator("tr", { has: signedIn.locator(`a[href="${href}"]`) });
    await row.getByRole("button", { name: /^Bought / }).click();
    await expect(signedIn.getByRole("status")).toContainText("is in your collection");
    await expect(signedIn.getByText("Nothing here yet.")).toBeVisible();

    // Leave the collection as found.
    await signedIn.getByRole("link", { name: "Open it" }).click();
    const owned = signedIn.locator("tr", { hasText: title }).last();
    await owned.getByRole("button", { name: /^Remove/ }).click();
    await signedIn.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
  });

  test("the budget and the alerts are saved", async ({ signedIn }) => {
    await signedIn.goto("/wishlist");
    const budget = signedIn.getByLabel("Your budget");
    await budget.fill("2000");
    await budget.press("Enter");
    await expect(budget).toHaveValue("2000");
    // Saved, not only typed: a reload reads it back from the server.
    await expect(async () => {
      await signedIn.reload();
      await expect(budget).toHaveValue("2000", { timeout: 2_000 });
    }).toPass({ timeout: 15_000 });
    await budget.fill("");
    await budget.press("Enter");
    await expect(async () => {
      await signedIn.reload();
      await expect(budget).toHaveValue("", { timeout: 2_000 });
    }).toPass({ timeout: 15_000 });
    const alerts = signedIn.getByLabel(/the moment one sells/);
    await alerts.check();
    await expect(alerts).toBeChecked();
    await signedIn.reload();
    await expect(signedIn.getByLabel(/the moment one sells/)).toBeChecked();
    await signedIn.getByLabel(/the moment one sells/).uncheck();
    await expect(signedIn.getByLabel(/the moment one sells/)).not.toBeChecked();
  });

  test("the nav leads there", async ({ signedIn }) => {
    await openPage(signedIn, "Wishlist");
    await expect(signedIn.getByRole("heading", { name: "Wishlist" })).toBeVisible();
  });
});

test.describe("wishlist states", () => {
  const item = (id, title, extra = {}) => ({
    id,
    title,
    site_id: 1,
    site_name: "Shop W",
    url: "https://x.test",
    current_price: 500,
    currency: "USD",
    is_rifle: true,
    is_pistol: false,
    is_sold: false,
    is_active: true,
    first_seen_at: "2026-09-20T12:00:00Z",
    last_seen_at: "2026-09-30T12:00:00Z",
    ...extra,
  });
  const valuation = (estimate, basis, like) => ({
    estimate,
    basis,
    like_for_like: like,
    shelf: null,
    departed: null,
  });
  const line = (overrides) => ({
    added_at: "2026-09-30T12:00:00Z",
    for_sale: true,
    price: 500,
    shipping: 30,
    shipping_note: null,
    curio: "eligible",
    fee: 25,
    fee_waived: false,
    fee_missing: false,
    total: 555,
    complete: true,
    valuation: null,
    profit: null,
    ...overrides,
  });

  test("gains, losses, the gone and the incomplete", async ({ signedIn }) => {
    await signedIn.route("**/api/wishlist", (route) =>
      route.fulfill({
        json: {
          ffl_transfer_fee: null,
          has_cr_license: true,
          wishlist_alerts: true,
          budget: 1000,
          lines: [
            line({
              item: item(1, "Swiss K31"),
              fee: null,
              fee_waived: true,
              total: 530,
              valuation: valuation(700, "left", true),
              profit: 170,
              since_added: -50,
            }),
            line({
              item: item(2, "Mosin M91/30"),
              shipping: null,
              shipping_note: "Calculated at checkout",
              curio: "unknown",
              fee: null,
              fee_missing: true,
              total: 500,
              complete: false,
              valuation: valuation(400, "shelf", false),
              profit: -100,
              since_added: 20,
            }),
            line({
              item: item(3, "Sold Enfield", { is_sold: true, is_active: false }),
              for_sale: false,
            }),
            line({
              item: item(4, "Delisted Garand", { is_active: false }),
              for_sale: false,
            }),
            line({
              item: item(5, "Bayonet", { is_rifle: false, current_price: null }),
              price: null,
              shipping: null,
              curio: null,
              fee: null,
              total: null,
              complete: false,
            }),
          ],
          totals: {
            count: 5,
            for_sale: 3,
            cost: 1030,
            cost_complete: false,
            unpriced: 1,
            value: 1100,
            valued: 2,
            compared: 2,
            compared_cost: 1030,
            compared_value: 1100,
            profit: 70,
          },
        },
      }),
    );
    await signedIn.goto("/wishlist");
    const table = signedIn.getByTestId("wishlist-table");
    const k31 = table.locator("tr", { hasText: "Swiss K31" });
    await expect(k31).toContainText("C&R, no dealer");
    await expect(k31).toContainText("+$170");
    await expect(k31).toContainText("when sold, same condition");
    const mosin = table.locator("tr", { hasText: "Mosin" });
    await expect(mosin).toContainText("Not stated");
    await expect(mosin).toContainText("Set your fee above");
    await expect(mosin).toContainText("at least");
    await expect(mosin).toContainText("−$100");
    await expect(mosin).toContainText("asking now");
    await expect(table.locator("tr", { hasText: "Sold Enfield" })).toContainText("Sold");
    await expect(table.locator("tr", { hasText: "Delisted Garand" })).toContainText(
      "No longer listed",
    );
    await expect(table.locator("tr", { hasText: "Bayonet" })).toContainText("No price");

    const totals = signedIn.getByTestId("wishlist-totals");
    await expect(totals).toContainText("2 gone");
    await expect(totals).toContainText("≥ $1,030");
    await expect(totals).toContainText("1 unpriced");
    await expect(totals).toContainText("+$70");
    await expect(totals).toContainText("over the 2 with both");
    await expect(totals).toContainText("over your $1,000 budget, at least");
    await expect(k31).toContainText("↓ $50 since added");
    await expect(mosin).toContainText("↑ $20 since added");
    await expect(signedIn.getByLabel(/the moment one sells/)).toBeChecked();

    // Sorted by profit, best first; the lines with none go last.
    const titles = table.locator(".wishlist-item__title");
    await signedIn.getByRole("button", { name: "Profit" }).click();
    await expect(titles.first()).toHaveText("Swiss K31");
    await expect(titles.nth(1)).toHaveText("Mosin M91/30");
    await signedIn.getByRole("button", { name: "Profit" }).click();
    await expect(titles.first()).toHaveText("Mosin M91/30");
    await signedIn.getByRole("button", { name: "Listing" }).click();
    await expect(titles.first()).toHaveText("Bayonet");
    await signedIn.getByRole("button", { name: "Worth" }).click();
    await expect(titles.first()).toHaveText("Swiss K31");
    await signedIn.getByRole("button", { name: "Price" }).click();
    await signedIn.getByRole("button", { name: "Total" }).click();
    await expect(titles.last()).toHaveText("Bayonet");
  });

  test("one the market cannot price, with unknown C&R status", async ({ signedIn }) => {
    await signedIn.route("**/api/wishlist", (route) =>
      route.fulfill({
        json: {
          ffl_transfer_fee: 25,
          has_cr_license: false,
          budget: 2000,
          lines: [line({ item: item(6, "Odd rifle"), curio: "unknown" })],
          totals: {
            count: 1,
            for_sale: 1,
            cost: 555,
            cost_complete: true,
            unpriced: 0,
            value: 0,
            valued: 0,
            compared: 0,
            compared_cost: 0,
            compared_value: 0,
            profit: 0,
          },
        },
      }),
    );
    await signedIn.goto("/wishlist");
    const row = signedIn
      .getByTestId("wishlist-table")
      .locator("tr", { hasText: "Odd rifle" });
    await expect(row).toContainText("C&R status unknown");
    const totals = signedIn.getByTestId("wishlist-totals");
    await expect(totals).toContainText("0 the market can price");
    await expect(totals).toContainText("profit or loss");
    await expect(totals).toContainText("$1,445left of your $2,000 budget");
  });

  test("failures are said, not swallowed", async ({ signedIn }) => {
    await signedIn.route("**/api/preferences/costs", (route) =>
      route.fulfill({ status: 500, json: { detail: "Could not save" } }),
    );
    await signedIn.route("**/api/wishlist/**", (route) =>
      route.fulfill({ status: 500, json: { detail: "Wishlist is down" } }),
    );
    await signedIn.route("**/api/wishlist", (route) =>
      route.fulfill({
        json: {
          ffl_transfer_fee: 25,
          has_cr_license: false,
          lines: [line({ item: item(7, "Stuck K98k") })],
          totals: {
            count: 1,
            for_sale: 1,
            cost: 555,
            cost_complete: true,
            unpriced: 0,
            value: 0,
            valued: 0,
            compared: 0,
            compared_cost: 0,
            compared_value: 0,
            profit: 0,
          },
        },
      }),
    );
    await signedIn.goto("/wishlist");
    const license = signedIn.getByLabel(/I hold a C&R license/);
    await license.click();
    await expect(signedIn.getByRole("alert")).toContainText("Could not save");
    // Put back: the box says what is saved, not what was clicked.
    await expect(license).not.toBeChecked();
    await signedIn
      .getByRole("button", { name: "Take Stuck K98k off the wishlist" })
      .click();
    await expect(
      signedIn.getByRole("alert").filter({ hasText: "Wishlist is down" }),
    ).toBeVisible();
    await signedIn.getByRole("button", { name: "Bought Stuck K98k" }).click();
    await expect(
      signedIn.getByRole("alert").filter({ hasText: "Wishlist is down" }),
    ).toBeVisible();
    const alerts = signedIn.getByLabel(/the moment one sells/);
    await alerts.click();
    await expect(alerts).not.toBeChecked();
  });

  test("a card's cart that fails is put back", async ({ signedIn }) => {
    await signedIn.goto("/?availability=all");
    await signedIn.route("**/api/wishlist/**", (route) =>
      route.fulfill({ status: 500, json: { detail: "Wishlist is down" } }),
    );
    const cart = signedIn.getByRole("button", { name: /^Add to wishlist: / }).first();
    await cart.click();
    await expect(cart).toHaveAttribute("title", "Could not change the wishlist");
    await expect(cart).toHaveAttribute("aria-pressed", "false");
  });

  test("a list that will not load says so", async ({ signedIn }) => {
    await signedIn.route("**/api/wishlist", (route) =>
      route.fulfill({ status: 500, json: { detail: "No wishlist today" } }),
    );
    await signedIn.goto("/wishlist");
    await expect(signedIn.getByRole("alert")).toContainText("No wishlist today");
  });

  test("the listing page says when the toggle fails", async ({ signedIn }) => {
    await signedIn.goto("/?availability=all");
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn.locator(".detail__facts")).toBeVisible();
    await signedIn.route("**/api/wishlist/**", (route) =>
      route.fulfill({ status: 500, json: { detail: "Wishlist is down" } }),
    );
    await signedIn.getByRole("button", { name: "Add to wishlist", exact: true }).click();
    await expect(signedIn.getByRole("alert")).toContainText("Wishlist is down");
  });
});
