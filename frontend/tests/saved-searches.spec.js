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
