/**
 * The collection page in the states a demo database never reaches.
 *
 * The seeded catalog is young: nothing has left the shelf in any number, no
 * listing states a condition a collection row shares, and nobody has made a
 * loss yet. Those are the states the page says the most careful things in --
 * which list set the value, how narrow the comparison was, that a total covers
 * only some of the guns -- so they are drawn here from answers the server
 * would give, rather than left untested.
 */
import { test, expect } from "./fixtures.js";

const BAND = (median, listings = 7) => ({
  value: "12",
  listings,
  low: median - 50,
  median,
  high: median + 50,
  currency: "USD",
  sites: 3,
  top_site_share: 0.4,
  concentrated: false,
});

const ROWS = [
  {
    id: 71,
    title: "Swiss K31, 1943",
    firearm_model_id: 12,
    model: "Swiss K31",
    model_declined: false,
    caliber: "7.5x55mm Swiss",
    manufacturer: "W+F Bern",
    condition_grade: "very_good",
    condition_grade_label: "Very good",
    acquired_on: "2021-06-01",
    paid: 600,
    acquired_from: "A gun show",
    item_id: null,
    notes: "Bought from a neighbor",
    created_at: "2026-09-01T12:00:00Z",
    updated_at: "2026-09-01T12:00:00Z",
    valuation: {
      estimate: 450,
      basis: "left",
      like_for_like: true,
      shelf: BAND(520),
      departed: BAND(450),
    },
  },
  {
    id: 72,
    title: "Mosin M91/30",
    firearm_model_id: 14,
    model: "Mosin-Nagant M91/30",
    model_declined: false,
    caliber: null,
    manufacturer: null,
    condition_grade: null,
    condition_grade_label: null,
    acquired_on: null,
    paid: null,
    acquired_from: null,
    item_id: null,
    notes: null,
    created_at: "2026-09-01T12:00:00Z",
    updated_at: "2026-09-01T12:00:00Z",
    valuation: null,
  },
  {
    id: 73,
    title: "Something odd",
    firearm_model_id: null,
    model: null,
    model_declined: true,
    caliber: null,
    manufacturer: null,
    condition_grade: null,
    condition_grade_label: null,
    acquired_on: null,
    paid: 100,
    acquired_from: null,
    item_id: null,
    notes: null,
    created_at: "2026-09-01T12:00:00Z",
    updated_at: "2026-09-01T12:00:00Z",
    valuation: null,
  },
];

const TOTALS = {
  count: 3,
  paid: 700,
  paid_count: 2,
  value: 450,
  valued_count: 1,
  compared_count: 1,
  compared_paid: 600,
  compared_value: 450,
};

const LISTING = (id, overrides = {}) => ({
  item_id: id,
  title: `Swiss K31 number ${id}`,
  site_name: "Shop",
  price: 450,
  currency: "USD",
  condition_grade_label: "Very good",
  left_at: null,
  marked_sold: false,
  ...overrides,
});

async function show(page, { rows = ROWS, totals = TOTALS, comparables = null } = {}) {
  await page.route("**/api/collection", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { items: rows, totals } })
      : route.fallback(),
  );
  if (comparables) {
    await page.route("**/api/collection/*/comparables", (route) =>
      typeof comparables === "function"
        ? comparables(route)
        : route.fulfill({ json: comparables }),
    );
  }
  await page.goto("/collection");
  await expect(
    page.getByRole("heading", { name: "Collection", exact: true }),
  ).toBeVisible();
}

test.describe("the collection, as the market sees it", () => {
  test("a value from departures, narrowed to the same condition", async ({
    signedIn,
  }) => {
    await show(signedIn);
    const row = signedIn.locator("tr", { hasText: "Swiss K31, 1943" });
    await expect(row).toContainText("$450");
    await expect(row.locator(".collection-range")).toContainText("$400–$500");
    await expect(row).toContainText(
      "What Swiss K31s in the same condition were asking when they left the shelf",
    );
    await expect(row.getByRole("link", { name: "See the 7 listings" })).toHaveAttribute(
      "href",
      "/?model=12&guns_only=true&grade=very_good&availability=left",
    );
  });

  test("a gun too thin to value, and one with no model", async ({ signedIn }) => {
    await show(signedIn);
    await expect(signedIn.locator("tr", { hasText: "Mosin M91/30" })).toContainText(
      "Too few listings to say",
    );
    const odd = signedIn.locator("tr", { hasText: "Something odd" });
    await expect(odd).toContainText("Not matched to a model");
    await expect(odd.getByRole("button", { name: "Show comparables" })).toHaveCount(0);
  });

  test("totals say what they cover, and a loss is a loss", async ({ signedIn }) => {
    await show(signedIn);
    const totals = signedIn.getByTestId("collection-totals");
    await expect(totals).toContainText("3");
    await expect(totals).toContainText("(2 say)");
    await expect(totals).toContainText("(1 the market can price)");
    await expect(totals).toContainText("−25%");
  });

  test("a gain, over the guns that have both", async ({ signedIn }) => {
    await show(signedIn, {
      rows: [ROWS[0]],
      totals: {
        ...TOTALS,
        count: 1,
        paid: 300,
        paid_count: 1,
        valued_count: 1,
        compared_paid: 300,
      },
    });
    await expect(signedIn.getByTestId("collection-totals")).toContainText("+50%");
  });

  test("a list that cannot be loaded says so", async ({ signedIn }) => {
    await signedIn.route("**/api/collection", (route) =>
      route.fulfill({ status: 500, json: { detail: "The database is busy." } }),
    );
    await signedIn.goto("/collection");
    await expect(signedIn.getByRole("alert")).toContainText("The database is busy.");
  });
});

test.describe("comparables", () => {
  test("both lists, which one set the value, and how they left", async ({ signedIn }) => {
    await show(signedIn, {
      comparables: {
        model: "Swiss K31",
        grade_label: "Very good",
        valuation: ROWS[0].valuation,
        departed: [
          LISTING(1, { left_at: "2026-09-20T12:00:00Z", marked_sold: true }),
          LISTING(2, { left_at: "2026-09-21T12:00:00Z", site_name: null }),
          LISTING(3, { price: null, condition_grade_label: null }),
        ],
        shelf: [LISTING(4), LISTING(5)],
        limit: 2,
      },
    });
    const row = signedIn.locator("tr", { hasText: "Swiss K31, 1943" });
    await row.getByRole("button", { name: "Show comparables" }).click();
    const dialog = signedIn.getByTestId("comparables");
    await expect(dialog).toContainText("in very good condition, like yours");
    await expect(dialog).toContainText("Worth about $450");
    await expect(
      dialog.getByRole("heading", { name: /Left the shelf/ }).locator(".chip"),
    ).toHaveText("sets the value");
    await expect(dialog).toContainText("marked sold");
    await expect(dialog).toContainText("taken down");
    await expect(dialog).toContainText("Showing the first 2");
    await expect(
      dialog.getByRole("link", { name: "Open these in the inventory" }),
    ).toHaveCount(2);
    await dialog
      .getByRole("link", { name: "Open these in the inventory" })
      .first()
      .click();
    await expect(signedIn).toHaveURL(/availability=left/);
  });

  test("nothing on either list, set from the shelf", async ({ signedIn }) => {
    await show(signedIn, {
      rows: [
        {
          ...ROWS[0],
          valuation: {
            ...ROWS[0].valuation,
            basis: "shelf",
            like_for_like: false,
            departed: null,
          },
        },
      ],
      comparables: {
        model: "Swiss K31",
        grade_label: null,
        valuation: {
          ...ROWS[0].valuation,
          basis: "shelf",
          like_for_like: false,
          departed: null,
        },
        departed: [],
        shelf: [],
        limit: 50,
      },
    });
    const row = signedIn.locator("tr", { hasText: "Swiss K31, 1943" });
    await expect(row).toContainText("What Swiss K31s are asking now");
    await row.getByRole("button", { name: "Show comparables" }).click();
    const dialog = signedIn.getByTestId("comparables");
    await expect(dialog).toContainText("in any condition");
    await expect(dialog).toContainText("None have left the shelf yet.");
    await expect(dialog).toContainText("None are for sale right now.");
    await expect(
      dialog.getByRole("heading", { name: /On the shelf now/ }).locator(".chip"),
    ).toHaveText("sets the value");
  });

  test("a row whose model was cleared since, and a failed request", async ({
    signedIn,
  }) => {
    let calls = 0;
    await show(signedIn, {
      comparables: (route) => {
        calls += 1;
        return calls === 1
          ? route.fulfill({
              json: {
                model: null,
                grade_label: null,
                valuation: null,
                departed: [],
                shelf: [],
                limit: 50,
              },
            })
          : route.fulfill({ status: 500, json: { detail: "Could not compare." } });
      },
    });
    const row = signedIn.locator("tr", { hasText: "Swiss K31, 1943" });
    await row.getByRole("button", { name: "Show comparables" }).click();
    await expect(signedIn.getByTestId("comparables")).toContainText(
      "nothing to compare it with",
    );
    await signedIn.locator(".modal__foot").getByRole("button", { name: "Close" }).click();

    await row.getByRole("button", { name: "Show comparables" }).click();
    await expect(signedIn.getByRole("dialog")).toContainText("Could not compare.");
  });
});

test.describe("editing", () => {
  test("a model is chosen from the armory, and a refused save says why", async ({
    signedIn,
  }) => {
    await show(signedIn);
    await signedIn.route("**/api/collection/models*", (route) =>
      route.fulfill({
        json: new URL(route.request().url()).searchParams.get("search")
          ? [{ id: 12, name: "Swiss K31", kind: "carbine", country: "Switzerland" }]
          : [],
      }),
    );
    await signedIn.route("**/api/collection/73", (route) =>
      route.request().method() === "PATCH"
        ? route.fulfill({ status: 400, json: { detail: "That is not a price." } })
        : route.fallback(),
    );
    await signedIn
      .locator("tr", { hasText: "Something odd" })
      .getByRole("button", { name: "Something odd", exact: true })
      .click();
    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toContainText("cannot be valued");
    await expect(dialog).toContainText("No model by that name.");
    await dialog.getByLabel("Model").fill("K31");
    await dialog.getByRole("button", { name: /^Swiss K31/ }).click();
    await expect(dialog.locator(".model-picker__current")).toContainText("Swiss K31");
    await dialog.getByRole("button", { name: "Change" }).click();
    await dialog.getByLabel("Model").fill("K31");
    await dialog.getByRole("button", { name: /^Swiss K31/ }).click();
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog.getByText("That is not a price.")).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
  });

  test("a model that is wrong can be taken off", async ({ signedIn }) => {
    await show(signedIn);
    await signedIn.route("**/api/collection/models*", (route) =>
      route.fulfill({ json: [] }),
    );
    let sent = null;
    await signedIn.route("**/api/collection/71", (route) => {
      if (route.request().method() !== "PATCH") return route.fallback();
      sent = route.request().postDataJSON();
      return route.fulfill({ json: { ...ROWS[0], firearm_model_id: null, model: null } });
    });
    await signedIn
      .locator("tr", { hasText: "Swiss K31, 1943" })
      .getByRole("button", { name: "Swiss K31, 1943", exact: true })
      .click();
    const dialog = signedIn.getByRole("dialog");
    await dialog.getByRole("button", { name: "Not this model" }).click();
    await expect(dialog).toContainText("cannot be valued");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    expect(sent.firearm_model_id).toBeNull();
  });

  test("an empty collection says how to start one", async ({ signedIn }) => {
    await show(signedIn, {
      rows: [],
      totals: {
        ...TOTALS,
        count: 0,
        paid: 0,
        paid_count: 0,
        value: 0,
        valued_count: 0,
        compared_count: 0,
        compared_paid: 0,
        compared_value: 0,
      },
    });
    await expect(
      signedIn.getByRole("heading", { name: "Nothing here yet" }),
    ).toBeVisible();
    await expect(signedIn.getByRole("link", { name: "Download" })).toHaveCount(0);
  });
});
