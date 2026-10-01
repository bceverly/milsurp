/**
 * For your guns, worth over time, the shops page, "will it drop?" and the
 * monthly market report.
 *
 * The demo catalog is a few weeks of nothing much: no shop has cut ten
 * prices, and no collection has been valued twice. Those states are drawn
 * from answers the server would give, as collection-states.spec.js does; the
 * rest runs against the seeded catalog.
 */
import { test, expect, openPage } from "./fixtures.js";

test.describe("for your guns", () => {
  test("a gun's caliber finds its clips", async ({ signedIn }) => {
    await openPage(signedIn, "Collection");
    await signedIn.getByRole("button", { name: "Add a gun" }).click();
    const dialog = signedIn.getByRole("dialog");
    await dialog.getByLabel("What it is").fill("Dad's Mauser");
    await dialog.getByLabel("Caliber").fill("8mm Mauser");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(signedIn.locator("tr", { hasText: "Dad's Mauser" })).toBeVisible();

    await signedIn.getByRole("tab", { name: "For your guns" }).click();
    await expect(signedIn).toHaveURL(/#for-your-guns/);
    const fits = signedIn.getByTestId("for-your-guns");
    await expect(fits).toContainText("Dad's Mauser");
    await expect(fits).toContainText("Stripper clips, 8mm Mauser");

    await signedIn.getByRole("tab", { name: "Your guns", exact: true }).click();
    const row = signedIn.locator("tr", { hasText: "Dad's Mauser" });
    await row.getByRole("button", { name: /^Remove/ }).click();
    await signedIn.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
  });

  test("gun by gun, with what has nothing", async ({ signedIn }) => {
    const listing = (id, title) => ({
      id,
      title,
      site_id: 1,
      site_name: "Shop",
      url: "https://x.test",
      current_price: 30,
      currency: "USD",
      is_rifle: false,
      is_pistol: false,
      is_sold: false,
      is_active: true,
      first_seen_at: "2026-09-20T12:00:00Z",
      last_seen_at: "2026-09-30T12:00:00Z",
    });
    await signedIn.route("**/api/collection/for-your-guns", (route) =>
      route.fulfill({
        json: [
          {
            row_id: 1,
            title: "Carcano Carbine",
            model: "Carcano M91 Cavalry Carbine",
            calibers: ["6.5x52mm Carcano"],
            ammo: [
              listing(11, "Carcano 6 round clip"),
              listing(12, "Carcano clip, brass"),
            ],
            ammo_total: 6,
            accessories: [listing(13, "Moschetto 91 bayonet")],
            accessories_total: 1,
          },
          {
            row_id: 2,
            title: "Something odd",
            model: null,
            calibers: [],
            ammo: [],
            ammo_total: 0,
            accessories: [],
            accessories_total: 0,
          },
        ],
      }),
    );
    await signedIn.route("**/api/collection", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({
            json: {
              items: [
                {
                  id: 1,
                  title: "Carcano Carbine",
                  created_at: "2026-09-01T00:00:00Z",
                  updated_at: "2026-09-01T00:00:00Z",
                },
              ],
              totals: {
                count: 1,
                paid: 0,
                paid_count: 0,
                value: 0,
                valued_count: 0,
                compared_count: 0,
                compared_paid: 0,
                compared_value: 0,
              },
              history: [],
            },
          })
        : route.fallback(),
    );
    await signedIn.goto("/collection#for-your-guns");
    const fits = signedIn.getByTestId("for-your-guns");
    await expect(fits).toContainText("Ammunition and clips (6)");
    await expect(fits).toContainText("Showing 2 of 6");
    await expect(fits).toContainText("Moschetto 91 bayonet");
    await expect(fits).toContainText("Nothing for sale right now for Something odd");
    await expect(fits).toContainText("A gun with no model only matches ammunition");
  });
});

test.describe("worth over time", () => {
  const collection = (history) => ({
    items: [
      {
        id: 1,
        title: "Swiss K31",
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
      },
    ],
    totals: {
      count: 1,
      paid: 300,
      paid_count: 1,
      value: 450,
      valued_count: 1,
      compared_count: 1,
      compared_paid: 300,
      compared_value: 450,
    },
    history,
  });

  test("one snapshot is said in words, several are a line", async ({ signedIn }) => {
    let history = [{ day: "2026-09-24", value: 430, guns: 1 }];
    await signedIn.route("**/api/collection", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: collection(history) })
        : route.fallback(),
    );
    await signedIn.goto("/collection");
    await expect(signedIn.getByTestId("worth-chart")).toContainText(
      "A line appears here once a second weekly snapshot is recorded",
    );

    history = [
      { day: "2026-09-17", value: 410, guns: 1 },
      { day: "2026-09-24", value: 430, guns: 1 },
      { day: "2026-10-01", value: 450, guns: 1 },
    ];
    await signedIn.reload();
    const chart = signedIn.getByTestId("worth-chart");
    await expect(chart.locator("polyline")).toHaveCount(1);
    await expect(chart.locator("circle")).toHaveCount(3);
    await expect(chart).toContainText("$450");
  });
});

test.describe("shops", () => {
  test("every shop, sortable", async ({ signedIn }) => {
    await openPage(signedIn, "Shops");
    const table = signedIn.getByTestId("shops-table");
    await expect(table.locator("tbody tr").first()).toBeVisible();
    await table.getByRole("button", { name: /^Shop/ }).click();
    const first = await table.locator("tbody tr td:first-child").first().innerText();
    await table.getByRole("button", { name: /^Shop/ }).click();
    await expect(table.locator("tbody tr td:first-child").first()).not.toHaveText(first);
    for (const name of [/^Price/, /^Sells in/, /^Cuts prices/, /^For sale/]) {
      await table.getByRole("button", { name }).click();
    }
  });

  test("what a shop with a full record says", async ({ signedIn }) => {
    await signedIn.route("**/api/market/shops", (route) =>
      route.fulfill({
        json: [
          {
            site_id: 1,
            name: "Simpson",
            slug: "simpson-ltd",
            guns_for_sale: 4758,
            new_this_week: 55,
            arrivals_by_weekday: [3, 1, 4, 9, 12, 0, 0],
            busiest_day: "Friday",
            price_vs_market: 0.783,
            compared: 1428,
            sell_days: 10.1,
            sold_measured: 60,
            left_last_30_days: 80,
            habit: { drops: 114, median_day: 18.1, median_pct: 10, share: 0.024 },
          },
          {
            site_id: 2,
            name: "Legacy",
            slug: "legacy-collectibles",
            guns_for_sale: 1044,
            new_this_week: 0,
            arrivals_by_weekday: [0, 0, 0, 0, 0, 0, 0],
            busiest_day: null,
            price_vs_market: 1.01,
            compared: 9,
            sell_days: null,
            sold_measured: 0,
            left_last_30_days: 0,
            habit: null,
          },
        ],
      }),
    );
    await signedIn.goto("/shops");
    const simpson = signedIn.locator("tr", { hasText: "Simpson" });
    await expect(simpson).toContainText("22% below");
    await expect(simpson).toContainText("Mostly Friday");
    await expect(simpson).toContainText("About 10% around day 18");
    await expect(simpson).toContainText("55 new this week");
    await expect(signedIn.locator("tr", { hasText: "Legacy" })).toContainText(
      "About the market",
    );
  });
});

test.describe("will it drop?", () => {
  async function withHabit(page, listedDays) {
    await page.route(/\/api\/items\/\d+$/, async (route) => {
      const response = await route.fetch();
      const item = await response.json();
      item.markdown_habit = {
        drops: 114,
        median_day: 18.1,
        median_pct: 10,
        share: 0.024,
        site_name: "Simpson Ltd.",
        listed_days: listedDays,
      };
      await route.fulfill({ response, json: item });
    });
    await page.goto("/?availability=all");
    await page.locator(".item-card").first().click();
  }

  test("before the shop's usual day", async ({ signedIn }) => {
    await withHabit(signedIn, 12);
    const line = signedIn.getByTestId("will-it-drop");
    await expect(line).toContainText("usually by about 10% around day 18");
    await expect(line).toContainText("This one is on day 12.");
  });

  test("after it", async ({ signedIn }) => {
    await withHabit(signedIn, 30);
    await expect(signedIn.getByTestId("will-it-drop")).toContainText(
      "has been up 30 days and has not been cut yet",
    );
  });
});

test.describe("the monthly market report", () => {
  test("switched on and off, and asked for now", async ({ signedIn }) => {
    await openPage(signedIn, "Email digest");
    const panel = signedIn.getByTestId("market-report");
    const toggle = panel.getByLabel("Send me the monthly market report");
    await toggle.check();
    await expect(toggle).toBeChecked();
    await toggle.uncheck();
    await expect(toggle).not.toBeChecked();
    // Email is switched off in the test deployment, and the panel says so.
    await panel.getByRole("button", { name: "Send a report now" }).click();
    await expect(panel.locator(".alert")).toBeVisible();
  });

  test("a sent one says so", async ({ signedIn }) => {
    await signedIn.route("**/api/preferences/email/market-report", (route) =>
      route.fulfill({ json: { message: "Sent to admin@example.test." } }),
    );
    await openPage(signedIn, "Email digest");
    const panel = signedIn.getByTestId("market-report");
    await panel.getByRole("button", { name: "Send a report now" }).click();
    await expect(panel.locator(".alert--success")).toContainText("Sent to");
  });
});
