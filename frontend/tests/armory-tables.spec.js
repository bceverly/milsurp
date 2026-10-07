/**
 * The armory page's tables: makers and the models they built, sorting,
 * search, adding and editing rows, and the links to the listings each row
 * accounts for. The approval queue is in armory.spec.js.
 */
import { test, expect, openPage } from "./fixtures.js";
import { allRowNames, loadShipped, searchFor } from "./armory-helpers.js";

test.describe("armory tables", () => {
  test.beforeEach(async ({ signedIn }) => {
    await openPage(signedIn, "Armory");
  });

  test("manufacturers are a tab here, not a page of their own", async ({ signedIn }) => {
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    // Mauser is seeded from the built-in maker list and arrives in production,
    // so the default "Awaiting approval" view does not list it. The tab honors
    // that filter like the other two -- which it did not, and every maker read
    // as pending because of it.
    await signedIn.getByLabel("Showing").selectOption("approved");
    await expect(
      signedIn.locator("tbody tr", { hasText: "Mauser" }).first(),
    ).toBeVisible();
    // No flat models textbox on a maker any more: the models are rows.
    await signedIn.getByRole("button", { name: "Mauser", exact: true }).first().click();
    await expect(signedIn.getByLabel("Also written as")).toBeVisible();
    await expect(signedIn.getByLabel("Models")).toHaveCount(0);
  });

  test("a maker expands to the models the armory says it built", async ({ signedIn }) => {
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    // Mauser is in production, so it is not in the default pending view.
    await signedIn.getByLabel("Showing").selectOption("approved");

    const expand = signedIn.getByRole("button", { name: "Expand Mauser" });
    await expect(expand).toBeVisible();
    await expand.click();
    const drilldown = signedIn.locator(".armory-drilldown");
    await expect(drilldown).toBeVisible();
    // Mauser built the K98k, and "+ Add model" is offered right there.
    await expect(drilldown).toContainText("Karabiner 98k");
    await expect(drilldown.getByRole("button", { name: "Add model" })).toBeVisible();
  });

  for (const tab of ["Manufacturers", "Models", "Calibers"]) {
    test(`the ${tab} table fits its container without scrolling sideways`, async ({
      signedIn,
    }) => {
      /**
       * No horizontal scrollbar, at any width worth supporting.
       *
       * The models table used to overflow by about forty pixels, and only when
       * the data happened to be long -- so the sideways scroll appeared and
       * disappeared with the rows. Worse, a browser with overlay scrollbars
       * draws nothing until you are already scrolling, so what was over the
       * edge did not look like it was there at all: the eye and the trashcan
       * were reported as simply missing.
       *
       * Fixed by letting the table shrink rather than by pinning what fell off
       * it -- headers and cells wrap, the widest column ("Also written as")
       * moved under the name it belongs to, and the controls give up padding
       * before the data gives up room. Checked at 1024 because that is where
       * it broke first, and asserted on header-to-cell count too, since a
       * column removed from one of the two tables and not the other is the
       * easy way to get this wrong.
       */
      await signedIn.setViewportSize({ width: 1024, height: 900 });
      await loadShipped(signedIn);
      await signedIn.getByRole("tab", { name: tab }).click();
      // "Everything", not the default pending queue: an earlier test in this
      // file approves the whole queue, so by the time this runs the default
      // view can be empty — and an empty table renders "Nothing here" in a
      // `.loading-row`, the same class the spinner uses. Waiting for that to
      // reach zero therefore waits forever, which is how this failed in the
      // suite while passing on its own.
      await signedIn.getByLabel("Showing").selectOption("");
      // Polled, not measured once. Changing the filter starts a fetch, so a
      // wait that passes on the rows already on screen can be followed by a
      // reload that replaces them with a placeholder before the measurement
      // runs -- which read one cell where there should be nine. Retrying until
      // a real row is on screen is the only honest way to measure a table that
      // reloads underneath you.
      //
      // ":has(.table__actions)" picks a data row rather than a placeholder,
      // and the backreference asserts every header has exactly one cell: a
      // column removed from one of the two tables and not the other is the
      // easy way to get this wrong, and it silently misaligns the other.
      await expect
        .poll(() =>
          signedIn.evaluate(() => {
            const wrap = document.querySelector("table")?.parentElement;
            const row = document.querySelector("tbody tr:has(.table__actions)");
            if (!wrap || !row) return "no data row on screen yet";
            const headers = document.querySelectorAll("thead th").length;
            const overflow = wrap.scrollWidth - wrap.clientWidth;
            return `overflow=${overflow} cells=${row.children.length} headers=${headers}`;
          }),
        )
        .toMatch(/^overflow=0 cells=(\d+) headers=\1$/);
    });
  }

  test("the row controls stay on screen when the table is too wide", async ({
    signedIn,
  }) => {
    /**
     * The models table is ten columns and overflows its scroll container. The
     * actions cell is justify-content: flex-end, so what went over the right
     * edge was the two icon-only buttons -- the eye and the trashcan -- while
     * "Merge…" stayed put. On a browser with overlay scrollbars nothing says
     * the table scrolls at all, so the feature was simply missing as far as
     * anyone could tell: "there is absolutely no eye or trash, just merge".
     *
     * Measured rather than eyeballed, because "is it in the DOM" and "can a
     * person reach it" had different answers: the link reported visible with
     * its right edge at 1451 on a 1440-wide window.
     */
    await signedIn.setViewportSize({ width: 1024, height: 900 });
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Models" }).click();
    // See the note above about .loading-row doubling as the empty state.
    await signedIn.getByLabel("Showing").selectOption("");
    // A row with the controls on it, not "the first row": a "Merge…" left
    // over from the table before the filter changed satisfied that, and the
    // first row was then the spinner of the refetch, with nothing to measure.
    const row = signedIn
      .locator("tbody tr")
      .filter({ has: signedIn.getByRole("link", { name: /^View listings for/ }) })
      .first();
    await expect(row).toBeVisible();
    await expect(signedIn.locator("tbody .loading-row .spinner")).toHaveCount(0);
    for (const control of [
      row.getByRole("link", { name: /^View listings for/ }),
      row.getByRole("button", { name: /^Delete / }),
    ]) {
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box.x + box.width).toBeLessThanOrEqual(1024);
      expect(box.x).toBeGreaterThanOrEqual(0);
    }
  });

  test("a model under an expanded maker has its own eyeball", async ({ signedIn }) => {
    /**
     * The question this tab cannot answer on its own: deciding whether a maker
     * really built a model means looking at what the model is holding, and
     * from here the only route there was to open the row, read its name,
     * switch to the models tab and find it again.
     */
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await signedIn.getByLabel("Showing").selectOption("approved");
    await searchFor(signedIn, "Mauser");
    await signedIn.getByRole("button", { name: "Expand Mauser" }).click();

    const drilldown = signedIn.locator(".armory-drilldown");
    await expect(drilldown).toBeVisible();
    const view = drilldown.getByRole("link", { name: /^View listings for/ }).first();
    await expect(view).toBeVisible();

    // The same link the models tab builds (see listingsHref): by model id once
    // a model is approved, so a rename cannot strand it, and by the quoted
    // name while it waits, since nothing is linked to it yet. Which one the
    // first row is depends on what other tests in the file have approved.
    const href = await view.getAttribute("href");
    expect(href).toMatch(/[?&](model=\d+|search=%22)/);
    expect(href).toContain("availability=all");

    await view.click();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });

  test("+ Add model from a maker pre-checks that maker", async ({ signedIn }) => {
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await signedIn.getByLabel("Showing").selectOption("approved");
    const expand = signedIn.getByRole("button", { name: "Expand Mauser" });
    await expect(expand).toBeVisible();
    await expand.click();
    await signedIn
      .locator(".armory-drilldown")
      .getByRole("button", { name: "Add model" })
      .click();

    // Scoped to the makers list: "8mm Mauser" and "7x57mm Mauser" are
    // cartridges in the field above, and they contain the word too.
    const makers = signedIn.locator(".armory-checkboxes").last();
    const mauser = makers.locator("label.checkbox", { hasText: /^Mauser$/ });
    await expect(mauser.locator('input[type="checkbox"]')).toBeChecked();
  });

  test("the maker list is alphabetical, whatever order the API sends", async ({
    signedIn,
  }) => {
    // The API orders makers by `position` -- the order their matching rules are
    // tried in, which is right for the API and no way to read fifty firms.
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await signedIn.getByLabel("Showing").selectOption("approved");
    await expect(
      signedIn.locator("tbody tr", { hasText: "Mauser" }).first(),
    ).toBeVisible();

    const names = await signedIn
      .locator("tbody tr td:nth-child(3) button")
      .allInnerTexts();
    expect(names.length).toBeGreaterThan(2);
    const alphabetical = [...names].sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }),
    );
    expect(names).toEqual(alphabetical);
  });

  test("a column header sorts by it, and again reverses it", async ({ signedIn }) => {
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    // The Calibers rows, not the Models rows still up while they load: only
    // a caliber row's eye filters by caliber.
    await expect(
      signedIn
        .locator("tbody tr")
        .first()
        .getByRole("link", { name: /^View listings for/ }),
    ).toHaveAttribute("href", /caliber=/);

    const firstName = signedIn.locator("tbody tr td:nth-child(2) button").first();
    await expect(firstName).toBeVisible();
    const ascending = await firstName.innerText();

    await signedIn
      .locator("thead")
      .getByRole("button", { name: "Name", exact: true })
      .click();
    await expect(signedIn.locator('th[aria-sort="descending"]')).toHaveCount(1);
    await expect(firstName).not.toHaveText(ascending);

    await signedIn
      .locator("thead")
      .getByRole("button", { name: "Name", exact: true })
      .click();
    // toHaveText, not innerText(). A click resolves when the event is
    // dispatched, not when React has re-rendered, so a one-shot read here
    // races the render and sees the *previous* order -- which is why this
    // test has twice reported "410 Gauge" where ".17 HMR" was expected. The
    // first click happens to be safe only because the aria-sort assertion
    // above it retries; this one had nothing to wait on.
    await expect(firstName).toHaveText(ascending);
  });

  test("the whole view survives a round trip through the listings", async ({
    signedIn,
  }) => {
    /**
     * The eye navigates in the current tab -- see listingsHref, where the
     * original reason (a per-tab bearer token) is recorded as having gone
     * away with the move to a cookie. So Back has to bring the page back
     * exactly as it was, which means the tab, the Showing filter, the sort
     * and the search all have to be in the URL.
     * Before this the sort and the search were React state and Back dropped
     * both, landing you on the Models tab sorted by name with an empty box.
     */
    await loadShipped(signedIn);

    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    // "Everything" is spelled ?status= -- present but empty, which is a real
    // answer and not the same as not having been asked.
    await signedIn.getByRole("combobox", { name: /Showing/i }).selectOption("");
    await signedIn
      .locator("thead")
      .getByRole("button", { name: "Name", exact: true })
      .click();
    await expect(signedIn.locator('th[aria-sort="descending"]')).toHaveCount(1);

    // The needle comes out of the table rather than being invented, so the
    // test does not depend on what the shipped armory happens to contain.
    const firstName = await signedIn
      .locator("tbody tr td:nth-child(2) button")
      .first()
      .innerText();
    const needle = firstName.slice(0, 3);
    await signedIn.getByRole("searchbox").fill(needle);
    // The search is applied a moment after typing stops, so wait for it to
    // reach the URL before reading it.
    await expect(signedIn).toHaveURL(new RegExp(`q=${encodeURIComponent(needle)}`));
    await expect(signedIn.locator("tbody tr").first()).toBeVisible();

    const before = signedIn.url();
    expect(before).toContain("sort=-name");
    expect(before).toContain(`q=${encodeURIComponent(needle)}`);
    expect(before).toContain("status=");

    // Out to the listings and straight back.
    const view = signedIn
      .locator("tbody tr")
      .first()
      .getByRole("link", { name: /^View listings for/ });
    await view.click();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
    await signedIn.goBack();

    await expect(signedIn.getByRole("tab", { name: "Calibers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(signedIn.getByRole("searchbox")).toHaveValue(needle);
    await expect(signedIn.locator('th[aria-sort="descending"]')).toHaveCount(1);
    await expect(signedIn.getByRole("combobox", { name: /Showing/i })).toHaveValue("");
    expect(signedIn.url()).toBe(before);
  });

  test("typing in the search box does not fill the history", async ({ signedIn }) => {
    /**
     * The search replaces rather than pushes. A history entry per keystroke
     * would make Back walk the word backwards a letter at a time instead of
     * leaving the page you came from.
     */
    await signedIn.getByRole("searchbox").fill("mauser");
    await expect(signedIn.getByRole("searchbox")).toHaveValue("mauser");
    await expect(signedIn).toHaveURL(/q=mauser/);

    // Six keystrokes, zero history entries: one Back leaves the armory
    // altogether rather than spelling "mause", "maus", "mau"...
    await signedIn.goBack();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });

  test("typing a search asks the server once, not once per letter", async ({
    signedIn,
  }) => {
    /**
     * Each keystroke used to reload the whole page: nine requests, six of
     * them lists the search does not even filter. Typing "Mauser" sent over
     * fifty in a couple of seconds, and production's proxy answered the rest
     * with 429. Now the search waits for the typing to stop and reloads only
     * the three lists it filters.
     */
    await signedIn.goto("/armory");
    await expect(signedIn.getByRole("searchbox")).toBeVisible();
    await signedIn.waitForLoadState("networkidle");

    const asked = [];
    signedIn.on("request", (request) => {
      if (request.url().includes("/api/")) asked.push(request.url());
    });
    await signedIn.getByRole("searchbox").pressSequentially("mauser", { delay: 40 });
    await expect(signedIn).toHaveURL(/q=mauser/);
    await signedIn.waitForLoadState("networkidle");

    expect(asked.length).toBeLessThanOrEqual(3);
    expect(asked.every((url) => url.includes("search=mauser"))).toBe(true);
  });

  test("calibers sort by bore, not by the digits in their names", async ({
    signedIn,
  }) => {
    // The general collator reads ".303" and ".45" as 303 and 45, so it put
    // .303 British after .45 ACP. As bore diameters they are 0.303" and 0.45"
    // and the .303 belongs between .30-06 and .308.
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await signedIn.getByLabel("Showing").selectOption("");

    // Polled for the names themselves rather than waiting on some proxy for
    // "the reload has finished". Waiting for the loading row to be *absent*
    // races the reload starting — it is absent before it begins too — and
    // waiting for one row to be visible is no better, because `hasText`
    // matches anywhere in a row and a caliber name appears on the Models tab
    // in a Chambered-in cell. Polling the actual assertion has neither hole.
    // **Every probe is a name the shipped armory defines**, not a spelling of
    // one. `7.62x54R` used to be in this list and is an *alias* here -- the
    // shipped row is named `7.62x54Rmm` -- so the only way a row read
    // `7.62x54R` was for a scan to have proposed it under that spelling
    // first. That made this test pass in a full run, where admin.spec.js
    // scans the demo vendor before the armory spec gets here, and fail
    // whenever armory.spec.js was run on its own. A test that needs another
    // spec to have gone first is a test that will eventually be run second.
    const probes = [
      ".30-06 Springfield",
      ".303 British",
      ".32 ACP",
      ".45 ACP",
      "7.62x54Rmm",
      "12 gauge",
    ];
    // The table is paged now, so the order is read across every page: first
    // the first page is waited for -- two reloads are in flight here, the tab
    // click's and the filter's -- and then the pager is walked to the end.
    await expect
      .poll(() => signedIn.locator("tbody tr td:nth-child(2) button").allInnerTexts())
      .toContain(".30-06 Springfield");
    const names = await allRowNames(signedIn);
    for (const probe of probes) expect(names).toContain(probe);

    const at = (name) => names.indexOf(name);
    expect(at(".30-06 Springfield")).toBeLessThan(at(".303 British"));
    expect(at(".303 British")).toBeLessThan(at(".32 ACP"));
    expect(at(".32 ACP")).toBeLessThan(at(".45 ACP"));
    // Metric after the inch bores, gauges last: different units, kept apart.
    expect(at(".45 ACP")).toBeLessThan(at("7.62x54Rmm"));
    expect(at("7.62x54Rmm")).toBeLessThan(at("12 gauge"));
  });

  test("the merge dropdown offers rows the table is not showing", async ({
    signedIn,
  }) => {
    // A merge folds one row into another, and the other is usually not in the
    // view you are looking at -- a freshly discovered "Mosin" into the approved
    // "Mosin-Nagant". The dialog was being handed the filtered rows, which made
    // exactly that impossible.
    //
    // Narrowed with the search box rather than the status filter: the tests in
    // this file share a database and one of them promotes the whole pending
    // queue, so "some rows are pending" is true or not depending on what ran
    // first. A search for one name hides the rest either way.
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await signedIn.getByLabel("Showing").selectOption("");
    await signedIn.getByLabel("Search").fill("Mauser");
    // The search is applied a moment after typing stops, and until then the
    // unfiltered table is still up: a row picked from it can be replaced
    // under the click. Wait for the search to land and the table to narrow.
    await expect(signedIn).toHaveURL(/q=Mauser/);
    await expect(signedIn.locator("tbody tr", { hasText: "Colt" })).toHaveCount(0);
    await signedIn.waitForLoadState("networkidle");

    const row = signedIn
      .locator("tbody tr")
      .filter({ has: signedIn.getByRole("button", { name: "Merge…" }) })
      .first();
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "Merge…" }).click();
    const names = (
      await signedIn.getByLabel("Merge into").locator("option").allInnerTexts()
    ).slice(1);

    // Colt is filtered out of the table behind the dialog and still offered.
    expect(names).toContain("Colt");
    const alphabetical = [...names].sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }),
    );
    expect(names).toEqual(alphabetical);
  });

  test("a caliber can be added without leaving the model dialog", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("button", { name: "Add model" }).first().click();
    const unique = `9x99mm Test ${Date.now()}`;
    await signedIn.getByPlaceholder("A cartridge not listed above").fill(unique);
    await signedIn.getByRole("button", { name: "Add caliber" }).click();
    // It appears in the list, already ticked for this model.
    const added = signedIn.locator("label.checkbox", { hasText: unique });
    await expect(added.locator('input[type="checkbox"]')).toBeChecked();
  });

  test("adding a model by hand also arrives awaiting approval", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Add model" }).click();
    const unique = `Test Model ${Date.now()}`;
    await signedIn.getByLabel("Name").fill(unique);
    await signedIn.getByLabel("Kind").selectOption("carbine");
    await signedIn.getByRole("button", { name: "Add, awaiting approval" }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    await searchFor(signedIn, unique);

    const row = signedIn.locator("tbody tr", { hasText: unique });
    await expect(row).toHaveCount(1);
    await expect(row.locator(".chip")).toHaveText("Awaiting approval");
    await expect(row).toContainText("Carbine");
  });

  test("a model records the country its pattern comes from", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Add model" }).click();
    const unique = `Test Model ${Date.now()}`;
    await signedIn.getByLabel("Name").fill(unique);
    await signedIn.getByLabel("Country of origin").fill("Sweden");
    await signedIn.getByRole("button", { name: "Add, awaiting approval" }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    await searchFor(signedIn, unique);

    const row = signedIn.locator("tbody tr", { hasText: unique });
    await expect(row).toContainText("Sweden");
  });

  test("models show how many listings they account for", async ({ signedIn }) => {
    /** The makers tab has had this since it existed, and models was the one
     *  place it was missing — which made "is this row worth filling in?" the
     *  question the page could not answer. */
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Models" }).click();
    // Approved rows: a row awaiting approval links nothing and shows how many
    // listings *mention* it instead -- see the test near the top of the file.
    await signedIn.getByLabel("Showing").selectOption("approved");

    await expect(signedIn.getByRole("columnheader", { name: /Listings/ })).toBeVisible();
    const cells = signedIn.locator("tbody tr td").filter({ hasText: /^\d+$/ });
    await expect(cells.first()).toBeVisible();

    // ...and it sorts, like every other column here.
    await signedIn.getByRole("columnheader", { name: /Listings/ }).click();
    await expect(signedIn.locator("tbody tr").first()).toBeVisible();
  });

  test("each row links to the listings it accounts for", async ({ signedIn }) => {
    /**
     * The question the page cannot answer on its own. Deciding whether two
     * calibers should be merged means looking at what each one is actually
     * holding, and before this the only route there was retyping the name
     * into the inventory's search box.
     */
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Calibers" }).click();

    const row = signedIn.locator("tbody tr").first();
    const view = row.getByRole("link", { name: /^View listings for/ });
    // Waits for the Calibers table itself: a tab switch leaves the Models rows
    // up while the calibers load, and their eye links by model, not caliber.
    // Read straight after the click, a busy machine served the Models row.
    await expect(view).toHaveAttribute("href", /caliber=/);

    const href = await view.getAttribute("href");
    // The filter matches the stored string exactly, and everything rather
    // than what is in stock: a pending row usually arrived from a listing
    // that has since sold.
    expect(href).toContain("caliber=");
    expect(href).toContain("availability=all");

    // The name comes off the link's own label rather than out of the name
    // cell, which also carries a reference link and a status chip.
    const label = await view.getAttribute("aria-label");
    const caliber = label.replace("View listings for ", "");

    await view.click();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
    await expect(signedIn.locator(".active-filters__chip").first()).toContainText(
      caliber,
    );
  });

  test("a model links by id rather than by name", async ({ signedIn }) => {
    /**
     * Because that is what a listing stores. `Item.firearm_model_id` is a real
     * foreign key while caliber and manufacturer are the text a scan read off
     * the shop, so filtering a model by name would miss every listing matched
     * to it under a different spelling.
     */
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Models" }).click();
    // An approved row: one awaiting approval has no links to filter by, and
    // opens the listings that name it instead.
    await signedIn.getByLabel("Showing").selectOption("approved");
    // The view reloads without clearing the old rows first, so wait for the
    // first row to be an approved one before reading its link.
    const first = signedIn.locator("tbody tr").first();
    await expect(first.locator(".chip--success")).toHaveText("Production");

    const view = first.getByRole("link", { name: /^View listings for/ });
    await expect(view).toBeVisible();
    expect(await view.getAttribute("href")).toMatch(/[?&]model=\d+/);
  });

  test("the country box suggests the spellings the classifier uses", async ({
    signedIn,
  }) => {
    // Held server-side for the same reason the kinds are: a model recorded as
    // "USSR" against listings read as "Russia" would split one country into
    // two filters, each showing half the rifles.
    await signedIn.getByRole("button", { name: "Add model" }).click();
    const options = signedIn.locator("#armory-countries option");
    await expect.poll(() => options.count()).toBeGreaterThan(0);
    const values = await options.evaluateAll((nodes) => nodes.map((n) => n.value));
    expect(values).toContain("Russia");
    expect(values).toContain("United States");
    expect(values).not.toContain("USSR");
  });
});
