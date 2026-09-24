/**
 * Saved searches: naming a browse query, running it, and the email settings.
 *
 * The three things the feature was asked for, in order: save a search under a
 * name, see and run the list, and turn a capped daily email on per search.
 */
import { test, expect } from "./fixtures.js";

async function save(page, name) {
  await page.getByRole("button", { name: "Save this search" }).click();
  await page.getByLabel("Name for this search").fill(name);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".alert--success")).toContainText(name);
}

test.describe("saving a search", () => {
  test("a named search appears on the saved searches page", async ({ signedIn }) => {
    await signedIn.goto("/?kind=rifle&sort=price_asc");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();

    await save(signedIn, "Cheap rifles");

    await signedIn.goto("/saved-searches");
    const card = signedIn.locator(".saved-search", { hasText: "Cheap rifles" });
    await expect(card).toBeVisible();
    await expect(card.locator(".saved-search__sort")).toContainText("Price: low to high");
  });

  test("the filters are described in words", async ({ signedIn }) => {
    await signedIn.goto("/?kind=rifle");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();
    await save(signedIn, "Just rifles");

    await signedIn.goto("/saved-searches");
    await expect(
      signedIn
        .locator(".saved-search", { hasText: "Just rifles" })
        .locator(".saved-search__filters"),
    ).toContainText("Type: rifle");
  });

  test("two searches cannot share a name", async ({ signedIn }) => {
    await signedIn.goto("/?kind=rifle");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();
    await save(signedIn, "Duplicate");

    await signedIn.getByRole("button", { name: "Save this search" }).click();
    await signedIn.getByLabel("Name for this search").fill("Duplicate");
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();
    await expect(signedIn.locator(".alert--error")).toContainText("already have");
  });
});

test.describe("the saved searches page", () => {
  test("running one lands on the inventory with its filters set", async ({
    signedIn,
  }) => {
    await signedIn.goto("/?kind=rifle&sort=title");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();
    await save(signedIn, "Runnable");

    await signedIn.goto("/saved-searches");
    await signedIn
      .locator(".saved-search", { hasText: "Runnable" })
      .getByRole("link", { name: "Run" })
      .click();

    await expect(signedIn).toHaveURL(/kind=rifle/);
    await expect(signedIn).toHaveURL(/sort=title/);
  });

  test("the email is off until it is turned on, and then it is capped", async ({
    signedIn,
  }) => {
    await signedIn.goto("/?kind=rifle");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();
    await save(signedIn, "Mailed");

    await signedIn.goto("/saved-searches");
    const card = signedIn.locator(".saved-search", { hasText: "Mailed" });
    const limit = card.locator("select");

    // The cap is meaningless until the email is on, so it is disabled first.
    await expect(limit).toBeDisabled();
    await card.getByLabel("Email me these").check();
    await expect(limit).toBeEnabled();

    await limit.selectOption("20");
    await signedIn.reload();
    await expect(
      signedIn.locator(".saved-search", { hasText: "Mailed" }).locator("select"),
    ).toHaveValue("20");
  });

  test("send now reports what the server said", async ({ signedIn }) => {
    /**
     * The suite's config has email switched off, which makes this the honest
     * case to assert: the button reaches the server, and what comes back is
     * shown on the card rather than swallowed. It is deliberately not gated on
     * the email toggle — "send this every day" and "send it to me now" are
     * different questions.
     */
    await signedIn.goto("/?kind=rifle");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();
    await save(signedIn, "Sendable");

    await signedIn.goto("/saved-searches");
    const card = signedIn.locator(".saved-search", { hasText: "Sendable" });

    await expect(card.getByLabel("Email me these")).not.toBeChecked();
    await card.getByRole("button", { name: /Send now/ }).click();

    await expect(card.locator(".alert")).toBeVisible();
  });

  test("deleting one removes it", async ({ signedIn }) => {
    await signedIn.goto("/?kind=rifle");
    await expect(signedIn.locator(".item-card, .item-row").first()).toBeVisible();
    await save(signedIn, "Disposable");

    await signedIn.goto("/saved-searches");
    await signedIn.getByRole("button", { name: "Delete Disposable" }).click();
    await expect(
      signedIn.locator(".saved-search", { hasText: "Disposable" }),
    ).toHaveCount(0);
  });

  test("with nothing saved it explains where to start", async ({ signedIn }) => {
    await signedIn.goto("/saved-searches");

    // Wait for the list to have rendered *something* before counting it.
    // `.count()` does not auto-wait, so on a slow first paint it reads zero on
    // an empty DOM, the delete loop below never runs, and the test then fails
    // looking for an empty state while two saved searches sit on the screen.
    // Anchoring on "a card or the empty state, whichever comes" is the wait
    // that was missing.
    await expect(signedIn.locator(".saved-search, .empty").first()).toBeVisible();

    // Whatever earlier tests left behind, clear it. Re-queried each time
    // rather than iterating `.all()`: deleting one re-renders the list, so
    // handles taken up front go stale.
    // Deleted until the list is empty rather than a fixed number of times:
    // this file shares one database with the tests above it, and a retry runs
    // this test alone against whatever they left behind.
    const remove = signedIn.getByRole("button", { name: /^Delete / });
    while ((await remove.count()) > 0) {
      const left = await remove.count();
      await remove.first().click();
      await expect(remove).toHaveCount(left - 1);
    }
    await expect(signedIn.locator(".empty")).toContainText("No saved searches yet");

    // And it survives a reload, which is the difference between the list being
    // empty and the *server* agreeing that it is.
    await signedIn.reload();
    await expect(signedIn.locator(".empty")).toContainText("No saved searches yet");
  });
});

/**
 * A saved search as the page describes it, from a stored query using every
 * filter at once. Answered from a route so the list is exactly this search,
 * whatever else the suite has saved by the time this runs.
 */
test.describe("a saved search, read back", () => {
  const RICH = {
    id: 901,
    name: "Swiss rifles under a thousand",
    query:
      "search=K31&kind=rifle&caliber=7.5x55mm&country=Switzerland&manufacturer=W%2BF+Bern" +
      "&category=Rifles&min_price=300&max_price=1000&price_drops_only=true&availability=sold",
    sort: "price_asc",
    email_enabled: true,
    email_item_limit: 10,
    match_count: 1,
    last_emailed_at: "2026-09-20T12:00:00Z",
  };

  async function show(page, searches) {
    await page.route("**/api/saved-searches", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: searches })
        : route.fallback(),
    );
    await page.goto("/saved-searches");
  }

  test("every filter is described in words", async ({ signedIn }) => {
    await show(signedIn, [RICH]);
    const card = signedIn.locator(".saved-search", { hasText: RICH.name });
    const filters = card.locator(".saved-search__filters");
    await expect(filters).toContainText("“K31”");
    await expect(filters).toContainText("Type: rifle");
    await expect(filters).toContainText("Caliber: 7.5x55mm");
    await expect(filters).toContainText("Country: Switzerland");
    await expect(filters).toContainText("Maker: W+F Bern");
    await expect(filters).toContainText("Category: Rifles");
    await expect(filters).toContainText("Price: 300–1000");
    await expect(filters).toContainText("Price reduced");
    await expect(filters).toContainText("Availability: sold");
    // One of them, so "match" rather than "matches".
    await expect(card.locator(".saved-search__count")).toHaveText("1 match");
    await expect(card).toContainText("Last emailed");
  });

  test("a price with only one end says which end is open", async ({ signedIn }) => {
    await show(signedIn, [{ ...RICH, query: "max_price=500", match_count: 4 }]);
    await expect(signedIn.locator(".saved-search__filters")).toHaveText("Price: any–500");
  });

  test("a change the server refuses is put back, and says why", async ({ signedIn }) => {
    await show(signedIn, [RICH]);
    await signedIn.route("**/api/saved-searches/901", (route) =>
      route.request().method() === "PATCH"
        ? route.fulfill({ status: 400, json: { detail: "That limit is not offered." } })
        : route.fallback(),
    );
    const card = signedIn.locator(".saved-search", { hasText: RICH.name });
    const toggle = card.getByRole("checkbox");
    await expect(toggle).toBeChecked();
    await toggle.uncheck();
    await expect(card.getByRole("alert")).toContainText("That limit is not offered.");
    // Optimistic, and so reverted: the box is left saying what the server holds.
    await expect(toggle).toBeChecked();
  });

  test("a list that cannot be loaded says so", async ({ signedIn }) => {
    await signedIn.route("**/api/saved-searches", (route) =>
      route.fulfill({ status: 500, json: { detail: "The database is busy." } }),
    );
    await signedIn.goto("/saved-searches");
    await expect(signedIn.getByRole("alert")).toContainText("The database is busy.");
  });
});
