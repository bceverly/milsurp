/**
 * The armory page.
 *
 * The behavior worth pinning down here is the approval gate: everything
 * arrives awaiting approval, promoting is what moves it into production, and
 * nothing in between is silent about which state a row is in.
 */
import { test, expect } from "./fixtures.js";

test.describe("armory", () => {
  test.beforeEach(async ({ signedIn }) => {
    // Exact: a listing card reading "US M1 Garand, Springfield Armory" is
    // also a link whose name contains "Armory".
    await signedIn.getByRole("link", { name: "Armory", exact: true }).click();
    await expect(signedIn.getByRole("heading", { name: "Armory" })).toBeVisible();
  });

  test("loads the shipped armory, all of it awaiting approval", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // The success line specifically. A standing banner counts what is
    // awaiting approval and appears only once there is something to count, so
    // a bare ".alert" matches one element or two depending on the timing.
    await expect(signedIn.locator(".alert--success")).toContainText(
      /awaiting approval|already has/,
    );

    const rows = signedIn.locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    // The default view is the pending queue, so every chip in it says so.
    const chips = signedIn.locator("tbody .chip");
    await expect(chips.first()).toHaveText("Awaiting approval");
  });

  test("a maker can be deleted, not only merged away", async ({ signedIn }) => {
    /**
     * The Manufacturers tab had no delete at all while Models and Calibers
     * have had one throughout, so a maker a scan proposed and got wrong could
     * only be merged into something or left in the queue. Merging is the wrong
     * tool for that: it moves the junk spelling onto the target as a live
     * matching rule, and the worst of them — "PD Trade" — is in 228 titles.
     *
     * Placed early in this file on purpose: a later test promotes every maker
     * to production, and the list shows the pending queue by default.
     */
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();

    const deletes = signedIn.getByRole("button", { name: /^Delete / });
    await expect(deletes.first()).toBeVisible();
    const before = await deletes.count();

    await deletes.first().click();

    // Confirmed rather than done: for a row a scan proposed, deleting is not
    // what it looks like — the name comes back the next time a title carries
    // it, because a surviving row is what suppresses re-proposal.
    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: /^Delete/ }).click();

    await expect(signedIn.locator(".alert--success")).toContainText("Deleted");
    await expect(deletes).toHaveCount(before - 1);
  });

  test("the models tab has a trashcan and it confirms", async ({ signedIn }) => {
    /** The shared models/calibers table has had a delete since it existed; what
     *  changed is that it asks first. Pinned per tab because the actions cell
     *  is one block of JSX shared by two tabs with different columns. */
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();

    for (const tab of ["Models", "Calibers"]) {
      await signedIn.getByRole("tab", { name: tab }).click();
      const trash = signedIn.getByRole("button", { name: /^Delete / }).first();
      await expect(trash).toBeVisible();
      await trash.click();

      const dialog = signedIn.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expect(dialog).toContainText(/Delete/);
      // Nothing is deleted by opening it.
      await signedIn.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
    }
  });

  test("deleting a scan-proposed row offers to disable it instead", async ({
    signedIn,
  }) => {
    /**
     * The trashcan looked decisive and quietly meant "ask me again next week".
     * Every propose_* in services/armory.py looks a name up regardless of
     * status or enabled, so any surviving row stops the name being proposed
     * and a deleted one comes back. The row is the tombstone.
     */
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();

    // A caliber the shipped file carries, so it has no first_seen_in and
    // deleting it really does get rid of it.
    const plain = signedIn.getByRole("button", { name: /^Delete / }).first();
    await plain.click();
    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toContainText("should stay gone");
    await expect(dialog.getByRole("button", { name: "Disable instead" })).toHaveCount(0);
    await signedIn.keyboard.press("Escape");

    // And the switch itself, which is what "disable instead" would set.
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await signedIn.locator("tbody tr td").nth(1).locator("button").first().click();
    await expect(signedIn.getByLabel("Enabled")).toBeVisible();
  });

  test("the tab is in the URL and Back walks between tabs", async ({ signedIn }) => {
    /**
     * Reported from the running site: Back from the armory jumped to a
     * different page than the one you came from, and which page depended on
     * how you had arrived. The tab was component state, so the browser had no
     * idea any of it had happened — every tab click was invisible to history.
     */
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await expect(signedIn).toHaveURL(/#manufacturer$/);
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await expect(signedIn).toHaveURL(/#caliber$/);

    // Back goes to the tab before it, not off the page.
    await signedIn.goBack();
    await expect(signedIn).toHaveURL(/#manufacturer$/);
    await expect(signedIn.getByRole("tab", { name: "Manufacturers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await signedIn.goForward();
    await expect(signedIn.getByRole("tab", { name: "Calibers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("Showing is in the URL too, and survives Back", async ({ signedIn }) => {
    /**
     * The other half of "what is this page showing". Both parts are stored in
     * different places — the tab in the fragment, this in the query — so the
     * thing most likely to break is one wiping the other.
     */
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await signedIn.getByLabel("Showing").selectOption("approved");
    await expect(signedIn).toHaveURL(/\?status=approved#caliber$/);

    // Changing the filter must not throw the tab away...
    await expect(signedIn.getByRole("tab", { name: "Calibers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // ...and changing the tab must not throw the filter away.
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await expect(signedIn).toHaveURL(/\?status=approved#manufacturer$/);
    await expect(signedIn.getByLabel("Showing")).toHaveValue("approved");

    // Back undoes the tab, leaving the filter where it was.
    await signedIn.goBack();
    await expect(signedIn).toHaveURL(/\?status=approved#caliber$/);
    // ...and again undoes the filter.
    await signedIn.goBack();
    await expect(signedIn.getByLabel("Showing")).toHaveValue("pending");
  });

  test("the default filter is left out of the URL", async ({ signedIn }) => {
    /** A page with no query string is the pending queue, which is what
     *  somebody opening the armory has come to work through. */
    await signedIn.goto("/armory#model");
    await expect(signedIn.getByLabel("Showing")).toHaveValue("pending");
    await signedIn.getByLabel("Showing").selectOption("approved");
    await signedIn.getByLabel("Showing").selectOption("pending");
    await expect(signedIn).toHaveURL(/\/armory#model$/);
  });

  test("a tab can be linked to directly", async ({ signedIn }) => {
    await signedIn.goto("/armory#caliber");
    await expect(signedIn.getByRole("tab", { name: "Calibers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // Read either way, so an older or hand-typed plural link still lands.
    await signedIn.goto("/armory#manufacturers");
    await expect(signedIn.getByRole("tab", { name: "Manufacturers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // And anything else falls back rather than showing an empty page.
    await signedIn.goto("/armory#nonsense");
    await expect(signedIn.getByRole("tab", { name: "Models" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("an alias can be made the primary name", async ({ signedIn }) => {
    /**
     * "IWI" and "Israel Weapon Industries" are one firm, and which of them is
     * the *name* decides what gets written onto every listing the row matches.
     * By hand that is two edits which have to happen together — rename the row,
     * then swap the alias — and between them the row either claims a spelling
     * twice or has stopped recognizing one.
     */
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();

    // A row with at least one alias: the control is not offered without one,
    // because there would be nothing to choose between.
    const row = signedIn.locator("tbody tr", { hasText: ".32 ACP" }).first();
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: ".32 ACP", exact: true }).click();

    await expect(signedIn.locator(".armory-primary-swap")).toContainText(".32 ACP");
    await signedIn.getByRole("button", { name: "Change…" }).click();

    const picker = signedIn.getByLabel("Primary name");
    await expect(picker).toBeVisible();
    // The current name is in the list too, marked, so the dialog can be opened
    // and closed without being a trap.
    await expect(picker.locator("option", { hasText: "current" })).toHaveCount(1);

    const alias = (await picker.locator("option").nth(1).getAttribute("value")) || "";
    await picker.selectOption(alias);
    await signedIn.getByRole("button", { name: "Make it the primary" }).click();

    await expect(signedIn.locator(".alert--success")).toContainText("primary name");
    // The old name is still there as a spelling, which is the half that keeps
    // the row matching what it used to.
    const moved = signedIn.locator("tbody tr", { hasText: alias }).first();
    await expect(moved).toContainText(".32 ACP");

    // Put it back. This file shares one database across its tests, and a later
    // one searches for "7.65mm Browning" expecting to find the row still
    // called ".32 ACP".
    await moved.getByRole("button", { name: alias, exact: true }).click();
    await signedIn.getByRole("button", { name: "Change…" }).click();
    await signedIn.getByLabel("Primary name").selectOption(".32 ACP");
    await signedIn.getByRole("button", { name: "Make it the primary" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText("primary name");

    // Reported from the running site: the page could not be scrolled again
    // afterwards. Two dialogs are open at that moment — the edit dialog and
    // this one on top of it — and each was restoring its *own* idea of what
    // the page scrolled like before, so the second put back the "hidden" the
    // first had set. See the counter in components/Modal.jsx.
    await expect
      .poll(() => signedIn.evaluate(() => document.body.style.overflow))
      .not.toBe("hidden");
  });

  test("promoting a row moves it to production and it stops being pending", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // A named row rather than whichever happens to sort first: the name cell
    // also carries a reference link and a chip, so a name read back out of it
    // is not the string it went in as.
    await signedIn.getByLabel("Search").fill("Karabiner 98k");
    const name = "Karabiner 98k";
    const target = signedIn.locator("tbody tr", { hasText: name });
    await expect(target).toHaveCount(1);
    await expect(target.locator(".chip")).toHaveText("Awaiting approval");
    await target.locator('input[type="checkbox"]').check();
    await signedIn.getByRole("button", { name: "Promote to production" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText(
      "moved into production",
    );

    // Gone from the pending queue…
    await expect(signedIn.locator("tbody tr", { hasText: name })).toHaveCount(0);
    // …and present in production, marked as such.
    await signedIn.getByLabel("Showing").selectOption("approved");
    const row = signedIn.locator("tbody tr", { hasText: name });
    await expect(row).toHaveCount(1);
    await expect(row.locator(".chip")).toHaveText("Production");
  });

  test("a model is one row carrying several makers", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await signedIn.getByLabel("Search").fill("M1 Garand");
    const rows = signedIn.locator("tbody tr", { hasText: "M1 Garand" });
    await expect(rows).toHaveCount(1);
    // Springfield and Winchester both built it, on the one row.
    await expect(rows.first()).toContainText("Springfield");
  });

  test("calibers are a separate tab and carry their other spellings", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await signedIn.getByLabel("Search").fill("7.65mm Browning");
    // Searching by an alias finds the row it belongs to, which is the point.
    await expect(signedIn.locator("tbody tr", { hasText: ".32 ACP" })).toHaveCount(1);
  });

  test("select all approves the whole pending queue in two clicks", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // Wait for real data rather than the first row: while it is fetching, the
    // only row in the table is "Loading…", which is also a visible row.
    await expect(signedIn.locator("tbody tr", { hasText: "M1 Garand" })).toHaveCount(1);
    const pending = await signedIn.locator("tbody tr").count();
    expect(pending).toBeGreaterThan(1);

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await expect(signedIn.locator(".armory-bulk")).toContainText("everything listed");

    await signedIn.getByRole("button", { name: "Promote to production" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();

    // The pending queue is the default view, and it is now empty.
    await expect(signedIn.locator("tbody")).toContainText("Nothing here");
    // And what was in it is in production. Counted by name rather than by
    // total, because earlier tests in this file promote a row of their own.
    await signedIn.getByLabel("Showing").selectOption("approved");
    await expect(signedIn.locator("tbody tr", { hasText: "M1 Garand" })).toHaveCount(1);
  });

  test("select all again clears the selection", async ({ signedIn }) => {
    // "Everything" rather than the pending queue, so this does not depend on
    // what the test above left behind.
    await signedIn.getByLabel("Showing").selectOption("");
    await expect(signedIn.locator("tbody tr", { hasText: "M1 Garand" })).toHaveCount(1);

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await expect(signedIn.locator(".armory-bulk")).toBeVisible();
    await signedIn.getByRole("checkbox", { name: "Clear selection" }).uncheck();
    await expect(signedIn.locator(".armory-bulk")).toHaveCount(0);
  });

  test("manufacturers can be approved the same way", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // Wait for it to report before touching the tab. The click kicks off a
    // POST and a reload, and load() does not cancel an in-flight request, so
    // a filter change made during it can be overwritten by the older response.
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    // The makers that arrived with the shipped armory are awaiting approval
    // like everything else, and this tab selects them the same way.
    await expect(signedIn.locator("tbody tr", { hasText: "Rock-Ola" })).toHaveCount(1);

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await signedIn.getByRole("button", { name: "Promote to production" }).click();
    await expect(signedIn.locator(".alert--success")).toContainText("production");
  });

  test("an approved manufacturer does not read as awaiting approval", async ({
    signedIn,
  }) => {
    // Reported from the running site: every maker drew the "Awaiting approval"
    // chip and approving them changed nothing. The payload carried no status
    // at all, so the page fell through to the chip it shows for one it does
    // not recognize -- while the database said they were all approved.
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // Wait for it to report before touching the tab. The click kicks off a
    // POST and a reload, and load() does not cancel an in-flight request, so
    // a filter change made during it can be overwritten by the older response.
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await signedIn.getByLabel("Showing").selectOption("approved");

    // Mauser's own row, not "the first chip in the table". The tests in this
    // file share one database and the one above promotes every pending maker,
    // so anything asserted about the table as a whole depends on what ran
    // before it. Mauser is the fixed point: seeded from the built-in maker
    // list in production, and nothing here sends it back.
    //
    // Waiting on the row rather than on "tbody tr" matters for a second
    // reason: that selector also matches the one-cell loading row, so it is
    // visible before any data has arrived.
    const mauser = signedIn.locator("tbody tr", { hasText: "Mauser" }).first();
    await expect(mauser).toBeVisible();
    await expect(mauser.locator(".chip--success")).toHaveText("Production");
    await expect(mauser.locator(".chip--warning")).toHaveCount(0);
  });

  test("the manufacturers tab honors the status filter", async ({ signedIn }) => {
    // It took no status parameter, so it returned every maker whatever the
    // page was set to -- which is what made the whole list look pending.
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // Wait for it to report before touching the tab. The click kicks off a
    // POST and a reload, and load() does not cancel an in-flight request, so
    // a filter change made during it can be overwritten by the older response.
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();

    // One maker, both ways round. Counts do not auto-wait, so comparing two of
    // them across a re-fetch compares whatever happened to be rendered -- and
    // naming a second, pending maker would depend on which tests ran first,
    // since they share a database and one of them promotes the whole queue.
    const mauser = signedIn.locator("tbody tr", { hasText: "Mauser" });

    await signedIn.getByLabel("Showing").selectOption("approved");
    await expect(mauser.first()).toBeVisible();

    await signedIn.getByLabel("Showing").selectOption("pending");
    await expect(mauser).toHaveCount(0);
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    // Wait for it to report before touching the tab. The click kicks off a
    // POST and a reload, and load() does not cancel an in-flight request, so
    // a filter change made during it can be overwritten by the older response.
    await expect(signedIn.locator(".alert--success")).toBeVisible();
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();

    const firstName = signedIn.locator("tbody tr td:nth-child(2) button").first();
    await expect(firstName).toBeVisible();
    const ascending = await firstName.innerText();

    await signedIn
      .locator("thead")
      .getByRole("button", { name: "Name", exact: true })
      .click();
    await expect(signedIn.locator('th[aria-sort="descending"]')).toHaveCount(1);
    expect(await firstName.innerText()).not.toBe(ascending);

    await signedIn
      .locator("thead")
      .getByRole("button", { name: "Name", exact: true })
      .click();
    expect(await firstName.innerText()).toBe(ascending);
  });

  test("calibers sort by bore, not by the digits in their names", async ({
    signedIn,
  }) => {
    // The general collator reads ".303" and ".45" as 303 and 45, so it put
    // .303 British after .45 ACP. As bore diameters they are 0.303" and 0.45"
    // and the .303 belongs between .30-06 and .308.
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await signedIn.getByLabel("Showing").selectOption("");

    // Polled for the names themselves rather than waiting on some proxy for
    // "the reload has finished". Waiting for the loading row to be *absent*
    // races the reload starting — it is absent before it begins too — and
    // waiting for one row to be visible is no better, because `hasText`
    // matches anywhere in a row and a caliber name appears on the Models tab
    // in a Chambered-in cell. Polling the actual assertion has neither hole.
    const probes = [
      ".30-06 Springfield",
      ".303 British",
      ".32 ACP",
      ".45 ACP",
      "7.62x54R",
      "12 gauge",
    ];
    const readNames = () =>
      signedIn.locator("tbody tr td:nth-child(2) button").allInnerTexts();
    await expect
      .poll(async () => {
        const found = await readNames();
        return probes.every((probe) => found.includes(probe));
      })
      .toBe(true);

    const names = await readNames();
    const at = (name) => names.indexOf(name);
    expect(at(".30-06 Springfield")).toBeLessThan(at(".303 British"));
    expect(at(".303 British")).toBeLessThan(at(".32 ACP"));
    expect(at(".32 ACP")).toBeLessThan(at(".45 ACP"));
    // Metric after the inch bores, gauges last: different units, kept apart.
    expect(at(".45 ACP")).toBeLessThan(at("7.62x54R"));
    expect(at("7.62x54R")).toBeLessThan(at("12 gauge"));
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await signedIn.getByLabel("Showing").selectOption("");
    await signedIn.getByLabel("Search").fill("Mauser");

    const row = signedIn
      .locator("tbody tr")
      .filter({ has: signedIn.getByRole("button", { name: "Merge…" }) })
      .first();
    await expect(row).toBeVisible();
    await expect(signedIn.locator("tbody tr", { hasText: "Colt" })).toHaveCount(0);

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

    const row = signedIn.locator("tbody tr", { hasText: unique });
    await expect(row).toContainText("Sweden");
  });

  test("models show how many listings they account for", async ({ signedIn }) => {
    /** The makers tab has had this since it existed, and models was the one
     *  place it was missing — which made "is this row worth filling in?" the
     *  question the page could not answer. */
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Models" }).click();

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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();

    const row = signedIn.locator("tbody tr").first();
    const view = row.getByRole("link", { name: /^View listings for/ });
    await expect(view).toBeVisible();

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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await signedIn.getByRole("tab", { name: "Models" }).click();

    const view = signedIn
      .locator("tbody tr")
      .first()
      .getByRole("link", { name: /^View listings for/ });
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

test.describe("armory access", () => {
  // Outside the describe above, which signs in before every test — that is
  // what this one must not have done.
  test("is not reachable without signing in", async ({ page }) => {
    await page.goto("/armory");
    await expect(page.locator('input[name="username"]')).toBeVisible();
  });
});
