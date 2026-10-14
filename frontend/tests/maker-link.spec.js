/**
 * Modern production, and the maker's page one click from a listing.
 *
 * Slice 1 of "New-gun prices, and the makers' own pages" in ROADMAP.md: a
 * reader looking at a used carry gun was searching Google for the maker's
 * page by hand. Which link a listing gets is the server's decision (see
 * services/makerlink.py and its tests); these check that the page shows what
 * it is sent, and that the armory edits the fields it is decided from.
 */
import { test, expect, openPage } from "./fixtures.js";
import { searchFor, openArmoryModels } from "./armory-helpers.js";

async function openListingWith(page, makerLink) {
  await page.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    const item = await response.json();
    item.maker_link = makerLink;
    // Matched to a model, so "What the armory knows" is there to open.
    item.model = item.model || "Tracker";
    item.firearm_model_id = item.firearm_model_id || 1;
    await route.fulfill({ response, json: item });
  });
  await page.goto("/?availability=all");
  await page.locator(".item-card").first().click();
  await expect(page.locator(".detail__facts")).toBeVisible();
}

test.describe("the maker's page on a listing", () => {
  // Inside "What the armory knows" since 2026-10-12, and only the model's own
  // page: the search of the maker's site it fell back to is gone.
  async function openArmory(page) {
    await page.getByRole("button", { name: "What the armory knows" }).click();
    return page.getByRole("dialog");
  }

  test("the model's own page, in what the armory knows", async ({ signedIn }) => {
    const url = "https://www.taurususa.com/revolvers/tracker";
    await openListingWith(signedIn, {
      url,
      kind: "page",
      maker: "Taurus",
      site: "taurususa.com",
    });
    // Not under the buy button any more: nowhere until the popup opens.
    await expect(signedIn.getByTestId("maker-link")).toHaveCount(0);
    const dialog = await openArmory(signedIn);
    const link = dialog.getByTestId("maker-link");
    await expect(link).toHaveText("Taurus's page");
    await expect(link).toHaveAttribute("href", url);
    await expect(link).toHaveAttribute("target", "_blank");
  });

  test("nothing at all when the armory has no page", async ({ signedIn }) => {
    await openListingWith(signedIn, null);
    await expect(signedIn.getByRole("link", { name: /^View on / })).toBeVisible();
    const dialog = await openArmory(signedIn);
    await expect(dialog.getByTestId("maker-link")).toHaveCount(0);
  });
});

test("the armory flags a model as still made and records its page", async ({
  signedIn,
}) => {
  await openArmoryModels(signedIn);
  await signedIn.getByRole("button", { name: "Add model" }).click();
  const name = `Modern Test ${Date.now()}`;
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel("Modern production").check();
  await dialog.getByLabel("Manufacturer's page").fill("https://maker.example/carry");
  await dialog.getByRole("button", { name: "Add, awaiting approval" }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);

  await searchFor(signedIn, name);
  const row = signedIn.locator("tbody tr", { hasText: name });
  await expect(row.getByText("Still made")).toBeVisible();

  await row.getByRole("button", { name, exact: true }).click();
  dialog = signedIn.getByRole("dialog");
  await expect(dialog.getByLabel("Modern production")).toBeChecked();
  await expect(dialog.getByLabel("Manufacturer's page")).toHaveValue(
    "https://maker.example/carry",
  );
  await dialog.getByLabel("Modern production").uncheck();
  await dialog.getByLabel("Manufacturer's page").fill("");
  await dialog.getByRole("button", { name: /^Save/ }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);
  await expect(row.getByText("Still made")).toHaveCount(0);

  // Leave the armory as found.
  await signedIn.getByRole("button", { name: `Delete ${name}` }).click();
  await signedIn
    .getByRole("dialog")
    .getByRole("button", { name: /^Delete/ })
    .click();
  await expect(row).toHaveCount(0);
});

test("a maker's website is edited with the maker", async ({ signedIn }) => {
  await openPage(signedIn, "Armory");
  await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
  await signedIn.getByRole("button", { name: "Add manufacturer" }).click();
  const name = `Website Test ${Date.now()}`;
  let dialog = signedIn.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel("Website").fill("websitetest.example");
  await dialog.getByRole("button", { name: "Add manufacturer" }).click();
  await expect(signedIn.getByRole("dialog")).toHaveCount(0);

  await signedIn.getByLabel("Showing").selectOption("");
  await signedIn.getByLabel("Search").fill(name);
  await signedIn.getByRole("button", { name, exact: true }).click();
  dialog = signedIn.getByRole("dialog");
  // Saved as an address, scheme and all, whatever was typed.
  await expect(dialog.getByLabel("Website")).toHaveValue("https://websitetest.example");
  await dialog
    .getByRole("button", { name: /^Cancel|^Close/ })
    .first()
    .click();

  await signedIn.getByRole("button", { name: `Delete ${name}` }).click();
  await signedIn
    .getByRole("dialog")
    .getByRole("button", { name: /^Delete/ })
    .click();
  await expect(signedIn.getByRole("button", { name, exact: true })).toHaveCount(0);
});

test.describe("the Manufacturer pages tab", () => {
  // Showing works here and a page can be typed in by hand (2026-10-13).
  test("a page is added, edited and removed by hand under Production", async ({
    signedIn,
  }) => {
    await openArmoryModels(signedIn);
    const name = `Page Test ${Date.now()}`;
    await signedIn.getByRole("button", { name: "Add model" }).click();
    await signedIn.getByRole("dialog").getByLabel("Name").fill(name);
    await signedIn
      .getByRole("dialog")
      .getByRole("button", { name: "Add, awaiting approval" })
      .click();
    await searchFor(signedIn, name);
    const row = signedIn.locator("tbody tr", { hasText: name });
    await row.getByRole("checkbox").check();
    await signedIn.getByRole("button", { name: "Promote to production" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText(
      "moved into production",
    );

    await signedIn.getByRole("tab", { name: /^Manufacturer pages/ }).click();
    await expect(signedIn.getByLabel("Showing")).toBeEnabled();
    await signedIn.getByLabel("Showing").selectOption("approved");
    const production = signedIn.getByTestId("maker-pages-production");
    await production.getByLabel("Model").fill(name);
    await production
      .getByLabel("Manufacturer's page")
      .fill("https://maker.example/first");
    await production.getByRole("button", { name: "Add manufacturer page" }).click();
    const listed = production.locator("tbody tr", { hasText: name });
    await expect(listed.getByRole("link")).toHaveAttribute(
      "href",
      "https://maker.example/first",
    );

    await listed.getByRole("button", { name: `Edit the page for ${name}` }).click();
    await listed
      .getByLabel(`Manufacturer's page for ${name}`)
      .fill("https://maker.example/second");
    await listed.getByRole("button", { name: "Save" }).click();
    await expect(listed.getByRole("link")).toHaveAttribute(
      "href",
      "https://maker.example/second",
    );

    await listed.getByRole("button", { name: `Remove the page for ${name}` }).click();
    await expect(production.locator("tbody tr", { hasText: name })).toHaveCount(0);
    // Awaiting approval and Rejected are not on the Production view.
    await expect(signedIn.getByTestId("maker-page-suggestions")).toHaveCount(0);
    await expect(signedIn.getByTestId("maker-pages-rejected")).toHaveCount(0);

    // Leave the armory as found.
    await signedIn.getByRole("tab", { name: "Models" }).click();
    await signedIn.getByLabel("Showing").selectOption("");
    await searchFor(signedIn, name);
    await signedIn.getByRole("button", { name: `Delete ${name}` }).click();
    await signedIn
      .getByRole("dialog")
      .getByRole("button", { name: /^Delete/ })
      .click();
    await expect(signedIn.locator("tbody tr", { hasText: name })).toHaveCount(0);
  });

  test("a rejected page can be accepted anyway", async ({ signedIn }) => {
    const asked = [];
    await signedIn.route("**/api/armory/references**", async (route) => {
      const request = route.request();
      if (request.method() !== "GET") {
        asked.push([request.url(), request.postDataJSON?.()]);
        await route.fulfill({ json: { changed: 1, message: "ok" } });
        return;
      }
      const rejected = new URL(request.url()).searchParams.get("status") === "rejected";
      await route.fulfill({
        json: rejected
          ? [
              {
                id: 9,
                field: "maker_page",
                status: "rejected",
                target_type: "model",
                target_id: 4,
                target_name: "Colt Cobra",
                url: "https://www.colt.com/detail-page/blued-king-cobra/",
                title: "blued-king-cobra",
                confident: false,
                reason: "in the manufacturer's sitemap",
              },
            ]
          : [],
      });
    });
    await openPage(signedIn, "Armory");
    await signedIn.getByRole("tab", { name: /^Manufacturer pages/ }).click();
    await signedIn.getByLabel("Showing").selectOption({ label: "Rejected" });
    const rejected = signedIn.getByTestId("maker-pages-rejected");
    await expect(rejected).toContainText("Colt Cobra");
    await rejected.getByRole("button", { name: /anyway$/ }).click();
    await expect.poll(() => asked.length).toBe(1);
    expect(asked[0][0]).toContain("/references/accept");
    expect(asked[0][1]).toEqual({ ids: [9] });
  });
});

test("Site settings starts a read of the manufacturers' sites", async ({ signedIn }) => {
  // Stubbed: a real request would start a real run against their sites.
  const jobs = [
    { name: "variants", requested_at: null, last_run_at: null },
    {
      name: "pages",
      requested_at: null,
      last_run_at: new Date().toISOString(),
      last_status: "ok",
      last_summary: "Asked about 184 model(s): 151 page(s) suggested",
    },
  ];
  const asked = [];
  await signedIn.route("**/api/manufacturer-data**", async (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      asked.push(new URL(request.url()).pathname);
      jobs[0] = { ...jobs[0], requested_at: new Date().toISOString() };
    }
    await route.fulfill({ json: jobs });
  });
  await openPage(signedIn, "Site settings");
  const section = signedIn.getByTestId("manufacturer-data-section");
  await expect(section.getByTestId("manufacturer-job-pages")).toContainText(
    "151 page(s) suggested",
  );
  await section.getByRole("button", { name: "Update MSRPs and variants" }).click();
  await expect.poll(() => asked).toEqual(["/api/manufacturer-data/variants/run"]);
  await expect(section.getByRole("button", { name: "Asked for" })).toBeDisabled();
  await expect(
    section.getByRole("button", { name: "Find manufacturer pages" }),
  ).toBeEnabled();
});

test("what the armory knows stays inside its own column", async ({ signedIn }) => {
  // On 2026-10-13 it ran on into the C&R column beside it: a button never
  // wraps, and "Walther PDP Pistol" left the column narrower than its words.
  await signedIn.setViewportSize({ width: 1440, height: 900 });
  await signedIn.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    const item = await response.json();
    item.model = "Walther PDP";
    item.model_kind = "pistol";
    item.firearm_model_id = item.firearm_model_id || 1;
    await route.fulfill({ response, json: item });
  });
  await signedIn.goto("/?availability=all");
  await signedIn.locator(".item-card").first().click();
  const button = signedIn.getByRole("button", { name: "What the armory knows" });
  await expect(button).toBeVisible();
  const own = await button.evaluate((el) => {
    const column = el.closest(".fact__value").parentElement.getBoundingClientRect();
    return { right: el.getBoundingClientRect().right, edge: column.right };
  });
  expect(own.right).toBeLessThanOrEqual(own.edge + 0.5);
});
