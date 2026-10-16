/**
 * Capacity on the listing page and in the inventory's rail, and searching by
 * frame size (asked for on 2026-10-16). Which listings match is the server's
 * business (app/services/capacity.py, app/services/search.py); these check
 * that the page shows what it is sent and asks for what was typed.
 */
import { test, expect } from "./fixtures.js";

async function showListing(page, extra) {
  await page.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), is_pistol: true, ...extra },
    });
  });
  await page.goto("/?availability=all");
  await page.locator(".item-card").first().click();
  return page.locator(".detail__facts");
}

test("a listing's capacity, in its words or from the armory", async ({ signedIn }) => {
  await showListing(signedIn, {
    capacity: 17,
    capacity_quote: "Pistols come with one 17rd magazine",
  });
  await expect(signedIn.getByTestId("capacity")).toHaveText(
    "Capacity17 rounds“Pistols come with one 17rd magazine”",
  );
});

test("a capacity it does not state is its model's", async ({ signedIn }) => {
  await showListing(signedIn, { capacity: 13, capacity_quote: null });
  await expect(signedIn.getByTestId("capacity")).toHaveText(
    "Capacity13 roundsfrom the armory",
  );
});

test("the rail asks for a capacity and a frame size", async ({ signedIn }) => {
  const asked = [];
  await signedIn.route(/\/api\/items\?/, async (route) => {
    asked.push(new URL(route.request().url()).searchParams);
    const response = await route.fetch();
    const body = await response.json();
    body.facets = {
      ...body.facets,
      frames: [
        { value: "Full size", label: "Full size", count: 12 },
        { value: "Compact", label: "Compact", count: 9 },
      ],
    };
    await route.fulfill({ response, json: body });
  });
  await signedIn.goto("/?availability=all");
  const last = () => asked[asked.length - 1];

  await signedIn.locator(".facet__summary", { hasText: /^Capacity$/ }).click();
  const box = signedIn.getByLabel("Rounds", { exact: true });
  await box.fill("15+");
  await box.press("Enter");
  await expect
    .poll(() => [last().get("capacity_min"), last().get("capacity_max")])
    .toEqual(["15", null]);
  await expect(
    signedIn.getByRole("button", { name: "Remove Capacity: 15+ rounds" }),
  ).toBeVisible();

  await box.fill("ten");
  await box.press("Enter");
  await expect(signedIn.locator("#capacity-rounds-hint")).toHaveText(
    "A number (15), a range (10-17), or one end (15+, -8).",
  );

  await signedIn.locator(".facet__summary", { hasText: /^Frame size$/ }).click();
  await signedIn.getByRole("checkbox", { name: /^Compact/ }).check();
  await expect.poll(() => last().getAll("frame")).toEqual(["Compact"]);
});
