/**
 * The classification page: countries, caliber designations, accessory words.
 *
 * The behavior worth pinning down is that an edit here *reaches the
 * classifier*. These three lists are process-wide caches, so a page that saves
 * correctly and changes nothing is exactly the bug this feature can have — and
 * from the browser the only visible half of that is the round trip, so the
 * round trip is what these tests hold.
 */
import { test, expect } from "./fixtures.js";

test.describe("classification", () => {
  test.beforeEach(async ({ signedIn }) => {
    // Straight to the page rather than through the nav link. Nine tests do
    // not each need to prove the link works -- admin.spec.js's reachability
    // test is where that belongs, and it now names Classification -- and a
    // click made while the app is still settling can be swallowed, which is
    // a failure in every one of these tests with a cause in none of them.
    await signedIn.goto("/classification");
    await expect(signedIn.getByRole("heading", { name: "Classification" })).toBeVisible();
  });

  test("opens on the countries the migration seeded", async ({ signedIn }) => {
    await expect(signedIn.getByRole("tab", { name: "Countries" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const rows = signedIn.locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    await expect(
      signedIn.getByRole("cell", { name: "Germany", exact: true }),
    ).toBeVisible();
  });

  test("searching narrows the list", async ({ signedIn }) => {
    await expect(signedIn.locator("tbody tr")).not.toHaveCount(1);
    await signedIn.getByLabel("Search").fill("Ishapore");
    await expect(signedIn.locator("tbody tr")).toHaveCount(1);
    await expect(
      signedIn.getByRole("cell", { name: "India", exact: true }),
    ).toBeVisible();
  });

  test("a country's spellings can be edited and come back", async ({ signedIn }) => {
    await signedIn.getByLabel("Search").fill("Finland");
    const row = signedIn.locator("tbody tr").first();
    await row.getByRole("button", { name: "Edit" }).click();

    const spellings = signedIn.getByLabel("Spellings");
    await expect(spellings).toHaveValue(/Finnish/);
    await spellings.fill("Finn\nFinnish\nFinland");
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();

    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    await expect(row.getByText("Finland", { exact: true }).last()).toBeVisible();
  });

  test("a rule can be switched off from the table", async ({ signedIn }) => {
    await signedIn.getByLabel("Search").fill("Sweden");
    const row = signedIn.locator("tbody tr").first();
    const toggle = row.getByRole("button", { name: /^(On|Off)$/ });
    await expect(toggle).toHaveText("On");
    await toggle.click();
    await expect(row.getByRole("button", { name: /^(On|Off)$/ })).toHaveText("Off");
  });

  test("the designations tab shows the order the rules are tried in", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("tab", { name: "Caliber designations" }).click();
    await expect(signedIn.getByRole("columnheader", { name: "Order" })).toBeVisible();
    await expect(
      signedIn.getByRole("columnheader", { name: "Also needs" }),
    ).toBeVisible();

    const positions = await signedIn.locator("tbody tr td:first-child").allInnerTexts();
    const numbers = positions.map(Number);
    expect(numbers).toEqual([...numbers].sort((a, b) => a - b));
  });

  test("a designation can be added and is refused without a caliber", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("tab", { name: "Caliber designations" }).click();
    await signedIn.getByRole("button", { name: "Add designation" }).click();

    // The browser's own required-field check, not ours: an empty form must
    // not reach the API at all.
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();
    await expect(signedIn.getByRole("dialog")).toBeVisible();

    await signedIn.getByLabel("Caliber").fill(".577/450");
    await signedIn.getByLabel("Designations").fill("martini henry");
    await signedIn.getByLabel("Position").fill("1");
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();

    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    await signedIn.getByLabel("Search").fill("martini");
    await expect(
      signedIn.getByRole("cell", { name: ".577/450", exact: true }),
    ).toBeVisible();
  });

  test("the part-or-gun tab names its three lists in reading order", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("tab", { name: "Part or gun" }).click();
    // The order the classifier reads them in *is* the rule, so it is said on
    // the page rather than left to be inferred from however the table happens
    // to be sorted.
    const listed = await signedIn.locator(".classify-order li strong").allInnerTexts();
    expect(listed).toEqual(["Sold with a gun", "Names a gun", "Names a part"]);

    // Each list compiles to one alternation, so there is nothing for a
    // position to decide and nothing on screen should suggest otherwise.
    await expect(signedIn.getByRole("columnheader", { name: "Order" })).toHaveCount(0);
    await expect(signedIn.getByLabel("Search")).toHaveCount(0);
    await expect(
      signedIn.getByRole("cell", { name: "bayonet", exact: true }),
    ).toBeVisible();
    await expect(
      signedIn.getByRole("row", { name: /scope/ }).getByText("any word ending in it"),
    ).toBeVisible();
  });

  test("a word can be added to a veto list", async ({ signedIn }) => {
    await signedIn.getByRole("tab", { name: "Part or gun" }).click();
    await signedIn.getByRole("button", { name: "Add word" }).click();
    // Exact: the Enabled switch's hint says "Listings it already labeled…",
    // and a substring label match finds that checkbox too.
    await signedIn.getByLabel("List", { exact: true }).selectOption("firearm");
    await signedIn.getByLabel("Word or phrase").fill("vetterli");
    await signedIn.getByLabel("How to match it").selectOption("substring");
    await signedIn.getByRole("button", { name: "Save", exact: true }).click();

    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    const row = signedIn.getByRole("row", { name: /vetterli/ });
    await expect(row.getByText("Names a gun")).toBeVisible();
    await expect(row.getByText("anywhere in the title")).toBeVisible();
  });

  test("deleting says what it does and does not do", async ({ signedIn }) => {
    await signedIn.getByRole("tab", { name: "Part or gun" }).click();
    const row = signedIn.getByRole("row", { name: /helmet/ }).first();
    await row.getByRole("button", { name: "Delete word" }).click();

    const dialog = signedIn.getByRole("dialog");
    await expect(dialog).toContainText("not the answer itself");
    await dialog.getByRole("button", { name: "Delete permanently" }).click();

    await expect(signedIn.getByRole("dialog")).toHaveCount(0);
    await expect(signedIn.getByRole("cell", { name: "helmet", exact: true })).toHaveCount(
      0,
    );
  });
});
