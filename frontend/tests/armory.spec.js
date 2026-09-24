/**
 * The armory page.
 *
 * The behavior worth pinning down here is the approval gate: everything
 * arrives awaiting approval, promoting is what moves it into production, and
 * nothing in between is silent about which state a row is in.
 */
import { test, expect } from "./fixtures.js";

/**
 * Wait until the *manufacturers* table is the one on screen.
 *
 * Clicking a tab does not clear the previous tab's rows while the new ones
 * load, so a count taken straight after the click can be the Models tab's:
 * "a maker can be deleted" read 553 delete buttons that way and then compared
 * them against 63 makers. The expander is in the makers table and nowhere
 * else, which makes it the signal that the swap has happened.
 */
async function makersAreShowing(page) {
  await expect(page.getByRole("button", { name: /^Expand / }).first()).toBeVisible();
}

/**
 * Wait until a named row on the Calibers tab is really on screen.
 *
 * Two races in one, and the same answer to both. Clicking a tab does not
 * clear the previous tab's rows while the new ones load, so `tbody tr` read
 * straight afterwards can still be the Models tab's -- and `hasText` matches
 * anywhere in a row, so a caliber name hits a Models row's "Chambered in"
 * cell. Separately, "Load shipped armory" is still committing while the next
 * click is being made.
 *
 * Polling the row *names* has neither hole, which is the same reasoning the
 * sort test below already arrived at: waiting for a loading row to be absent
 * races the reload starting, because it is absent before it begins too.
 */
async function caliberRowIsShowing(page, name) {
  await expect
    .poll(() => page.locator("tbody tr td:nth-child(2) button").allInnerTexts())
    .toContain(name);
}

test.describe("armory", () => {
  test.beforeEach(async ({ signedIn }) => {
    // Exact, both the link and the heading: the inventory the test starts on
    // has a card headed "US M1 Garand, Springfield Armory 1944", which is also
    // a link. A substring match on the heading passed while still on that page whenever the click was lost
    // to a re-render -- and the test then waited ten seconds for a button that
    // was never going to be there. Retried until the URL moves, so a click the
    // inventory swallowed while it was still rendering is simply made again.
    await expect(async () => {
      await signedIn.getByRole("link", { name: "Armory", exact: true }).click();
      await expect(signedIn).toHaveURL(/\/armory/, { timeout: 2000 });
    }).toPass();
    await expect(
      signedIn.getByRole("heading", { name: "Armory", exact: true }),
    ).toBeVisible();
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

  test("a row awaiting approval shows how many listings name it, and the eye opens them", async ({
    signedIn,
  }) => {
    // Straight after the load above, so M1 Garand is still awaiting approval:
    // a later test promotes the whole queue. A pending row links nothing, so
    // its count is of listings that *name* it -- and the eye has to open that
    // same set, or the number in the table is a promise the page breaks.
    await signedIn.getByLabel("Search").fill("M1 Garand");
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await makersAreShowing(signedIn);

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

  test("a row switched off leaves the queue and lands under Disabled", async ({
    signedIn,
  }) => {
    /**
     * Reported from the running site: two manufacturers switched off by hand
     * went on showing under "Awaiting approval" and kept the nav badge lit.
     * Turning a row off is ruling on it — it matches nothing afterwards,
     * exactly like a pending row — but the filter asked only about status.
     */
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
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
    // Every other test here waits for this and this one did not, so it was
    // searching a table the load had not finished filling.
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Calibers" }).click();
    await caliberRowIsShowing(signedIn, ".32 ACP");

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
      await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
      await expect(signedIn.locator(".alert--success")).toBeVisible();
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Models" }).click();
    // See the note above about .loading-row doubling as the empty state.
    await signedIn.getByLabel("Showing").selectOption("");
    await expect(
      signedIn.getByRole("button", { name: "Merge\u2026" }).first(),
    ).toBeVisible();

    const row = signedIn.locator("tbody tr").first();
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();
    await signedIn.getByRole("tab", { name: "Manufacturers" }).click();
    await signedIn.getByLabel("Showing").selectOption("approved");
    await signedIn.getByRole("button", { name: "Expand Mauser" }).click();

    const drilldown = signedIn.locator(".armory-drilldown");
    await expect(drilldown).toBeVisible();
    const view = drilldown.getByRole("link", { name: /^View listings for/ }).first();
    await expect(view).toBeVisible();

    // By model id, not by name -- the same link the models tab builds, so a
    // renamed model cannot strand it. See listingsHref.
    const href = await view.getAttribute("href");
    expect(href).toContain("model=");
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
    await signedIn.getByRole("button", { name: "Load shipped armory" }).click();
    await expect(signedIn.locator(".alert--success")).toBeVisible();

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
    expect(signedIn.url()).toContain("q=mauser");

    // Six keystrokes, zero history entries: one Back leaves the armory
    // altogether rather than spelling "mause", "maus", "mau"...
    await signedIn.goBack();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
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
    const readNames = () =>
      signedIn.locator("tbody tr td:nth-child(2) button").allInnerTexts();

    // Keep the snapshot that satisfied the poll rather than reading again.
    // Two reloads are in flight here — the tab click starts one and the filter
    // starts another — so a second read can land after the poll passed and
    // catch the table mid-replace, with every probe back to index -1. Asserting
    // on the array that *was* complete has no such gap.
    let names = [];
    await expect
      .poll(async () => {
        const found = await readNames();
        if (!probes.every((probe) => found.includes(probe))) return false;
        names = found;
        return true;
      })
      .toBe(true);

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
    // Let the load report before changing the view: its reload is still in
    // flight otherwise, and would overwrite the filter change below.
    await expect(signedIn.locator(".alert--success")).toBeVisible();
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

test.describe("armory access", () => {
  // Outside the describe above, which signs in before every test — that is
  // what this one must not have done.
  test("is not reachable without signing in", async ({ page }) => {
    await page.goto("/armory");
    await expect(page.locator('input[name="username"]')).toBeVisible();
  });
});
