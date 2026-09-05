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
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn.locator(".detail")).toBeVisible();

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
