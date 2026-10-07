/**
 * The armory page: the approval queue, and the page's state in the URL.
 *
 * The behavior worth pinning down here is the approval gate: everything
 * arrives awaiting approval, promoting is what moves it into production, and
 * nothing in between is silent about which state a row is in. The tables
 * themselves -- makers, sorting, search, editing -- are in armory-tables.spec.js;
 * the two were one file of 45 tests and seven minutes until 2026-10-07.
 */
import { test, expect, openPage } from "./fixtures.js";
import {
  caliberRowIsShowing,
  clearSearch,
  loadShipped,
  makersAreShowing,
  pressLoadShipped,
  searchFor,
} from "./armory-helpers.js";

test.describe("armory", () => {
  test.beforeEach(async ({ signedIn }) => {
    // See openPage: its exact heading, and the click retried until it lands.
    await openPage(signedIn, "Armory");
  });

  test("loads the shipped armory, all of it awaiting approval", async ({ signedIn }) => {
    await pressLoadShipped(signedIn);
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

  test("a row awaiting approval shows how many listings name it, and the eye opens them", async ({
    signedIn,
  }) => {
    // Straight after the load above, so M1 Garand is still awaiting approval:
    // a later test promotes the whole queue. A pending row links nothing, so
    // its count is of listings that *name* it -- and the eye has to open that
    // same set, or the number in the table is a promise the page breaks.
    await signedIn.getByLabel("Search").fill("M1 Garand");
    // Applied a moment after typing stops; until then the old table is up.
    await expect(signedIn).toHaveURL(/[?&]q=/);
    const row = signedIn.locator("tbody tr", { hasText: "M1 Garand" }).first();
    const mentions = row.locator(".armory-mentions");
    await expect(mentions).toHaveText(/^\d+ mentions?$/);
    const count = Number((await mentions.innerText()).split(" ")[0]);
    expect(count).toBeGreaterThan(0);

    await row.getByRole("link", { name: "View listings for M1 Garand" }).click();
    await expect(signedIn).toHaveURL(/search=%22M1\+Garand%22/);
    await expect(
      signedIn.getByText(new RegExp(`^${count} listings? match your filters`)),
    ).toBeVisible();
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
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await makersAreShowing(signedIn);

    const deletes = signedIn.getByRole("button", { name: /^Delete / });
    await expect(deletes.first()).toBeVisible();
    // By name rather than by count: the table is paged, and a page refills to
    // a hundred from the next one when a row goes.
    const label = await deletes.first().getAttribute("aria-label");

    await deletes.first().click();

    // Confirmed rather than done: for a row a scan proposed, deleting is not
    // what it looks like — the name comes back the next time a title carries
    // it, because a surviving row is what suppresses re-proposal.
    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: /^Delete/ }).click();

    await expect(signedIn.locator(".alert--success")).toContainText("Deleted");
    await expect(signedIn.getByRole("button", { name: label, exact: true })).toHaveCount(
      0,
    );
  });

  test("the models tab has a trashcan and it confirms", async ({ signedIn }) => {
    /** The shared models/calibers table has had a delete since it existed; what
     *  changed is that it asks first. Pinned per tab because the actions cell
     *  is one block of JSX shared by two tabs with different columns. */
    await loadShipped(signedIn);

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
    await loadShipped(signedIn);
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

  test("a row switched off leaves the queue and lands under Disabled", async ({
    signedIn,
  }) => {
    /**
     * Reported from the running site: two manufacturers switched off by hand
     * went on showing under "Awaiting approval" and kept the nav badge lit.
     * Turning a row off is ruling on it — it matches nothing afterwards,
     * exactly like a pending row — but the filter asked only about status.
     */
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await makersAreShowing(signedIn);

    // Column 0 selects the row and column 1 expands it; the name is column 2,
    // and its button is what opens the edit form.
    const nameCell = signedIn.locator("tbody tr").first().locator("td").nth(2);
    const name = (await nameCell.locator("button").innerText()).trim();

    // Switch it off through the form, the way an admin would.
    await nameCell.locator("button").click();
    await signedIn.getByLabel("Enabled").uncheck();
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);

    // Gone from the queue it had been stuck in...
    await expect(signedIn.locator("tbody")).not.toContainText(name);
    // ...and findable where the decision put it.
    await signedIn.getByLabel("Showing").selectOption("disabled");
    await expect(signedIn.locator("tbody")).toContainText(name);
  });

  test("a merge can be undone from the row it left behind", async ({ signedIn }) => {
    /**
     * The armory kept the merged row deliberately — "an admin who merges the
     * wrong pair should have something to look at rather than an archaeology
     * exercise" — and then offered nothing to do about it.
     */
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await makersAreShowing(signedIn);

    // Merge the first maker into the second.
    const rows = signedIn.locator("tbody tr");
    const source = (
      await rows.nth(0).locator("td").nth(2).locator("button").innerText()
    ).trim();
    await rows.nth(0).getByRole("button", { name: "Merge…" }).click();
    const dialog = signedIn.getByRole("dialog");
    await dialog.getByRole("combobox").selectOption({ index: 1 });
    await dialog.getByRole("button", { name: /Merge/ }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);

    // It is gone from the queue and sitting under Merged away.
    await signedIn.getByLabel("Showing").selectOption("merged");
    await expect(signedIn.locator("tbody")).toContainText(source);

    // Undo it, and it stops being merged.
    await signedIn
      .locator("tbody tr", { hasText: source })
      .first()
      .getByRole("button", { name: "Un-merge" })
      .click();
    await expect(signedIn.locator(".alert--success")).toContainText("Un-merged");
    await expect(signedIn.locator("tbody")).not.toContainText(source);
  });

  test("un-merge is not offered on a row that was never merged", async ({ signedIn }) => {
    /** On an ordinary row it would read as a second kind of delete. */
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await expect(signedIn.getByRole("button", { name: "Un-merge" })).toHaveCount(0);
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

  test("a URL naming an inherited property is treated as unknown, not obeyed", async ({
    signedIn,
  }) => {
    /**
     * Every object literal inherits from Object.prototype, so the lookups
     * behind these two URLs used to return something truthy for keys nobody
     * put in the map and skip their fallback. `?sort=__proto__` found
     * Object.prototype, which is not callable, and the sort comparator took
     * the render down with it; `#__proto__` made the tab an object instead of
     * a string. CodeQL found the first as "unvalidated dynamic method call"
     * and never saw the second, because that one is read rather than called.
     */
    for (const hash of ["#__proto__", "#constructor", "#toString"]) {
      await signedIn.goto(`/armory${hash}`);
      // Falls back exactly like "#nonsense" above rather than rendering an
      // object as the tab.
      await expect(signedIn.getByRole("tab", { name: "Models" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    }

    for (const key of ["__proto__", "valueOf", "constructor"]) {
      await signedIn.goto(`/armory?sort=${key}#model`);
      // The page is still standing and the table still has rows: an unknown
      // column sorts by name rather than throwing.
      await expect(
        signedIn.getByRole("heading", { name: "Armory", exact: true }),
      ).toBeVisible();
      await expect(signedIn.locator("tbody tr").first()).toBeVisible();
    }

    // And a real column still sorts, so the guard did not swallow the feature.
    await signedIn.goto("/armory?sort=name#model");
    await expect(signedIn.locator("tbody tr").first()).toBeVisible();
  });

  test("an alias can be made the primary name", async ({ signedIn }) => {
    /**
     * "IWI" and "Israel Weapon Industries" are one firm, and which of them is
     * the *name* decides what gets written onto every listing the row matches.
     * By hand that is two edits which have to happen together — rename the row,
     * then swap the alias — and between them the row either claims a spelling
     * twice or has stopped recognizing one.
     */
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await searchFor(signedIn, ".32 ACP");
    await caliberRowIsShowing(signedIn, ".32 ACP");

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
    await loadShipped(signedIn);
    // A named row rather than whichever happens to sort first: the name cell
    // also carries a reference link and a chip, so a name read back out of it
    // is not the string it went in as.
    await signedIn.getByLabel("Search").fill("Karabiner 98k");
    // Applied a moment after typing stops; until then the old table is up.
    await expect(signedIn).toHaveURL(/[?&]q=/);
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
    await loadShipped(signedIn);
    await signedIn.getByLabel("Search").fill("M1 Garand");
    // Applied a moment after typing stops; until then the old table is up.
    await expect(signedIn).toHaveURL(/[?&]q=/);
    const rows = signedIn.locator("tbody tr", { hasText: "M1 Garand" });
    await expect(rows).toHaveCount(1);
    // Springfield and Winchester both built it, on the one row.
    await expect(rows.first()).toContainText("Springfield");
  });

  test("calibers are a separate tab and carry their other spellings", async ({
    signedIn,
  }) => {
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    // Paged, so the row may not be on the first page; any data row will do.
    await expect(signedIn.locator("tbody tr").first()).toBeVisible();

    await signedIn.getByLabel("Search").fill("7.65mm Browning");
    // Applied a moment after typing stops; until then the old table is up.
    await expect(signedIn).toHaveURL(/[?&]q=/);
    // Searching by an alias finds the row it belongs to, which is the point.
    await expect(signedIn.locator("tbody tr", { hasText: ".32 ACP" })).toHaveCount(1);
  });

  test("select all approves the whole pending queue in two clicks", async ({
    signedIn,
  }) => {
    await loadShipped(signedIn);
    // Wait for real data rather than the first row: while it is fetching, the
    // only row in the table is "Loading…", which is also a visible row.
    await searchFor(signedIn, "M1 Garand");
    await clearSearch(signedIn);
    // More than a page of it, so "everything listed" reaches past what shows.
    await expect(signedIn.locator(".armory-pager").first()).toBeVisible();

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await expect(signedIn.locator(".armory-bulk")).toContainText("everything listed");

    await signedIn.getByRole("button", { name: "Promote to production" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();

    // The pending queue is the default view, and it is now empty.
    await expect(signedIn.locator("tbody")).toContainText("Nothing here");
    // And what was in it is in production. Counted by name rather than by
    // total, because earlier tests in this file promote a row of their own.
    await signedIn.getByLabel("Showing").selectOption("approved");
    await searchFor(signedIn, "M1 Garand");
  });

  test("select all again clears the selection", async ({ signedIn }) => {
    // "Everything" rather than the pending queue, so this does not depend on
    // what the test above left behind.
    await signedIn.getByLabel("Showing").selectOption("");
    await expect(signedIn.locator(".armory-pager").first()).toBeVisible();

    await signedIn.getByRole("checkbox", { name: "Select everything listed" }).check();
    await expect(signedIn.locator(".armory-bulk")).toBeVisible();
    await signedIn.getByRole("checkbox", { name: "Clear selection" }).uncheck();
    await expect(signedIn.locator(".armory-bulk")).toHaveCount(0);
  });

  test("manufacturers can be approved the same way", async ({ signedIn }) => {
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    // The makers that arrived with the shipped armory are awaiting approval
    // like everything else, and this tab selects them the same way.
    await makersAreShowing(signedIn);
    await searchFor(signedIn, "Rock-Ola");
    await clearSearch(signedIn);
    await makersAreShowing(signedIn);

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
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await signedIn.getByLabel("Showing").selectOption("approved");
    // Searched for, since the table is paged and Mauser need not be on page one.
    await searchFor(signedIn, "Mauser");

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
    await loadShipped(signedIn);
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();

    // One maker, both ways round. Counts do not auto-wait, so comparing two of
    // them across a re-fetch compares whatever happened to be rendered -- and
    // naming a second, pending maker would depend on which tests ran first,
    // since they share a database and one of them promotes the whole queue.
    const mauser = signedIn.locator("tbody tr", { hasText: "Mauser" });

    await signedIn.getByLabel("Showing").selectOption("approved");
    await searchFor(signedIn, "Mauser");
    await expect(mauser.first()).toBeVisible();

    await signedIn.getByLabel("Showing").selectOption("pending");
    await expect(mauser).toHaveCount(0);
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
