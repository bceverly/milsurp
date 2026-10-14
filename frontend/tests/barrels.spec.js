/**
 * A gun's barrel: its length and whether it is threaded, shown on the listing
 * with the words they were read from, and searched on from the Inventory rail.
 * Asked for on 2026-10-13. Which listings match is the server's business
 * (app/services/barrels.py and app/services/search.py); these check that the
 * page asks for what was typed and shows what it is sent.
 */
import { test, expect, openPage } from "./fixtures.js";

test("a listing shows its barrel and the words it was read from", async ({
  signedIn,
}) => {
  await signedIn.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...(await response.json()),
        is_pistol: true,
        barrel_inches: 4.625,
        barrel_threaded: true,
        barrel_quotes: {
          length: "4 & 5/8 INCH BARREL",
          threaded: "The muzzle is threaded for 1/2x28",
        },
      },
    });
  });
  await signedIn.goto("/?availability=all");
  await signedIn.locator(".item-card").first().click();
  const facts = signedIn.locator(".detail__facts");
  await expect(facts).toContainText('Barrel4.625"“4 & 5/8 INCH BARREL”');
  await expect(facts).toContainText("ThreadedYes“The muzzle is threaded for 1/2x28”");
});

test("the rail asks for a length, a range, one end, and threading", async ({
  signedIn,
}) => {
  const asked = [];
  await signedIn.route(/\/api\/items\?/, async (route) => {
    asked.push(new URL(route.request().url()).searchParams);
    await route.continue();
  });
  await signedIn.goto("/?availability=all");
  await signedIn.locator(".facet__summary", { hasText: /^Barrel$/ }).click();
  const box = signedIn.getByLabel("Length, in inches");

  const lastAsked = () => asked[asked.length - 1];
  await box.fill("4.5");
  await box.press("Enter");
  await expect
    .poll(() => [lastAsked().get("barrel_min"), lastAsked().get("barrel_max")])
    .toEqual(["4.5", "4.5"]);
  await expect(
    signedIn.getByRole("button", { name: 'Remove Barrel: 4.5"' }),
  ).toBeVisible();

  await box.fill("3 to 4");
  await box.press("Enter");
  await expect
    .poll(() => [lastAsked().get("barrel_min"), lastAsked().get("barrel_max")])
    .toEqual(["3", "4"]);

  await box.fill("16+");
  await box.press("Enter");
  await expect
    .poll(() => [lastAsked().get("barrel_min"), lastAsked().get("barrel_max")])
    .toEqual(["16", null]);

  await box.fill("long");
  await box.press("Enter");
  await expect(
    signedIn.getByText("A length (4.5), a range (4-5), or one end"),
  ).toBeVisible();

  await signedIn.getByRole("radio", { name: "Threaded", exact: true }).check();
  await expect.poll(() => lastAsked().get("threaded")).toBe("yes");
  await expect(signedIn).toHaveURL(/threaded=yes/);
});

test("Site settings re-reads every gun's barrel", async ({ signedIn }) => {
  // Stubbed, as the manufacturer jobs are in maker-link.spec.js.
  const jobs = [
    { name: "variants", requested_at: null, last_run_at: null },
    { name: "pages", requested_at: null, last_run_at: null },
    {
      name: "barrels",
      requested_at: null,
      last_run_at: new Date().toISOString(),
      last_status: "ok",
      last_summary: "Read 16,535 gun(s): 5,085 barrel length(s), 152 threaded",
    },
  ];
  const asked = [];
  await signedIn.route("**/api/manufacturer-data**", async (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      asked.push(new URL(request.url()).pathname);
      jobs[2] = { ...jobs[2], requested_at: new Date().toISOString() };
    }
    await route.fulfill({ json: jobs });
  });
  await openPage(signedIn, "Site settings");
  const section = signedIn.getByTestId("listing-data-section");
  await expect(section.getByTestId("manufacturer-job-barrels")).toContainText(
    "5,085 barrel length(s)",
  );
  await section
    .getByRole("button", { name: "Re-read barrel lengths and threading" })
    .click();
  await expect.poll(() => asked).toEqual(["/api/manufacturer-data/barrels/run"]);
  await expect(section.getByRole("button", { name: "Asked for" })).toBeDisabled();
});
