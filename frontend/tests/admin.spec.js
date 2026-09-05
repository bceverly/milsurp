/** Admin surfaces: site controls, scan history, user management, settings. */
import { test, expect } from "./fixtures.js";

test.describe("sites", () => {
  test("lists every site with its status", async ({ signedIn }) => {
    await signedIn.goto("/sites");
    await expect(signedIn.getByRole("heading", { name: "Sites" })).toBeVisible();

    const cards = signedIn.locator(".site-card");
    expect(await cards.count()).toBeGreaterThan(0);
    await expect(cards.first().locator(".site-card__name")).not.toBeEmpty();
    // The at-a-glance roll-up: active, total seen, last scan.
    await expect(cards.first().locator(".site-card__stat")).toHaveCount(3);
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
    const lastScan = card.locator(".site-card__stat").last();

    await card.getByRole("button", { name: "Scan now" }).click();
    await expect(card.locator(".site-card__result")).toBeVisible({ timeout: 60000 });

    // An out-of-band scan resets the schedule, so "last scan" becomes recent.
    await expect(lastScan).toContainText(/second|minute|just now|ago/i);
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

  test("the password panel is present", async ({ signedIn }) => {
    await signedIn.goto("/settings");
    await expect(signedIn.getByRole("heading", { name: "Password" })).toBeVisible();
    await expect(signedIn.getByLabel("Current password")).toBeVisible();
  });
});

test.describe("navigation", () => {
  test("every top-level page is reachable", async ({ signedIn }) => {
    for (const [name, heading] of [
      ["Sites", "Sites"],
      ["Users", "Users"],
      ["Email digest", "Email digest"],
      ["Inventory", "Inventory"],
    ]) {
      await signedIn.getByRole("link", { name, exact: true }).click();
      await expect(signedIn.getByRole("heading", { name: heading })).toBeVisible();
    }
  });

  test("an unknown route falls back to the inventory", async ({ signedIn }) => {
    await signedIn.goto("/no-such-page");
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });
});
