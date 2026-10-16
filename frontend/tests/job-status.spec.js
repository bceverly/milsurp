/**
 * Where each Site settings job stands (asked for on 2026-10-16: "how do i know
 * when update msrps and variants is done?"): running, with its progress;
 * waiting; and the last run's time, how long it took and how it went. What
 * the jobs report is the server's business; its answers are supplied here.
 */
import { test, expect, openPage } from "./fixtures.js";

const now = Date.now();
const ago = (minutes) => new Date(now - minutes * 60000).toISOString();

const JOBS = [
  {
    name: "variants",
    requested_at: null,
    started_at: ago(40),
    progress: "Bud's Gun Shop: Glock (12 of 34 makers)",
    last_run_at: ago(60 * 14),
    last_status: "ok",
    last_summary: "Read 114 model(s): 0 variant(s) proposed.",
    last_seconds: 1446,
  },
  {
    name: "pages",
    requested_at: null,
    started_at: null,
    progress: null,
    last_run_at: ago(60 * 24),
    last_status: "warning",
    last_summary: "Asked about 40 model(s). 2 maker site(s) could not be read.",
    last_seconds: 312.4,
  },
  {
    name: "barrels",
    requested_at: ago(1),
    started_at: null,
    progress: null,
    last_run_at: null,
    last_status: null,
    last_summary: null,
    last_seconds: null,
  },
];

test("each job says whether it is running, and how its last run went", async ({
  signedIn,
}) => {
  let asked = 0;
  await signedIn.route(/\/api\/manufacturer-data$/, (route) => {
    asked += 1;
    // The second look finds the run finished.
    const rows =
      asked < 3
        ? JOBS
        : JOBS.map((row) =>
            row.name === "variants"
              ? {
                  ...row,
                  started_at: null,
                  progress: null,
                  last_run_at: ago(0),
                  last_status: "ok",
                }
              : row,
          );
    return route.fulfill({ json: rows });
  });
  await signedIn.route(/\/api\/ammunition\/settings$/, (route) =>
    route.fulfill({
      json: {
        refresh_days: 7,
        choices: { 1: "Daily", 7: "Weekly", 14: "Every 2 weeks" },
        requested_at: null,
        requested_parts: null,
        last_run_at: ago(90),
        last_parts: "wikipedia,reloading,prices",
        last_full_at: ago(90),
        last_status: "interrupted",
        last_error: null,
        last_summary: "Interrupted: the service restarted during the refresh.",
        last_seconds: 61,
        started_at: null,
        progress: null,
      },
    }),
  );
  await signedIn.clock.install({ time: now });
  await openPage(signedIn, "Site settings");

  const variants = signedIn.getByTestId("manufacturer-job-variants");
  await expect(variants.getByTestId("job-status")).toContainText(
    "Running since 40 minutes ago: Bud's Gun Shop: Glock (12 of 34 makers)",
  );
  await expect(variants.getByRole("button", { name: "Running" })).toBeDisabled();
  await expect(variants.getByTestId("job-status")).toContainText("took 24m 6s");
  await expect(variants.locator(".chip--success")).toHaveText("Success");

  const pages = signedIn.getByTestId("manufacturer-job-pages");
  await expect(pages.locator(".chip--warning")).toHaveText("Warning");
  await expect(pages).toContainText("2 maker site(s) could not be read.");

  const barrels = signedIn.getByTestId("manufacturer-job-barrels");
  await expect(barrels).toContainText("Waiting to start");
  await expect(barrels).toContainText("Not run yet.");

  await expect(signedIn.getByTestId("caliber-data-last").locator(".chip")).toHaveText(
    "Interrupted",
  );

  // While something runs the page looks again by itself.
  await signedIn.clock.runFor(31000);
  await expect(variants.getByText("Running")).toHaveCount(0);
  await expect(
    variants.getByRole("button", { name: "Update MSRPs and variants" }),
  ).toBeEnabled();
});
