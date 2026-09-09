/**
 * The mobile layout.
 *
 * Runs under the "mobile" Playwright project (Pixel 7), because the app is
 * meant to be used on a phone as much as on a desktop and the two layouts
 * differ structurally, not just cosmetically.
 */
import { test, expect } from "./fixtures.js";

test.describe("mobile layout", () => {
  test("the inventory grid fits the viewport", async ({ signedIn }) => {
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
    await expect(signedIn.locator(".item-card").first()).toBeVisible();

    // Nothing may push the page wider than the screen.
    const overflow = await signedIn.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("navigation is a drawer, opened from the header", async ({ signedIn }) => {
    // The sidebar is off-canvas until the menu button is pressed.
    const rail = signedIn.locator(".rail");
    await expect(rail).not.toHaveClass(/rail--open/);

    await signedIn.getByRole("button", { name: "Open navigation" }).click();
    await expect(rail).toHaveClass(/rail--open/);
    await expect(signedIn.getByRole("link", { name: "Sites" })).toBeVisible();
  });

  test("the drawer closes after navigating", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Open navigation" }).click();
    await signedIn.getByRole("link", { name: "Sites", exact: true }).click();

    await expect(signedIn.getByRole("heading", { name: "Sites" })).toBeVisible();
    await expect(signedIn.locator(".rail")).not.toHaveClass(/rail--open/);
  });

  test("the drawer closes on escape", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Open navigation" }).click();
    await expect(signedIn.locator(".rail")).toHaveClass(/rail--open/);

    await signedIn.keyboard.press("Escape");
    await expect(signedIn.locator(".rail")).not.toHaveClass(/rail--open/);
  });

  test("filters are behind a toggle rather than always on screen", async ({
    signedIn,
  }) => {
    const filters = signedIn.locator(".filters");
    await expect(filters).toBeHidden();

    await signedIn.getByRole("button", { name: /Filters/ }).click();
    await expect(filters).toBeVisible();
  });

  test("the item detail view stacks without horizontal scroll", async ({ signedIn }) => {
    // This test needs a listing whose thumbnail strip is wider than the phone,
    // and it has to go and find one rather than take whichever card is first.
    //
    // Both halves of that were learned the hard way. The page scrolled
    // sideways by 378px for a year with this test watching it, because the
    // seed gave every listing at most four photos and four thumbnails — 296px
    // — fit a phone: the test opened the page and proved nothing. And the
    // obvious repair, "seed one listing with ten photos and click the first
    // card", fails whenever admin.spec.js has already run: scanning the Demo
    // Vendor creates six listings dated now, and those lead "newest first".
    //
    // So: walk the listings until one qualifies, and fail loudly if none does,
    // rather than pass quietly on a page that cannot demonstrate anything.
    // Wait for the grid before reading it: evaluateAll does not auto-wait, so
    // on a slow first paint it returns an empty list from an empty DOM and the
    // test fails claiming there are no listings.
    await expect(signedIn.locator(".item-card").first()).toBeVisible();
    const hrefs = await signedIn
      .locator('a[href^="/items/"]')
      .evaluateAll((links) => [...new Set(links.map((a) => a.getAttribute("href")))]);
    expect(hrefs.length).toBeGreaterThan(0);

    let measured = null;
    for (const href of hrefs.slice(0, 12)) {
      await signedIn.goto(href);
      await expect(signedIn.locator(".detail")).toBeVisible();
      const strip = signedIn.locator(".gallery__thumbs");
      if (!(await strip.count())) continue;
      const seen = await strip.evaluate((el) => ({
        content: el.scrollWidth,
        box: el.clientWidth,
        viewport: document.documentElement.clientWidth,
      }));
      if (seen.content > seen.viewport) {
        measured = seen;
        break;
      }
    }
    expect(
      measured,
      "no seeded listing has a thumbnail strip wider than the viewport, so this " +
        "test cannot show anything — check seed_demo_data.GALLERY_PHOTOS",
    ).not.toBeNull();

    // The strip absorbs the overflow by scrolling itself...
    expect(measured.box).toBeLessThanOrEqual(measured.viewport);
    // ...rather than by pushing the page sideways.
    const overflow = await signedIn.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("form fields are large enough not to trigger iOS zoom", async ({ page }) => {
    // Anything under 16px makes Safari zoom the page on focus.
    await page.goto("/");
    const fontSize = await page
      .locator('input[name="username"]')
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(fontSize).toBeGreaterThanOrEqual(16);
  });
});
