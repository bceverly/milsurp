/**
 * The hot deals page.
 *
 * What it holds is the shape of the page rather than the arithmetic — the rule
 * itself is measured in `backend/tests/test_hotdeals.py`, where a fixture can
 * say what a bargain is without depending on a seeded catalog.
 *
 * Three things here are worth pinning. Every row shows its *evidence*, because
 * a discount with nothing behind it is a marketing claim. The three filters are
 * always offered with their counts, including the empty one — police surplus is
 * a small corner of any catalog and a tab that vanished when it was empty would
 * read as a missing feature. And the operator's panel and the reader's panel
 * come apart cleanly: everybody chooses their own categories, only an
 * administrator changes what counts as a deal for everybody.
 */
import { test, expect } from "./fixtures.js";

test.describe("hot deals", () => {
  test.beforeEach(async ({ signedIn }) => {
    await signedIn.getByRole("link", { name: "Hot deals" }).click();
    await expect(signedIn.getByRole("heading", { name: "Hot deals" })).toBeVisible();
  });

  test("lists what is cheap for what it is", async ({ signedIn }) => {
    const rows = signedIn.locator(".deal");
    await expect(rows.first()).toBeVisible();
    // The saving first and in colour: nobody opens this page to browse.
    await expect(rows.first().locator(".deal__headline")).toContainText(
      /% below the usual price/,
    );
  });

  test("and says what the claim rests on", async ({ signedIn }) => {
    // "50% off" is a marketing claim. "50% off, 9 listed across 7 shops" is a
    // measurement, and the difference is the whole point of the page.
    const meta = signedIn.locator(".deal").first().locator(".deal__meta");
    await expect(meta).toContainText(/Usually \$/);
    await expect(meta).toContainText(/listed across \d+ shops?/);
    await expect(meta).toContainText(/Cheaper than \d+% of them/);
  });

  test("the three filters are always offered, empty ones included", async ({
    signedIn,
  }) => {
    for (const name of [/^Rifles/, /^Handguns/, /^Police surplus/]) {
      await expect(signedIn.getByRole("tab", { name })).toBeVisible();
    }
    // Police surplus is a small corner of any catalog. A tab that disappeared
    // when it was empty would read as a missing feature rather than an empty
    // one, so it stays and carries its count.
    await expect(signedIn.getByRole("tab", { name: /^Police surplus/ })).toContainText(
      "(0)",
    );
  });

  test("choosing one narrows the list without changing the counts", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("tab", { name: /^Handguns/ }).click();
    await expect(signedIn.locator(".deal")).toHaveCount(1);
    // The tabs still describe the whole page, which is the point of a count
    // on a tab you are not looking at.
    await expect(signedIn.getByRole("tab", { name: /^Rifles/ })).toContainText("(1)");
  });

  test("an empty category says why rather than showing nothing", async ({ signedIn }) => {
    await signedIn.getByRole("tab", { name: /^Police surplus/ }).click();
    await expect(signedIn.locator(".deal")).toHaveCount(0);
    await expect(signedIn.getByText(/Nothing here at the moment/)).toBeVisible();
  });

  test("a deal links through to the listing behind it", async ({ signedIn }) => {
    await signedIn.locator(".deal__link").first().click();
    await expect(signedIn).toHaveURL(/\/items\/\d+/);
  });

  // The row has to hold its shape while its photo is missing, and that is not
  // a cosmetic nicety: AuthImage stands in for an absent photo with a box that
  // fills whatever contains it, which is right inside a card and wrong inside
  // a row. When the stand-in dropped the caller's class it claimed the whole
  // row and shoved the title and the price against the right-hand edge, so a
  // page whose photos were slow to arrive — this one, at a hundred and fifty
  // rows — looked broken until they did. Every photo is refused here, which is
  // the same state as one that has not arrived yet.
  test("a row keeps its shape when the photo does not arrive", async ({ signedIn }) => {
    await signedIn.route("**/api/items/*/photos/*", (route) => route.abort());
    await signedIn.reload();
    await expect(signedIn.locator(".deal").first()).toBeVisible();

    const boxes = await signedIn.locator(".deal").evaluateAll((rows) =>
      rows.map((row) => ({
        thumb: row.querySelector(".deal__link > *").getBoundingClientRect().width,
        text: Math.round(row.querySelector(".deal__text").getBoundingClientRect().left),
      })),
    );

    expect(boxes.length).toBeGreaterThan(1);
    for (const box of boxes) expect(box.thumb).toBe(64);
    // One left edge for the whole column: the titles line up under each other
    // rather than each starting wherever its own row happened to leave room.
    expect(new Set(boxes.map((box) => box.text)).size).toBe(1);
  });

  const titles = (page) => page.locator(".deal__title").allTextContents();

  test("the list can be re-ordered, and the orders come from the server", async ({
    signedIn,
  }) => {
    const box = signedIn.getByLabel("Sort by");
    // The wording is the server's, so the page and the email cannot drift.
    await expect(box.locator("option").first()).toHaveText("Biggest discount");

    const byDiscount = await titles(signedIn);
    expect(byDiscount.length).toBeGreaterThan(1);

    await box.selectOption("price_desc");
    await expect.poll(() => titles(signedIn)).not.toEqual(byDiscount);
    // The seeded catalog's two deals rank opposite ways by discount and by
    // price, so a straight reversal is the proof the list really turned over.
    const byPrice = await titles(signedIn);
    expect([...byPrice].reverse()).toEqual(byDiscount);
  });

  test("and the order is the server's doing, not a shuffle of what was sent", async ({
    signedIn,
  }) => {
    // The request carries it, which is what makes the order apply before the
    // row limit rather than after it.
    const asked = signedIn.waitForRequest(
      (request) =>
        request.url().includes("/api/hot-deals") && request.url().includes("sort="),
    );
    await signedIn.getByLabel("Sort by").selectOption("price_asc");
    expect((await asked).url()).toContain("sort=price_asc");
  });

  test("choosing an order survives changing something else on the page", async ({
    signedIn,
  }) => {
    // Every write answers with the whole page, so the page it answers with has
    // to be the one on screen — otherwise pressing anything at all silently
    // put the list back in the default order. Driven from the administrator's
    // "Look again now" rather than from a subscription checkbox: this suite
    // shares one database and runs in order, so a test that leaves a
    // preference switched off is a test that breaks the next one.
    //
    // **Asserted on the request, not on the rows.** The first version waited
    // for the list to visibly re-order, which needs the seeded catalog to hold
    // two deals that rank differently by discount and by price — and the specs
    // that run before this one edit models and calibers, which is what a
    // deal's peer group is built from. So it passed alone and failed in a full
    // run, which is a test reporting on its neighbours rather than on the
    // feature. What the feature promises is that the write carries the view,
    // and that is a fact about one request.
    const box = signedIn.getByLabel("Sort by");
    await box.selectOption("price_desc");
    await expect(box).toHaveValue("price_desc");

    const refresh = signedIn.waitForRequest(
      (request) =>
        request.url().includes("/api/hot-deals/refresh") && request.method() === "POST",
    );
    await signedIn.getByRole("button", { name: /Look again now/ }).click();
    expect((await refresh).url()).toContain("sort=price_desc");

    // ...and the box still says so once the answer lands, so the list and the
    // control above it cannot end up describing different things.
    await expect(box).toHaveValue("price_desc");
    await expect(signedIn.getByText(/comparable listings/)).toBeVisible();
  });

  // The checkbox inside a `.switch` is visually hidden so the track can be
  // styled, so the label is what gets clicked and the input is what gets
  // asserted on — the same split admin.spec.js uses for a site's switch.
  const switchFor = (page, name) =>
    page.locator("label.switch").filter({ hasText: name });

  test("the reader chooses which categories to be mailed about", async ({ signedIn }) => {
    // On by default, for everybody, without anyone having opted in.
    await expect(
      switchFor(signedIn, "Send me hot deals").getByRole("checkbox"),
    ).toBeChecked();

    const police = switchFor(signedIn, "Police surplus");
    await expect(police.getByRole("checkbox")).toBeChecked();
    await police.click();
    await expect(police.getByRole("checkbox")).not.toBeChecked();

    // It survives a reload, which is the only proof the change was saved
    // rather than merely rendered.
    await signedIn.reload();
    await expect(
      switchFor(signedIn, "Police surplus").getByRole("checkbox"),
    ).not.toBeChecked();
    await switchFor(signedIn, "Police surplus").click();
    await expect(
      switchFor(signedIn, "Police surplus").getByRole("checkbox"),
    ).toBeChecked();
  });

  test("turning the alert off disables the categories with it", async ({ signedIn }) => {
    const subscribed = switchFor(signedIn, "Send me hot deals");
    const rifles = switchFor(signedIn, "Rifles").getByRole("checkbox");

    await subscribed.click();
    await expect(subscribed.getByRole("checkbox")).not.toBeChecked();
    await expect(rifles).toBeDisabled();

    await subscribed.click();
    await expect(rifles).toBeEnabled();
  });

  test("an administrator can change what counts as a deal", async ({ signedIn }) => {
    await expect(
      signedIn.getByRole("heading", { name: "How deals are found" }),
    ).toBeVisible();

    const every = signedIn.getByLabel("Look again every");
    await expect(every).toHaveValue("8");
    await every.selectOption("12");
    await signedIn.reload();
    await expect(signedIn.getByLabel("Look again every")).toHaveValue("12");
    await signedIn.getByLabel("Look again every").selectOption("8");
  });

  test("and can run a pass without waiting for the schedule", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Look again now" }).click();
    // The panel reports what the pass did, so a run that found nothing is
    // distinguishable from a button that did nothing.
    await expect(signedIn.getByText(/comparable listings/)).toBeVisible();
    // Not a fixed number. A pass re-reads the whole catalog, and this suite
    // shares one database with specs that edit models and calibers -- which
    // is what a deal's peer group is built from, so a pass run after them
    // legitimately finds a different set than the seed did. Pinning the
    // seeded count only held while nothing had re-run a pass, and it broke
    // the moment anything did. What the button has to do is come back with
    // deals rather than an empty list.
    await expect(signedIn.locator(".deal").first()).toBeVisible();
  });

  test("a threshold the server refuses is put back rather than left on screen", async ({
    signedIn,
  }) => {
    const floor = signedIn.getByLabel("and be at least");
    await floor.fill("3");
    await floor.blur();
    // 3 is below the allowed floor, so the server says no and the page shows
    // the truth again instead of a value that was never saved.
    await expect(signedIn.locator(".alert--error")).toBeVisible();
    await expect(floor).toHaveValue("20");
  });
});
