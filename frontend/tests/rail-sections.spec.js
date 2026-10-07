/**
 * The rail's four sections fold, and a reader starts with only the catalog
 * open: the four at once are taller than a laptop's screen, and the catalog is
 * what nearly every visit is for.
 */
import { test, expect, openPage } from "./fixtures.js";

const rail = (page) => page.getByRole("navigation", { name: "Main navigation" });
const toggle = (page, name) => rail(page).getByRole("button", { name });

test("only the catalog is open on signing in", async ({ signedIn }) => {
  await expect(toggle(signedIn, "Catalog")).toHaveAttribute("aria-expanded", "true");
  for (const name of ["Yours", "Account", "Administration"]) {
    await expect(toggle(signedIn, name)).toHaveAttribute("aria-expanded", "false");
  }
  await expect(rail(signedIn).getByRole("link", { name: "Hot deals" })).toBeVisible();
  await expect(rail(signedIn).getByRole("link", { name: "Watchlist" })).toBeHidden();
});

test("a heading opens and closes its section", async ({ signedIn }) => {
  await toggle(signedIn, "Yours").click();
  await expect(rail(signedIn).getByRole("link", { name: "Watchlist" })).toBeVisible();
  await toggle(signedIn, "Catalog").click();
  await expect(rail(signedIn).getByRole("link", { name: "Hot deals" })).toBeHidden();
  await expect(toggle(signedIn, "Catalog")).toHaveAttribute("aria-expanded", "false");
});

test("what was opened stays open from page to page", async ({ signedIn }) => {
  await openPage(signedIn, "Watchlist");
  await openPage(signedIn, "Hot deals");
  await expect(toggle(signedIn, "Yours")).toHaveAttribute("aria-expanded", "true");
});

test("the section of the page on screen opens itself", async ({ signedIn }) => {
  await signedIn.goto("/armory");
  await expect(toggle(signedIn, "Administration")).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await expect(rail(signedIn).getByRole("link", { name: "Armory" })).toBeVisible();
});
