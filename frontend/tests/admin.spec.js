/** Admin surfaces: site controls, scan history, user management, settings. */
import { test, expect } from "./fixtures.js";

test.describe("sites", () => {
  test("lists every site with its status", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    await expect(signedIn.getByRole("heading", { name: "Sites" })).toBeVisible();

    const cards = signedIn.locator(".site-card");
    // `.count()` does not auto-wait, so this read zero on the first test of a
    // run — the heading renders before the site list has arrived.
    await expect(cards.first()).toBeVisible();
    await expect(cards.first().locator(".site-card__name")).not.toBeEmpty();
    // The at-a-glance roll-up: active, total seen, last scan, scan time.
    await expect(cards.first().locator(".site-card__stat")).toHaveCount(4);
    await expect(cards.first().locator(".site-card__stat-label").nth(3)).toHaveText(
      "Scan time",
    );
  });

  test("a site can be disabled and re-enabled", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    const card = signedIn.locator(".site-card").first();
    // The checkbox itself is visually hidden so the switch can be styled; the
    // label is the real affordance, and clicking it is what a user does.
    const label = card.locator("label.switch");
    const toggle = card.getByRole("checkbox");

    const wasEnabled = await toggle.isChecked();
    await label.click();
    await expect(toggle).toBeChecked({ checked: !wasEnabled });

    // Put it back so the suite leaves no state behind.
    await label.click();
    await expect(toggle).toBeChecked({ checked: wasEnabled });
  });

  test("the scan frequency can be changed and persists", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    const select = signedIn.locator(".site-card").first().locator("select");
    await select.selectOption("360");

    await signedIn.reload();
    await expect(signedIn.locator(".site-card").first().locator("select")).toHaveValue(
      "360",
    );
  });

  test("a fortnightly cadence is offered and sticks", async ({ signedIn }) => {
    /**
     * Added for Collectors Firearms, whose crawl delay makes a pass cost
     * hours: weekly was the longest the list offered and it was not long
     * enough. Labeled "Every 2 weeks" rather than "biweekly", which means
     * both "every two weeks" and "twice a week".
     */
    await signedIn.goto("/sites");
    const select = signedIn.locator(".site-card").first().locator("select");

    await expect(select.locator("option", { hasText: "Every 2 weeks" })).toHaveCount(1);
    await select.selectOption("20160");

    await signedIn.reload();
    await expect(signedIn.locator(".site-card").first().locator("select")).toHaveValue(
      "20160",
    );
  });

  test("both scan controls are on the card whether or not one is running", async ({
    signedIn,
  }) => {
    /**
     * They used to swap places, and a control that exists only in one state is
     * a control nobody can find in the other. Stop disappeared the moment a
     * scan ended — which reads as a scan that cannot be stopped — and whatever
     * was rendered next inherited its position and its click.
     */
    await signedIn.goto("/sites");
    const card = signedIn.locator(".site-card", { hasText: "Demo Vendor" });
    const scan = card.getByRole("button", { name: "Scan now" });
    const stop = card.getByRole("button", { name: "Stop", exact: true });

    await expect(scan).toBeVisible();
    await expect(stop).toBeVisible();

    // Idle: startable, and nothing to stop.
    await expect(scan).toBeEnabled();
    await expect(stop).toBeDisabled();
  });

  test("photographs can be fetched without re-scraping", async ({ signedIn }) => {
    /*
     * A scan caps how many photographs it downloads and carries the rest to
     * the next run, so a shop that gains hundreds of listings at once drains
     * its backlog a scan at a time. These buttons are that download step on
     * its own, and they exist in both states for the same reason Scan now and
     * Stop do: a control that appears only when there is work is a control
     * nobody can find when they are wondering whether there is any.
     */
    await signedIn.goto("/sites");
    const everywhere = signedIn.getByRole("button", { name: /^Update photos/ }).first();
    await expect(everywhere).toBeVisible();

    const card = signedIn.locator(".site-card", { hasText: "Demo Vendor" });
    const forOneSite = card.getByRole("button", { name: /^Update photos/ });
    await expect(forOneSite).toBeVisible();

    // Nothing is outstanding on a freshly seeded database, so both say so by
    // being unpressable rather than by disappearing.
    await expect(forOneSite).toBeDisabled();
    await expect(forOneSite).toHaveAttribute("title", /already stored/);
  });

  test("product pages can be queued to be read again", async ({ signedIn }) => {
    /*
     * A scan skips the product page of any listing it has already read one
     * for, so fixing how a page is parsed reaches only the listings it has
     * never seen. This is the control that says "those ones too" — and it has
     * to be on the page, because the alternative was a make target on a
     * production server.
     */
    await signedIn.goto("/sites");
    const card = signedIn.locator(".site-card", { hasText: "Demo Vendor" });
    const button = card.getByRole("button", { name: /^Re-read details/ });

    await expect(button).toBeVisible();
    // Nothing on a freshly seeded database has had a product page read, so
    // the next scan reads them all anyway and there is nothing to queue. It
    // says so by being unpressable rather than by disappearing.
    await expect(button).toBeDisabled();
    await expect(button).toHaveAttribute("title", /reads them all anyway/);
  });

  test("scan now shows progress, then the outcome", async ({ signedIn }) => {
    // Waits on a real scan run, so it needs more than the default 30s budget.
    test.setTimeout(90_000);
    await signedIn.goto("/sites");
    // The demo vendor performs no network access, so this exercises the whole
    // scan pipeline without contacting a real shop.
    const card = signedIn.locator(".site-card", { hasText: "Demo Vendor" });
    await expect(card).toBeVisible();

    await card.getByRole("button", { name: "Scan now" }).click();

    // While it runs: an indeterminate progress bar and a spinner chip. The
    // scan may finish very quickly against a stub site, so accept either the
    // in-progress state or the outcome that immediately follows it.
    const progress = card.getByRole("progressbar");
    const outcome = card.locator(".site-card__result");
    await expect(progress.or(outcome).first()).toBeVisible({ timeout: 15000 });

    // It must always end in a stated outcome rather than silently going quiet.
    await expect(outcome).toBeVisible({ timeout: 60000 });
    await expect(outcome).toContainText(/Scan (complete|failed|canceled|finished)/);

    // ...and the result can be dismissed.
    await outcome.getByRole("button", { name: "Dismiss scan result" }).click();
    await expect(outcome).toHaveCount(0);
  });

  test("a scan updates the last-scan time and the next-scan countdown", async ({
    signedIn,
  }) => {
    test.setTimeout(90_000);
    await signedIn.goto("/sites");
    const card = signedIn.locator(".site-card", { hasText: "Demo Vendor" });
    // Selected by its label rather than by position: a fourth stat was added
    // later and .last() silently started pointing at the wrong cell.
    const lastScan = card.locator(".site-card__stat", { hasText: "Last scan" });
    const scanTime = card.locator(".site-card__stat", { hasText: "Scan time" });

    await card.getByRole("button", { name: "Scan now" }).click();
    await expect(card.locator(".site-card__result")).toBeVisible({ timeout: 60000 });

    // An out-of-band scan resets the schedule, so "last scan" becomes recent.
    await expect(lastScan).toContainText(/second|minute|just now|ago/i);
    // ...and how long it took end to end, as seconds or m/s.
    await expect(scanTime).toContainText(/^\d+(\.\d+)?s|^\d+m \d+s/m);
  });

  test("a due time in the past reads as overdue, not as a next scan", async ({
    signedIn,
  }) => {
    /**
     * "Next scan 3 hours ago" -- seen on a real deployment. formatRelative
     * reads both directions and the label only made sense in one of them, so
     * every overdue site contradicted itself.
     *
     * A due time in the past is a normal state rather than a glitch: the
     * scheduler ships disabled, and a database restored from another machine
     * carries that machine's schedule with it. Both leave the time behind.
     */
    await signedIn.goto("/sites");
    const card = signedIn.locator(".site-card", { hasText: "Demo Vendor" });
    const schedule = card.locator("div", { hasText: /Next scan|Scan overdue/ }).last();
    await expect(schedule).toBeVisible();

    // Whichever way it reads, it must not say "next ... ago".
    await expect(schedule).not.toContainText(/Next scan .*ago/i);
  });

  test("vendors that are not built yet are listed as coming soon", async ({
    signedIn,
  }) => {
    /**
     * The question the page gets asked after "what is here?", which is "is
     * that all of them?". Each card says what is standing in the way, because
     * "not written yet" and "cannot get in" are different kinds of waiting.
     */
    await signedIn.goto("/sites");
    const planned = signedIn.locator(".site-card--planned");
    const heading = signedIn.getByRole("heading", { name: "Coming soon" });

    if ((await planned.count()) === 0) {
      // The queue emptied for the first time when Simpson Ltd. shipped and the
      // last three were dropped. An empty list must render *nothing* rather
      // than a heading over a gap, which is the only thing left to check here.
      await expect(heading).toHaveCount(0);
      return;
    }

    await expect(heading).toBeVisible();
    await expect(planned.first()).toBeVisible();

    // Nothing to operate: no row behind it, so no controls that could work.
    await expect(planned.first().getByRole("button")).toHaveCount(0);
    await expect(planned.first().locator("select")).toHaveCount(0);
    await expect(planned.first()).toContainText("Coming soon");
  });

  test("scan history is reachable from a site", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    await signedIn
      .locator(".site-card")
      .first()
      .getByRole("link", { name: "History" })
      .click();

    await expect(signedIn).toHaveURL(/\/sites\/\d+/);
    await expect(signedIn.getByRole("heading", { name: "Scan history" })).toBeVisible();
  });
});

test.describe("users", () => {
  test("lists accounts with role and status", async ({ signedIn }) => {
    await signedIn.goto("/users");
    await expect(signedIn.getByRole("heading", { name: "Users" })).toBeVisible();
    // The username cell also carries the full name underneath, so this is a
    // substring match rather than an exact one.
    await expect(
      signedIn.getByRole("cell").filter({ hasText: "admin" }).first(),
    ).toBeVisible();
    await expect(
      signedIn.getByRole("cell", { name: "Admin", exact: true }),
    ).toBeVisible();
  });

  test("the add-user dialog validates before submitting", async ({ signedIn }) => {
    await signedIn.goto("/users");
    await signedIn.getByRole("button", { name: "Add user" }).click();

    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // The password field advertises the server's policy to the browser rather
    // than a hard-coded number, so raising security.min_password_length is
    // reflected here without a frontend change.
    await expect(dialog.locator('input[type="password"]')).toHaveAttribute(
      "minlength",
      /^\d+$/,
    );

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
  });

  test("an admin cannot delete their own account", async ({ signedIn }) => {
    await signedIn.goto("/users");
    const row = signedIn.getByRole("row", { name: /admin/ }).first();
    await expect(row.getByRole("button").last()).toBeDisabled();
  });

  test("field hints describe rather than name the control", async ({ signedIn }) => {
    // Regression guard: a hint nested inside the <label> becomes part of the
    // control's accessible name, so a screen reader would announce
    // "Password At least 12 characters…" as the field's name. Hints belong in
    // aria-describedby instead.
    await signedIn.goto("/users");
    await signedIn.getByRole("button", { name: "Add user" }).click();
    const dialog = signedIn.getByRole("dialog");

    const password = dialog.getByLabel("Password", { exact: true });
    await expect(password).toBeVisible();
    await expect(password).toHaveAttribute("aria-describedby", /.+/);

    // The hint text comes from the server's derived rules, so it always
    // matches what is actually enforced.
    await expect(dialog.getByText(/Must be at least \d+ characters/)).toBeVisible();

    await dialog.getByRole("button", { name: "Cancel" }).click();
  });

  test("escape closes the dialog", async ({ signedIn }) => {
    await signedIn.goto("/users");
    await signedIn.getByRole("button", { name: "Add user" }).click();
    await expect(signedIn.getByRole("dialog")).toBeVisible();

    await signedIn.keyboard.press("Escape");
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
  });
});

test.describe("email digest settings", () => {
  test("shows the current preferences", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    await expect(signedIn.getByRole("heading", { name: "Email digest" })).toBeVisible();
    await expect(signedIn.getByRole("heading", { name: "Delivery" })).toBeVisible();
    await expect(signedIn.getByRole("heading", { name: /New listings/ })).toBeVisible();
    await expect(
      signedIn.getByRole("heading", { name: /Price reductions/ }),
    ).toBeVisible();
  });

  test("settings save and survive a reload", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    await signedIn.getByLabel("How often").selectOption("12");
    await signedIn.getByRole("button", { name: "Save settings" }).click();

    await expect(signedIn.getByRole("status")).toContainText(/saved/i);
    await signedIn.reload();
    await expect(signedIn.getByLabel("How often")).toHaveValue("12");
  });

  test("the per-site item cap is offered as a bounded choice", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    // A free-text field would let someone ask for a thousand items per email.
    const limit = signedIn.getByLabel("Most per site").first();
    await expect(limit).toBeVisible();
    await limit.selectOption("5");
    await signedIn.getByRole("button", { name: "Save settings" }).click();
    await expect(signedIn.getByRole("status")).toBeVisible();
  });

  test("the password panel has moved off this page", async ({ signedIn }) => {
    // It lived here since it was written, under a nav item called Email
    // digest, which is not where anybody looks for it.
    await signedIn.goto("/settings");
    await expect(signedIn.getByRole("heading", { name: "Password" })).toHaveCount(0);

    await signedIn.goto("/security");
    await expect(
      signedIn.getByRole("heading", { name: "Security settings" }),
    ).toBeVisible();
    await expect(signedIn.getByRole("heading", { name: "Password" })).toBeVisible();
    await expect(signedIn.getByLabel("Current password")).toBeVisible();
  });
});

test.describe("navigation", () => {
  test("every top-level page is reachable", async ({ signedIn }) => {
    for (const [name, heading] of [
      ["Sites", "Sites"],
      ["Armory", "Armory"],
      ["Classification", "Classification"],
      ["Users", "Users"],
      ["Email digest", "Email digest"],
      ["Security settings", "Security settings"],
      ["Inventory", "Inventory"],
    ]) {
      await signedIn.getByRole("link", { name, exact: true }).click();
      await expect(signedIn.getByRole("heading", { name: heading })).toBeVisible();
    }
  });

  test("the old Makers URL still lands somewhere sensible", async ({ signedIn }) => {
    // Bookmarked and linked from the release notes, so a redirect rather than
    // the inventory fallback that every other unknown route gets.
    await signedIn.goto("/manufacturers");
    await expect(signedIn.getByRole("heading", { name: "Armory" })).toBeVisible();
  });

  test("an unknown route falls back to the inventory", async ({ signedIn }) => {
    await signedIn.goto("/no-such-page");
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });
});

test.describe("backups", () => {
  test("the schedule can be switched on and its frequency changed", async ({
    signedIn,
  }) => {
    await signedIn.goto("/backups");
    await expect(signedIn.getByRole("heading", { name: "Backups" })).toBeVisible();

    // Off on a new installation: an upgrade should not start writing files
    // nobody asked for.
    const toggle = signedIn.getByRole("checkbox");
    await expect(toggle).not.toBeChecked();

    // The frequency is unusable until the schedule is on, which is the whole
    // meaning of the switch.
    const howOften = signedIn.getByLabel("How often");
    await expect(howOften).toBeDisabled();

    await signedIn.locator("label.switch").click();
    await expect(toggle).toBeChecked();
    await expect(howOften).toBeEnabled();

    await howOften.selectOption("12");
    // It persisted, rather than only changing on screen.
    await signedIn.reload();
    await expect(signedIn.getByLabel("How often")).toHaveValue("12");
    await expect(signedIn.getByRole("checkbox")).toBeChecked();
  });

  test("“Back up now” writes a snapshot and lists it", async ({ signedIn }) => {
    await signedIn.goto("/backups");
    await expect(signedIn.getByRole("heading", { name: "Backups" })).toBeVisible();

    // Nothing yet, and the empty state says why rather than being blank.
    await expect(signedIn.locator(".empty")).toContainText("No snapshots yet");

    await signedIn.getByRole("button", { name: "Back up now" }).click();

    await expect(signedIn.locator(".alert--success")).toContainText("Wrote milsurp-");
    const rows = signedIn.locator("table.table tbody tr");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("milsurp-");
    // And the run is recorded where somebody would look for it.
    await expect(signedIn.getByText(/Last run/)).toBeVisible();
  });
});

test.describe("sessions and the audit log", () => {
  test("the sessions list names this browser", async ({ signedIn }) => {
    /**
     * The first thing anybody looks for, and the reason the list is worth
     * having at all: "which one is this?" Signing yourself out by accident is
     * the obvious mistake, so the current session is labelled and its button
     * says Sign out rather than Revoke.
     */
    await signedIn.goto("/security");
    const row = signedIn.locator("tbody tr", { hasText: "This browser" });
    await expect(row).toHaveCount(1);
    await expect(row.getByRole("button", { name: "Sign out" })).toBeVisible();
  });

  test("administrative actions show up in the audit log", async ({ signedIn }) => {
    /**
     * End to end rather than through the API: the point of the log is that
     * somebody can go and read it, so the test does what they would.
     */
    await signedIn.goto("/users");
    await signedIn.getByRole("button", { name: "Add user" }).click();

    // Labels, not name attributes: this form builds its ids through <Field>,
    // so the label is the stable handle.
    const dialog = signedIn.getByRole("dialog");
    await dialog.getByLabel("Username").fill("audited-by-e2e");
    // example.com, not example.test: Pydantic's EmailStr refuses the RFC 2606
    // reserved TLDs, so a .test address fails validation and the dialog stays
    // open -- which is exactly how this test failed the first time.
    await dialog.getByLabel("Email address").fill("audited@example.com");
    await dialog.locator('input[type="password"]').fill("a-long-enough-passphrase");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog).toBeHidden();

    await signedIn.goto("/audit");
    const row = signedIn.locator("tbody tr", { hasText: "audited-by-e2e" });
    await expect(row.first()).toBeVisible();
    await expect(row.first()).toContainText("User created");
    await expect(row.first()).toContainText("admin");
  });

  test("the audit log is admin-only in the navigation", async ({ signedIn }) => {
    await expect(signedIn.getByRole("link", { name: "Audit log" })).toBeVisible();
  });
});
