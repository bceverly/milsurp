/**
 * The market page.
 *
 * What it holds are the two decisions a reader could be misled by if the page
 * did not make them visible: the spread is percentiles rather than the range,
 * and a band drawn from one shop is that shop's pricing rather than the
 * market's.
 */
import { test, expect, openPage } from "./fixtures.js";

test.describe("market", () => {
  test.beforeEach(async ({ signedIn }) => {
    await openPage(signedIn, "Market");
  });

  test("shows a typical price and a spread for each band", async ({ signedIn }) => {
    await expect(signedIn.getByRole("columnheader", { name: "Typical" })).toBeVisible();
    await expect(signedIn.getByRole("columnheader", { name: "Spread" })).toBeVisible();
    const rows = signedIn.locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    // Every row draws its bar against the same ceiling, which is the only
    // reason to draw one rather than print three numbers.
    await expect(rows.first().locator(".market-bar")).toBeVisible();
  });

  test("the dimension can be changed", async ({ signedIn }) => {
    const first = await signedIn.locator("tbody tr td:first-child").first().innerText();
    await signedIn.getByRole("tab", { name: "Country" }).click();
    await expect(signedIn.getByRole("columnheader", { name: "Country" })).toBeVisible();
    await expect(signedIn.locator("tbody tr td:first-child").first()).not.toHaveText(
      first,
    );
  });

  test("the caliber, listings and typical columns sort when clicked", async ({
    signedIn,
  }) => {
    // The price bands are the first table; how-fast-it-sells is the second.
    const bands = signedIn.locator("table").first();
    await expect(bands.locator("tbody tr").first()).toBeVisible();
    const column = (index) =>
      bands.locator(`tbody tr td:nth-child(${index})`).allInnerTexts();
    const money = (text) => Number(text.replace(/[^0-9.]/g, ""));
    const count = (text) => Number(text.replace(/[^0-9]/g, ""));
    const ascending = (values) => values.every((v, i) => i === 0 || values[i - 1] <= v);
    const descending = (values) => values.every((v, i) => i === 0 || values[i - 1] >= v);

    // Busiest first until a heading is clicked; clicking it again reverses.
    expect(descending((await column(2)).map(count))).toBe(true);
    await bands.getByRole("button", { name: "Listings" }).click();
    await expect(bands.getByRole("columnheader", { name: "Listings" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(ascending((await column(2)).map(count))).toBe(true);

    // A price starts from the top.
    await bands.getByRole("button", { name: "Typical" }).click();
    await expect(bands.getByRole("columnheader", { name: "Typical" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(descending((await column(3)).map(money))).toBe(true);

    // And the name column, from A.
    await bands.getByRole("button", { name: "Caliber" }).click();
    await expect(bands.getByRole("columnheader", { name: "Caliber" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
  });

  test("a band links through to the listings behind it", async ({ signedIn }) => {
    await signedIn.locator("tbody tr td:first-child a").first().click();
    await expect(signedIn).toHaveURL(/\/\?caliber=/);
  });

  test("it says how much it left out, rather than quietly showing less", async ({
    signedIn,
  }) => {
    await expect(signedIn.locator(".market-footnote").first()).toContainText(
      "considered",
    );
  });

  test("how fast things sell is its own section, and says what it counts", async ({
    signedIn,
  }) => {
    const section = signedIn.getByRole("region", { name: "How fast they sell" });
    await expect(section).toBeVisible();
    // The sample data has no sales watched from start to finish, and the
    // section must say so rather than render an empty table.
    const empty = section.getByTestId("turnover-empty");
    const table = section.getByTestId("turnover-table");
    await expect(empty.or(table)).toBeVisible();

    await section.getByRole("tab", { name: "Caliber" }).click();
    await expect(section.getByRole("tab", { name: "Caliber" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(section.locator(".market-footnote")).toContainText(
      "sales watched from start to finish",
    );
  });

  test("including accessories is a choice the reader makes", async ({ signedIn }) => {
    // A caliber's listings mix rifles with bayonets and magazines, so the
    // default excludes them — and says so where the switch is.
    const toggle = signedIn.getByLabel(/Firearms only/);
    await expect(toggle).toBeChecked();

    // Asserted on the request rather than on the numbers. The sample catalog
    // prices only firearms, so including accessories changes no count in it —
    // and a test that watched the total would pass just as happily if the
    // switch were wired to nothing at all. Which it was: `qs` drops a false
    // boolean, so the first version of this sent `firearms_only` nowhere and
    // the server's default quietly won. This is the test that found it.
    const [request] = await Promise.all([
      signedIn.waitForRequest(
        (r) =>
          r.url().includes("/api/market") && r.url().includes("include_accessories=true"),
      ),
      toggle.uncheck(),
    ]);
    expect(request.url()).toContain("by=caliber");
  });
});
