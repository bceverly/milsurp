/**
 * What the two armory spec files share: loading the shipped rows, and waiting
 * for the right table to be the one on screen.
 */
import { expect } from "./fixtures.js";

/**
 * Load the shipped armory, through the API, and show the page it produces.
 *
 * Nearly every test here starts from the shipped rows and is about something
 * else, so the button is not pressed for them: the endpoint is called the way
 * the page calls it, CSRF token and all, and the page is reloaded and waited
 * for. Pressing it and waiting for its alert cost every one of them the
 * button's own round trip plus a re-render of the table it replaces. The
 * button itself is tested once, by pressLoadShipped.
 */
export async function loadShipped(page) {
  const csrf = (await page.context().cookies()).find((c) => c.name === "milsurp_csrf");
  const response = await page.request.post("/api/armory/seed", {
    headers: csrf ? { "X-CSRF-Token": csrf.value } : {},
  });
  expect(response.ok()).toBe(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Armory", exact: true })).toBeVisible();
  // The spinner, not .loading-row: that cell is also the empty state, and a
  // filter with nothing in it ("pending", once a test has approved it all) is
  // a finished load too.
  await expect(page.locator("tbody .loading-row .spinner")).toHaveCount(0);
}

/**
 * Press "Load shipped armory" and wait for it to say it has.
 *
 * Waiting was a race each time without it: the load's own reload replaces the
 * table, so a search typed, a row ticked or a tab chosen before it lands is
 * done to a table about to vanish.
 */
export async function pressLoadShipped(page) {
  await page.getByRole("button", { name: "Load shipped armory" }).click();
  await expect(page.locator(".alert--success")).toBeVisible();
}

/**
 * Wait until the *manufacturers* table is the one on screen.
 *
 * Clicking a tab does not clear the previous tab's rows while the new ones
 * load, so a count taken straight after the click can be the Models tab's:
 * "a maker can be deleted" read 553 delete buttons that way and then compared
 * them against 63 makers. The expander is in the makers table and nowhere
 * else, which makes it the signal that the swap has happened.
 */
export async function makersAreShowing(page) {
  await expect(page.getByRole("button", { name: /^Expand / }).first()).toBeVisible();
}

/**
 * Wait until a named row on the Calibers tab is really on screen.
 *
 * Two races in one, and the same answer to both. Clicking a tab does not
 * clear the previous tab's rows while the new ones load, so `tbody tr` read
 * straight afterwards can still be the Models tab's -- and `hasText` matches
 * anywhere in a row, so a caliber name hits a Models row's "Chambered in"
 * cell. Separately, "Load shipped armory" is still committing while the next
 * click is being made.
 *
 * Polling the row *names* has neither hole, which is the same reasoning the
 * sort test below already arrived at: waiting for a loading row to be absent
 * races the reload starting, because it is absent before it begins too.
 */
export async function caliberRowIsShowing(page, name) {
  await expect
    .poll(() => page.locator("tbody tr td:nth-child(2) button").allInnerTexts())
    .toContain(name);
}

/**
 * Narrow the table to *text* with the Search box, and wait for a row with it.
 *
 * The tables are paged (a hundred rows a page), so a row that exists may be on
 * a later page -- searching for it is how a person finds one, and it does not
 * depend on where the sort happens to put it.
 */
export async function searchFor(page, text) {
  await page.getByLabel("Search").fill(text);
  await expect(page).toHaveURL(/[?&]q=/);
  await expect(page.locator("tbody tr", { hasText: text }).first()).toBeVisible();
}

/** Clear the Search box, back to every row the Showing filter admits. */
export async function clearSearch(page) {
  await page.getByLabel("Search").fill("");
  await expect(page).not.toHaveURL(/[?&]q=/);
}

/**
 * The name in every row of the table, every page of it, in order.
 *
 * For the tests that are about the order of the whole list rather than about
 * one row. Pages forward with the pager until it stops, then back to the first.
 */
export async function allRowNames(page) {
  const names = [];
  const next = page.locator(".armory-pager").getByRole("button", { name: "Next" });
  for (;;) {
    names.push(
      ...(await page.locator("tbody tr td:nth-child(2) button").allInnerTexts()),
    );
    if ((await next.count()) === 0 || (await next.isDisabled())) break;
    const status = await page.locator(".armory-pager .pagination__status").innerText();
    await next.click();
    await expect(page.locator(".armory-pager .pagination__status")).not.toHaveText(
      status,
    );
  }
  return names.map((name) => name.trim());
}
