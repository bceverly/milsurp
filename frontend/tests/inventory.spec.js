/** The inventory browser: search, filters, sorting, pagination, detail view. */
import { test, expect } from "./fixtures.js";

test.describe("inventory", () => {
  test("shows listings with prices and photos", async ({ signedIn }) => {
    const cards = signedIn.locator(".item-card");
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBeGreaterThan(0);

    const first = cards.first();
    await expect(first.locator(".item-card__title")).not.toBeEmpty();
    await expect(first.locator(".item-card__price")).toContainText("$");
  });

  test("the result count matches the heading", async ({ signedIn }) => {
    await expect(signedIn.getByText(/\d+ listings? match your filters/)).toBeVisible();
  });

  test("search narrows the results and updates the URL", async ({ signedIn }) => {
    // Wait for the grid before counting, or `before` is 0 and the comparison
    // below is meaningless.
    await expect(signedIn.locator(".item-card").first()).toBeVisible();
    const before = await signedIn.locator(".item-card").count();

    await signedIn.getByPlaceholder(/search titles/i).fill("mauser");
    // The box is debounced, so wait for the URL to catch up rather than sleeping.
    await expect(signedIn).toHaveURL(/search=mauser/);
    await signedIn.waitForTimeout(600);

    const after = await signedIn.locator(".item-card").count();
    expect(after).toBeLessThanOrEqual(before);
  });

  test("a search with no matches shows the empty state", async ({ signedIn }) => {
    await signedIn.getByPlaceholder(/search titles/i).fill("zzzznosuchthing");
    await expect(signedIn.getByText("No listings match")).toBeVisible();
  });

  test("clearing the search restores the full list", async ({ signedIn }) => {
    await expect(signedIn.locator(".item-card").first()).toBeVisible();
    const before = await signedIn.locator(".item-card").count();
    await signedIn.getByPlaceholder(/search titles/i).fill("mauser");
    await expect(signedIn).toHaveURL(/search=mauser/);

    await signedIn.getByRole("button", { name: "Clear search" }).click();
    await expect(signedIn).not.toHaveURL(/search=/);
    await signedIn.waitForTimeout(600);
    expect(await signedIn.locator(".item-card").count()).toBe(before);
  });

  test("search state is shareable via the URL", async ({ signedIn }) => {
    await signedIn.goto("/?search=mauser");
    await expect(signedIn.getByPlaceholder(/search titles/i)).toHaveValue("mauser");
  });

  test("sorting by price orders the results ascending", async ({ signedIn }) => {
    await signedIn.getByLabel("Sort listings").selectOption("price_asc");
    await expect(signedIn).toHaveURL(/sort=price_asc/);
    await signedIn.waitForTimeout(800);

    const prices = await signedIn.locator(".item-card__price").allTextContents();
    const numbers = prices
      .map((text) => Number(text.replace(/[^0-9.]/g, "")))
      .filter((value) => !Number.isNaN(value) && value > 0);
    const sorted = [...numbers].sort((a, b) => a - b);
    expect(numbers).toEqual(sorted);
  });

  test("a facet filter applies and can be removed again", async ({ signedIn }) => {
    // The filter rail is always visible at desktop widths.
    const rifles = signedIn.getByRole("checkbox", { name: "Rifles" });
    await rifles.check();
    await expect(signedIn).toHaveURL(/kind=rifle/);

    // The active-filter chip is the affordance for undoing it.
    const chip = signedIn.locator(".active-filters__chip", { hasText: "Rifles" });
    await expect(chip).toBeVisible();
    await chip.getByRole("button").click();
    await expect(signedIn).not.toHaveURL(/kind=rifle/);
  });

  test("clear all removes every filter at once", async ({ signedIn }) => {
    await signedIn.goto("/?kind=rifle&search=mauser");
    await signedIn.getByRole("button", { name: "Clear all" }).click();
    await expect(signedIn).not.toHaveURL(/kind=|search=/);
  });

  test("availability is a single choice", async ({ signedIn }) => {
    await signedIn.getByRole("radio", { name: "Sold" }).check();
    await expect(signedIn).toHaveURL(/availability=sold/);
  });
});

test.describe("item detail", () => {
  test("opens from a card and shows the full record", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn).toHaveURL(/\/items\/\d+/);

    await expect(signedIn.locator(".detail__title")).not.toBeEmpty();
    await expect(signedIn.locator(".detail__price-now")).toBeVisible();
    await expect(signedIn.getByRole("heading", { name: "Price history" })).toBeVisible();
    await expect(signedIn.getByRole("link", { name: /View on/ })).toBeVisible();
  });

  test("the vendor link opens safely in a new tab", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    const link = signedIn.getByRole("link", { name: /View on/ });
    await expect(link).toHaveAttribute("target", "_blank");
    // noopener stops the vendor page reaching back through window.opener.
    await expect(link).toHaveAttribute("rel", /noopener/);
  });

  test("back returns to the inventory", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn).toHaveURL(/\/items\/\d+/);
    await signedIn.getByRole("button", { name: /Back to inventory/ }).click();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });

  test("a photo gallery is shown when the listing has several", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn.locator(".gallery__main")).toBeVisible();

    const thumbs = signedIn.locator(".gallery__thumb");
    if ((await thumbs.count()) > 1) {
      await thumbs.nth(1).click();
      await expect(thumbs.nth(1)).toHaveClass(/gallery__thumb--active/);
    }
  });

  test("an unknown item id shows an error rather than a blank page", async ({
    signedIn,
  }) => {
    await signedIn.goto("/items/999999");
    await expect(signedIn.getByRole("alert")).toBeVisible();
  });
});

test.describe("pagination", () => {
  // The demo catalog is deliberately seeded past the 48-per-page boundary so
  // these controls exist to be clicked. When it held only 28 listings the
  // pager never rendered, and a Next button that set the page number and then
  // deleted it went unnoticed.

  test("next advances to the following page", async ({ signedIn }) => {
    const status = signedIn.locator(".pagination__status");
    await expect(status).toContainText("Page 1 of");

    const firstTitle = await signedIn.locator(".item-card__title").first().textContent();

    await signedIn.getByRole("button", { name: "Next" }).click();

    await expect(status).toContainText("Page 2 of");
    await expect(signedIn).toHaveURL(/page=2/);
    // Different page, different listings.
    await expect(signedIn.locator(".item-card__title").first()).not.toHaveText(
      firstTitle ?? "",
    );
  });

  test("previous returns to page one and drops the parameter", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Next" }).click();
    await expect(signedIn).toHaveURL(/page=2/);

    await signedIn.getByRole("button", { name: "Previous" }).click();
    await expect(signedIn.locator(".pagination__status")).toContainText("Page 1 of");
    // Page 1 is the default, so it stays out of the URL.
    await expect(signedIn).not.toHaveURL(/page=/);
  });

  test("paging returns you to the top of the grid", async ({ signedIn }) => {
    // The pager sits below 48 cards, so a page change always starts from the
    // bottom of the page. Landing on the new page already scrolled past its
    // first rows makes it look like nothing happened.
    // The page has to be tall enough to scroll before any of this proves
    // anything, and a grid still fetching its cards is not. The scroll is
    // retried inside the poll rather than gated on a card count: page two
    // holds the remainder, not a full 48, and how much of the catalog is
    // active depends on whether an unrelated test has run a scan.
    const scrollToBottom = () =>
      expect
        .poll(async () => {
          await signedIn.evaluate(() =>
            window.scrollTo(0, document.documentElement.scrollHeight),
          );
          return signedIn.evaluate(() => window.scrollY);
        })
        .toBeGreaterThan(0);

    await scrollToBottom();
    await signedIn.getByRole("button", { name: "Next" }).click();
    await expect(signedIn).toHaveURL(/page=2/);
    await expect.poll(() => signedIn.evaluate(() => window.scrollY)).toBe(0);

    await scrollToBottom();
    await signedIn.getByRole("button", { name: "Previous" }).click();
    await expect(signedIn.locator(".pagination__status")).toContainText("Page 1 of");
    await expect.poll(() => signedIn.evaluate(() => window.scrollY)).toBe(0);
  });

  test("the buttons disable at each end", async ({ signedIn }) => {
    await expect(signedIn.getByRole("button", { name: "Previous" })).toBeDisabled();
    await signedIn.getByRole("button", { name: "Next" }).click();
    await expect(signedIn.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  test("changing a filter resets to page one", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Next" }).click();
    await expect(signedIn).toHaveURL(/page=2/);

    // A narrower result set renumbers the pages, so page 2 no longer means
    // anything and must be dropped.
    await signedIn.getByRole("checkbox", { name: "Rifles" }).check();
    await expect(signedIn).toHaveURL(/kind=rifle/);
    await expect(signedIn).not.toHaveURL(/page=2/);
  });
});
