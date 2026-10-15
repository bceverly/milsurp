/**
 * When a gun was made, and its serial, on the listing page (asked for on
 * 2026-10-15). Which year a listing gets is the server's business
 * (app/services/serials.py); these check that the page shows what it is sent:
 * the year the listing states, with its words, or "about" the years its
 * serial places it in, with the listings it fell between.
 */
import { test, expect } from "./fixtures.js";

async function showListing(page, extra) {
  await page.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), is_rifle: true, ...extra },
    });
  });
  await page.goto("/?availability=all");
  await page.locator(".item-card").first().click();
  return page.locator(".detail__facts");
}

test("a year the listing states, in its own words", async ({ signedIn }) => {
  const facts = await showListing(signedIn, {
    serial: "3657019",
    made_from: 1945,
    made_to: 1945,
    made_source: "stated",
    made_quote: "Serial no. 3657019. Manufactured in 1945 at Springfield",
  });
  await expect(signedIn.getByTestId("year-made")).toHaveText(
    "Made1945“Serial no. 3657019. Manufactured in 1945 at Springfield”",
  );
  await expect(facts).toContainText("Serial3657019");
  // One "Made", not the C&R reader's as well.
  await expect(facts.locator(".fact__label", { hasText: /^Made$/ })).toHaveCount(1);
});

test("a year placed by its serial says about, and from what", async ({ signedIn }) => {
  await showListing(signedIn, {
    serial: "2143954",
    made_from: 1943,
    made_to: 1944,
    made_source: "serial",
    made_quote:
      "between serials 2,051,218 (1943) and 2,578,076 (1944), as listings here state",
  });
  await expect(signedIn.getByTestId("year-made")).toHaveText(
    "Madeabout 1943–1944from its serial, between serials 2,051,218 (1943) and " +
      "2,578,076 (1944), as listings here state",
  );
});

test("with neither, the C&R reader's year as before", async ({ signedIn }) => {
  const facts = await showListing(signedIn, {
    serial: null,
    made_from: null,
    made_to: null,
    made_source: null,
    manufacture_year: 1943,
  });
  await expect(signedIn.getByTestId("year-made")).toHaveCount(0);
  await expect(facts).toContainText("Made1943");
  await expect(facts.locator(".fact__label", { hasText: /^Serial$/ })).toHaveCount(0);
});
