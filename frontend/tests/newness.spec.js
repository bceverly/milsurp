/**
 * New or used (asked for on 2026-10-20): the Inventory rail asks for it, and
 * a listing's page says which. Which listings are which is the server's
 * business (app/services/newness.py).
 */
import { test, expect } from "./fixtures.js";

test("the rail asks for new or used", async ({ signedIn }) => {
  const asked = [];
  await signedIn.route(/\/api\/items\?/, async (route) => {
    asked.push(new URL(route.request().url()).searchParams);
    await route.continue();
  });
  await signedIn.goto("/?availability=all");
  const last = () => asked[asked.length - 1];

  await signedIn.locator(".facet__summary", { hasText: /^New or used$/ }).click();
  await signedIn.getByRole("radio", { name: "Used" }).check();
  await expect.poll(() => last().get("newness")).toBe("used");
  await signedIn.getByRole("button", { name: "Remove Used" }).click();
  await expect.poll(() => last().get("newness")).toBe(null);
  await signedIn.getByRole("radio", { name: "New", exact: true }).check();
  await expect.poll(() => last().get("newness")).toBe("new");
});

test("a listing says whether it is new or used", async ({ signedIn }) => {
  await signedIn.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), is_new: true } });
  });
  await signedIn.goto("/?availability=all");
  await signedIn.locator(".item-card").first().click();
  await expect(signedIn.locator(".detail__facts")).toContainText("New or usedNew");
});
