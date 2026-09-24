/**
 * The Backups page, in the states a real deployment reaches but the e2e one
 * does not: a snapshot directory holding both engines' files after a move
 * from SQLite to PostgreSQL, a last run that failed, an empty directory with
 * the schedule off, and each request failing. Answered from routes shaped as
 * /api/admin/backups is; admin.spec.js drives the real endpoint.
 */
import { test, expect } from "./fixtures.js";

const SETTINGS = {
  enabled: false,
  interval_hours: 24,
  keep: 7,
  last_run_at: "2026-09-20T03:00:00Z",
  last_status: "FAILED",
  last_error: "pg_dump: connection refused",
  last_bytes: null,
};

const BOTH_ENGINES = {
  directory: "/var/lib/milsurp/backups",
  engine: "postgresql",
  restore_hint: "pg_restore -d milsurp <file>",
  interval_choices: [6, 12, 24, 48],
  keep_choices: [3, 7, 14],
  total_bytes: 3 * 1048576,
  settings: SETTINGS,
  snapshots: [
    {
      name: "milsurp-20260921.dump",
      taken_at: "2026-09-21T03:00:00Z",
      bytes: 2 * 1048576,
      engine: "postgresql",
      restore_hint: "pg_restore -d milsurp milsurp-20260921.dump",
    },
    {
      name: "milsurp-20260901.db",
      taken_at: "2026-09-01T03:00:00Z",
      bytes: 1048576,
      engine: "sqlite",
      restore_hint: "cp milsurp-20260901.db milsurp.db",
    },
  ],
};

async function serve(page, state) {
  await page.route("**/api/admin/backups", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: state })
      : route.fallback(),
  );
  await page.goto("/backups");
  await expect(page.getByRole("heading", { name: "Backups" })).toBeVisible();
}

test.describe("backups, in the states a test deployment never reaches", () => {
  test("a snapshot from the other engine is marked, and says how to restore it", async ({
    signedIn,
  }) => {
    await serve(signedIn, BOTH_ENGINES);
    const other = signedIn.locator("tbody tr", { hasText: "milsurp-20260901.db" });
    const chip = other.locator(".chip--warning");
    await expect(chip).toHaveText("sqlite3 file");
    await expect(chip).toHaveAttribute(
      "title",
      /not what this application is running now/,
    );
    const same = signedIn.locator("tbody tr", { hasText: "milsurp-20260921.dump" });
    await expect(same.locator(".chip--neutral")).toHaveText("pg_restore");
  });

  test("a failed last run is shown as a failure, with its reason", async ({
    signedIn,
  }) => {
    await serve(signedIn, BOTH_ENGINES);
    await expect(signedIn.locator(".alert--error")).toContainText(
      "failed: pg_dump: connection refused",
    );
  });

  test("an empty directory with the schedule off says what to do", async ({
    signedIn,
  }) => {
    await serve(signedIn, {
      ...BOTH_ENGINES,
      total_bytes: 0,
      snapshots: [],
      settings: { ...SETTINGS, last_run_at: null },
    });
    await expect(signedIn.locator(".empty")).toContainText("The schedule is off");
  });

  test("a settings page that cannot be read says so", async ({ signedIn }) => {
    await signedIn.route("**/api/admin/backups", (route) =>
      route.fulfill({
        status: 500,
        json: { detail: "Could not read the backup settings." },
      }),
    );
    await signedIn.goto("/backups");
    await expect(signedIn.locator(".alert--error")).toContainText(
      "Could not read the backup settings.",
    );
  });

  test("a change the server refuses says why", async ({ signedIn }) => {
    await signedIn.route("**/api/admin/backups", (route) =>
      route.request().method() === "PATCH"
        ? route.fulfill({ status: 400, json: { detail: "Keep at least one." } })
        : route.fulfill({ json: BOTH_ENGINES }),
    );
    await signedIn.goto("/backups");
    // The switch itself, as a person clicks it: the checkbox is visually
    // hidden behind the styled track.
    await signedIn
      .locator(".panel", { hasText: "Schedule" })
      .locator("label.switch")
      .click();
    await expect(
      signedIn.locator(".alert--error", { hasText: "Keep at least one." }),
    ).toBeVisible();
  });

  test("a backup that fails says so rather than claiming to have written one", async ({
    signedIn,
  }) => {
    await serve(signedIn, BOTH_ENGINES);
    await signedIn.route("**/api/admin/backups/run", (route) =>
      route.fulfill({ status: 500, json: { detail: "The disk is full." } }),
    );
    await signedIn.getByRole("button", { name: "Back up now" }).click();
    // Its own message, beside the standing "last run failed" one.
    await expect(
      signedIn.locator(".alert--error", { hasText: "The disk is full." }),
    ).toBeVisible();
    await expect(signedIn.locator(".alert--success")).toHaveCount(0);
  });
});
