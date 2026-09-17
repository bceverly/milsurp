/**
 * The price filter in the browse rail.
 *
 * It did not exist until now: the API has taken `min_price` and `max_price`
 * since the beginning and nothing on screen ever set them. What these hold is
 * that it is a *filter* — the URL carries it, the chip row shows it, and the
 * histogram deliberately does not reshape itself around its own setting.
 */
import { test, expect } from "./fixtures.js";

test.describe("price filter", () => {
  // A <details>, folded on arrival like every other facet.
  //
  // Matched on the summary exactly, not on `hasText: "Price"`: the
  // Availability facet contains the words "Price reduced", so the loose
  // version picks that one, opens it, and then waits ten seconds for a number
  // box that is still folded away inside the facet nobody touched.
  function priceFacet(page) {
    return page
      .locator(".facet")
      .filter({ has: page.locator("summary", { hasText: /^Price$/i }) });
  }

  async function openPrice(page) {
    const facet = priceFacet(page);
    await expect(facet).toBeVisible();
    if (!(await facet.evaluate((node) => node.open))) {
      await facet.locator("summary").click();
    }
  }

  test.beforeEach(async ({ signedIn }) => {
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
    await openPrice(signedIn);
  });

  test("shows the shape of what the results cost", async ({ signedIn }) => {
    await expect(signedIn.locator(".price-range__chart")).toBeVisible();
    const bars = signedIn.locator(".price-range__bar");
    expect(await bars.count()).toBeGreaterThan(1);
    await expect(signedIn.locator(".price-range__note")).toContainText("Most are");
  });

  test("a typed bound filters the results and lands in the URL", async ({ signedIn }) => {
    const before = await signedIn
      .locator(".browse__count, .page-head p")
      .first()
      .innerText();
    await signedIn.getByLabel("Min", { exact: true }).fill("100000");
    await expect(signedIn).toHaveURL(/min_price=100000/);
    // Nothing in the sample catalog costs six figures, so this is the empty
    // state — which is a real answer and has to be reachable.
    await expect(signedIn.locator(".browse__count, .page-head p").first()).not.toHaveText(
      before,
    );
  });

  test("the range shows as one chip and clears as one", async ({ signedIn }) => {
    await signedIn.getByLabel("Min", { exact: true }).fill("200");
    const chip = signedIn.getByRole("button", { name: /Price: .* – any/ });
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(signedIn).not.toHaveURL(/min_price/);
  });

  test("the histogram keeps its full shape when the range narrows", async ({
    signedIn,
  }) => {
    // The one that matters. Shaped by its own setting, the chart would redraw
    // as only the slice you chose and there would be nothing to widen towards.
    const shape = () =>
      signedIn
        .locator(".price-range__bar")
        .evaluateAll((bars) => bars.map((bar) => bar.style.height).join(","));
    const before = await shape();
    await signedIn.getByLabel("Min", { exact: true }).fill("200");
    await expect(signedIn).toHaveURL(/min_price=200/);
    expect(await shape()).toEqual(before);
  });

  test("the handles are reachable from the keyboard", async ({ signedIn }) => {
    const lowest = signedIn.getByLabel("Lowest price");
    await expect(lowest).toBeVisible();
    await lowest.focus();
    await signedIn.keyboard.press("ArrowRight");
    await expect(signedIn).toHaveURL(/min_price=/);
  });
});
