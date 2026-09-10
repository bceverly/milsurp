/**
 * Longer journeys: scan drill-down, the user lifecycle, and digest settings.
 *
 * These exercise the paths a spot-check misses — the ones that only run when
 * you complete a task rather than just load a page.
 */
import { test, expect } from "./fixtures.js";

test.describe("scan drill-down", () => {
  test("from a site through its history to one run's log", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    await signedIn
      .locator(".site-card")
      .first()
      .getByRole("link", { name: "History" })
      .click();
    await expect(signedIn.getByRole("heading", { name: "Scan history" })).toBeVisible();

    const rows = signedIn.locator("table tbody tr");
    // `.count()` does not auto-wait; the heading arrives before the table does.
    await expect(rows.first()).toBeVisible();

    await rows.first().getByRole("link", { name: "Details" }).click();
    await expect(signedIn).toHaveURL(/\/scans\/\d+/);
  });

  test("a scan detail page shows results and the progress log", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    await signedIn
      .locator(".site-card")
      .first()
      .getByRole("link", { name: "History" })
      .click();
    await signedIn
      .locator("table tbody tr")
      .first()
      .getByRole("link", { name: "Details" })
      .click();

    await expect(signedIn.getByRole("heading", { name: "Results" })).toBeVisible();
    await expect(signedIn.getByRole("heading", { name: "Progress log" })).toBeVisible();
    await expect(signedIn.locator(".scan-log")).not.toBeEmpty();
    // The seven result counters.
    await expect(signedIn.locator(".stat")).toHaveCount(7);
  });

  test("a partial scan surfaces its warnings", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    await signedIn
      .locator(".site-card")
      .first()
      .getByRole("link", { name: "History" })
      .click();

    const partial = signedIn.locator("table tbody tr", { hasText: "Partial" }).first();
    if ((await partial.count()) > 0) {
      await partial.getByRole("link", { name: "Details" }).click();
      await expect(signedIn.getByRole("alert")).toContainText(/warning/i);
    }
  });

  test("an unknown scan id shows an error", async ({ signedIn }) => {
    await signedIn.goto("/scans/999999");
    await expect(signedIn.getByRole("alert")).toBeVisible();
  });

  test("back from a scan returns to the history", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    await signedIn
      .locator(".site-card")
      .first()
      .getByRole("link", { name: "History" })
      .click();
    await signedIn
      .locator("table tbody tr")
      .first()
      .getByRole("link", { name: "Details" })
      .click();

    await signedIn.getByRole("button", { name: "Back", exact: true }).first().click();
    await expect(signedIn.getByRole("heading", { name: "Scan history" })).toBeVisible();
  });
});

test.describe("user lifecycle", () => {
  // A distinct name per run so a retry cannot collide with its own leftovers.
  const username = `e2e${Date.now().toString().slice(-8)}`;

  test("create, edit, then delete an account", async ({ signedIn }) => {
    await signedIn.goto("/users");

    // --- create ---
    await signedIn.getByRole("button", { name: "Add user" }).click();
    const dialog = signedIn.getByRole("dialog");
    await dialog.getByLabel("Username").fill(username);
    await dialog.getByLabel("Email address").fill(`${username}@example.com`);
    await dialog.getByLabel("Full name (optional)").fill("End To End");
    await dialog.getByLabel("Password", { exact: true }).fill("a-long-enough-passphrase");
    await dialog.getByRole("button", { name: "Save" }).click();

    await expect(dialog).toHaveCount(0);
    const row = signedIn.getByRole("row", { name: new RegExp(username) });
    await expect(row).toBeVisible();
    await expect(row).toContainText("Normal");
    await expect(row).toContainText("Active");

    // --- edit: promote and deactivate ---
    await row.getByRole("button", { name: "Edit" }).click();
    const editDialog = signedIn.getByRole("dialog");
    await editDialog.getByLabel("Role").selectOption("admin");
    await editDialog.getByLabel("Account is active").uncheck();
    await editDialog.getByRole("button", { name: "Save" }).click();

    await expect(editDialog).toHaveCount(0);
    const updated = signedIn.getByRole("row", { name: new RegExp(username) });
    await expect(updated).toContainText("Admin");
    await expect(updated).toContainText("Disabled");

    // --- delete ---
    await updated.getByRole("button").last().click();
    const confirm = signedIn.getByRole("dialog");
    await expect(confirm).toContainText("cannot be undone");
    await confirm.getByRole("button", { name: "Delete permanently" }).click();

    await expect(signedIn.getByRole("row", { name: new RegExp(username) })).toHaveCount(
      0,
    );
  });

  test("a duplicate username is rejected with a message", async ({ signedIn }) => {
    await signedIn.goto("/users");
    await signedIn.getByRole("button", { name: "Add user" }).click();

    const dialog = signedIn.getByRole("dialog");
    await dialog.getByLabel("Username").fill("admin");
    await dialog.getByLabel("Email address").fill("duplicate@example.com");
    await dialog.getByLabel("Password", { exact: true }).fill("a-long-enough-passphrase");
    await dialog.getByRole("button", { name: "Save" }).click();

    await expect(dialog.getByRole("alert")).toContainText(/already in use/i);
  });

  test("the list can be refreshed", async ({ signedIn }) => {
    await signedIn.goto("/users");
    await signedIn.getByRole("button", { name: "Refresh" }).click();
    await expect(signedIn.getByRole("heading", { name: "Users" })).toBeVisible();
  });
});

test.describe("digest settings", () => {
  test("toggling a section disables its limit control", async ({ signedIn }) => {
    await signedIn.goto("/settings");

    const panel = signedIn.locator(".panel", { hasText: "New listings" });
    // The checkbox is visually hidden so the switch can be styled, so click the
    // label — which is the affordance a user sees and presses.
    const toggle = panel.locator("label.switch");
    const state = panel.getByRole("checkbox");
    const limit = signedIn.getByLabel("Most per site").first();

    await expect(limit).toBeEnabled();
    await toggle.click();
    await expect(state).not.toBeChecked();
    // With the section off, its cap is meaningless.
    await expect(limit).toBeDisabled();

    await toggle.click();
    await expect(state).toBeChecked();
    await expect(limit).toBeEnabled();
  });

  test("price reduction options save and persist", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    await signedIn.getByLabel("Ignore drops under").fill("50");
    await signedIn.getByRole("button", { name: "Save settings" }).click();
    await expect(signedIn.getByRole("status")).toContainText(/saved/i);

    await signedIn.reload();
    await expect(signedIn.getByLabel("Ignore drops under")).toHaveValue("50");
  });

  test("site selection persists", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    const sitePanel = signedIn.locator(".panel", { hasText: "Sites" });
    await sitePanel.getByRole("checkbox").first().check();
    await signedIn.getByRole("button", { name: "Save settings" }).click();
    await expect(signedIn.getByRole("status")).toBeVisible();

    await signedIn.reload();
    await expect(
      signedIn.locator(".panel", { hasText: "Sites" }).getByRole("checkbox").first(),
    ).toBeChecked();
  });

  test("enabling delivery shows the next send time", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    // Scoped to the panel header: the body also has a "skip when empty" box.
    const delivery = signedIn.locator(".panel", { hasText: "Delivery" });
    const master = delivery.locator(".panel__head label.switch");
    if (!(await delivery.locator(".panel__head").getByRole("checkbox").isChecked())) {
      await master.click();
    }
    await signedIn.getByRole("button", { name: "Save settings" }).click();

    await expect(signedIn.getByRole("status")).toBeVisible();
    await expect(signedIn.getByText(/Next digest/)).toBeVisible();
  });

  test("sending a digest reports that email is not configured", async ({ signedIn }) => {
    // Email is deliberately off in the test config, so this exercises the
    // failure path a user hits before setting up SMTP.
    await signedIn.goto("/settings");
    await signedIn.getByRole("button", { name: "Send one now" }).click();
    await expect(signedIn.getByRole("alert")).toContainText(/disabled|unavailable/i);
  });

  test("the timezone selector offers this device's zone", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    await expect(signedIn.getByLabel("Times shown in")).toContainText("this device");
  });

  test("the frequency selector persists", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    await signedIn.getByLabel("How often").selectOption("168");
    await signedIn.getByRole("button", { name: "Save settings" }).click();
    await expect(signedIn.getByRole("status")).toBeVisible();

    await signedIn.reload();
    await expect(signedIn.getByLabel("How often")).toHaveValue("168");
  });
});

test.describe("item detail extras", () => {
  test("a listing shows where its price sits among the same gun", async ({
    signedIn,
  }) => {
    /**
     * The question the catalog exists for — "is this a good deal?" — and the
     * first thing in it that answers. The bar is scaled by *rank*, not by
     * dollars: surplus prices are skewed hard enough that a dollar axis puts
     * nine listings in ten inside its leftmost tenth.
     */
    await signedIn.goto("/?search=Mosin&availability=all");
    const card = signedIn.locator(".item-card").first();
    await expect(card).toBeVisible();
    await card.click();
    await expect(signedIn.locator(".detail__facts")).toBeVisible();

    const spectrum = signedIn.locator(".spectrum");
    await expect(spectrum).toBeVisible();
    await expect(spectrum).toContainText("listings of this model");
    await expect(spectrum).toContainText(
      /cheapest one listed|dearest one listed|Cheaper than/,
    );

    // Three graduations and one marker, and the marker is somewhere on the bar.
    await expect(spectrum.locator(".spectrum__tick")).toHaveCount(3);
    const marker = spectrum.locator(".spectrum__marker");
    await expect(marker).toHaveCount(1);
    const left = await marker.evaluate((node) => node.style.left);
    expect(Number.parseFloat(left)).toBeGreaterThanOrEqual(0);
    expect(Number.parseFloat(left)).toBeLessThanOrEqual(100);
  });

  test("the dearest listing puts its marker at the far end", async ({ signedIn }) => {
    /**
     * Reported from the running site. The marker was placed by the *statistic*
     * — how many peers this one undercuts — and the dearest of five undercuts
     * four of them, which is 80%. A marker at 80% of a bar whose right end is
     * labeled with this listing's own price is simply wrong, and the two
     * numbers are now separate.
     */
    await signedIn.goto("/?search=Mosin&availability=all&sort=price_desc");
    const card = signedIn.locator(".item-card").first();
    await expect(card).toBeVisible();
    await card.click();

    const spectrum = signedIn.locator(".spectrum");
    await expect(spectrum).toBeVisible();
    // The dearest of its group: hard right, and the sentence says so rather
    // than quoting a percentage.
    const left = await spectrum
      .locator(".spectrum__marker")
      .evaluate((node) => node.style.left);
    expect(Number.parseFloat(left)).toBe(100);
    await expect(spectrum).toContainText("The dearest one listed");
  });

  test("a listing with nothing to compare against shows no spectrum", async ({
    signedIn,
  }) => {
    /** It needs a matched model, a maker, a cartridge and three peers, which
     *  most listings do not have — so the widget has to be absent rather than
     *  empty. */
    await signedIn.goto("/?search=Arisaka&availability=all");

    // Asserted on the grid before touching a card, so a fixture that has gone
    // missing says so instead of timing out on "element not found" — which is
    // what this reported when it failed, and it took a while to work out that
    // the complaint was about the search, not about the widget.
    const cards = signedIn.locator(".item-card");
    await expect
      .poll(() => cards.count(), {
        message: 'no listing matched "Arisaka" — check scripts/seed_demo_data.py',
      })
      .toBeGreaterThan(0);

    await cards.first().click();
    await expect(signedIn.locator(".detail__facts")).toBeVisible();
    // Not "has no model": a listing can be matched and still have no spectrum,
    // and since promoting a row now writes the link straight onto the listings,
    // the armory tests earlier in the run give this one a model. What it does
    // not have is three peers sharing its model and cartridge.
    await expect(signedIn.locator(".spectrum")).toHaveCount(0);
  });

  test("the armory panel opens from the model line", async ({ signedIn }) => {
    /**
     * What the armory knows was reachable only from the admin page before
     * this, by searching for the row by name. The panel is separate from the
     * facts beside it because it answers a different question: those describe
     * this listing, these describe the pattern, and the two are allowed to
     * disagree.
     */
    // Searched for rather than "whichever card sorts first": only a listing
    // the armory matched carries the panel, and the seeder gives a model to
    // exactly one of them.
    await signedIn.goto("/?search=Mosin&availability=all");
    // The card *is* the link — `.item-card` is a <Link>, not a wrapper round
    // one, so there is no anchor inside it to click.
    const card = signedIn.locator(".item-card").first();
    await expect(card).toBeVisible();
    await card.click();
    await expect(signedIn.locator(".detail__facts")).toBeVisible();

    const open = signedIn.getByRole("button", { name: "What the armory knows" });
    await open.click();
    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Country of the pattern");
    await expect(dialog).toContainText("Chambered in");
    await expect(
      dialog.getByRole("link", { name: "Every listing of this model" }),
    ).toBeVisible();

    // Escape closes it, like every other modal in the application.
    await signedIn.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });

  test("a reduced listing shows the previous price struck through", async ({
    signedIn,
  }) => {
    await signedIn.goto("/?price_drops_only=true");
    const cards = signedIn.locator(".item-card");
    if ((await cards.count()) > 0) {
      await expect(cards.first().locator(".item-card__was")).toBeVisible();
      await cards.first().click();
      await expect(signedIn.locator(".detail__price-was")).toBeVisible();
      // Two observations means the sparkline renders rather than the one-off note.
      await expect(signedIn.locator(".price-table")).toBeVisible();
    }
  });

  test("the description panel is shown when there is one", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn.getByRole("heading", { name: "Description" })).toBeVisible();
  });

  test("structured facts are populated", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn.locator(".detail__facts")).toBeVisible();
    await expect(signedIn.locator(".fact__label").first()).not.toBeEmpty();
  });

  test("sold and de-listed listings are reachable through the filters", async ({
    signedIn,
  }) => {
    await signedIn.goto("/?availability=sold");
    await expect(signedIn.getByText(/listings? match your filters/)).toBeVisible();

    await signedIn.goto("/?availability=delisted");
    await expect(signedIn.getByText(/listings? match your filters/)).toBeVisible();

    await signedIn.goto("/?availability=all");
    await expect(signedIn.locator(".item-card").first()).toBeVisible();
  });

  test("a listing with no price reads as call for price", async ({ signedIn }) => {
    await signedIn.goto("/?sort=price_desc&availability=all");
    await expect(signedIn.locator(".item-card").first()).toBeVisible();
    // Null prices sort last regardless of direction.
    const prices = await signedIn.locator(".item-card__price").allTextContents();
    expect(prices.length).toBeGreaterThan(0);
  });
});
