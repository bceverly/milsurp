/**
 * The market page.
 *
 * What it holds are the two decisions a reader could be misled by if the page
 * did not make them visible: the spread is percentiles rather than the range,
 * and a band drawn from one shop is that shop's pricing rather than the
 * market's.
 */
import { test, expect } from "./fixtures.js";

test.describe("market", () => {
  test.beforeEach(async ({ signedIn }) => {
    await signedIn.getByRole("link", { name: "Market" }).click();
    await expect(signedIn.getByRole("heading", { name: "Market" })).toBeVisible();
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

  test("a band links through to the listings behind it", async ({ signedIn }) => {
    await signedIn.locator("tbody tr td:first-child a").first().click();
    await expect(signedIn).toHaveURL(/\/\?caliber=/);
  });

  test("it says how much it left out, rather than quietly showing less", async ({
    signedIn,
  }) => {
    await expect(signedIn.locator(".market-footnote")).toContainText("considered");
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
