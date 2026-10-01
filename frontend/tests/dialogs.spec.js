/**
 * Every dialog keeps its title and its buttons on screen.
 *
 * A dialog used to be one scrolling box, so a tall one carried its Save button
 * below the bottom of the window -- the collection's Add dialog on a laptop,
 * the armory's model form almost anywhere -- and nothing on screen said the
 * button was there. The head and the actions are pinned now and only the body
 * scrolls; these hold that in a window short enough to make every one of
 * these dialogs taller than it.
 *
 * Desktop only, at a short laptop height. The phone's bottom sheet has its own
 * test in responsive.spec.js.
 */
import { test, expect } from "./fixtures.js";

const SHORT = { width: 1280, height: 560 };

/** Wholly inside the window: not clipped at the top and not off the bottom. */
async function expectOnScreen(page, locator) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  const height = page.viewportSize().height;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(height);
}

async function expectDialogFits(page, actionName) {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expectOnScreen(page, dialog.locator(".modal__head"));
  await expectOnScreen(page, dialog.getByRole("button", { name: actionName }).last());
}

test.describe("dialogs in a short window", () => {
  test.beforeEach(async ({ signedIn }) => {
    await signedIn.setViewportSize(SHORT);
  });

  test("adding a gun to the collection", async ({ signedIn }) => {
    await signedIn.goto("/collection");
    await signedIn.getByRole("button", { name: "Add a gun" }).click();
    await expectDialogFits(signedIn, "Save");
  });

  test("an armory model, whose form brings its own buttons", async ({ signedIn }) => {
    await signedIn.goto("/armory#model");
    await signedIn.getByRole("button", { name: "Add model" }).first().click();
    await expectDialogFits(signedIn, "Add, awaiting approval");
  });

  test("adding a user", async ({ signedIn }) => {
    await signedIn.goto("/users");
    await signedIn.getByRole("button", { name: "Add user" }).click();
    await expectDialogFits(signedIn, "Save");
  });

  test("a classification rule", async ({ signedIn }) => {
    await signedIn.goto("/classification");
    await signedIn.getByRole("tab", { name: "Caliber designations" }).click();
    await signedIn.getByRole("button", { name: "Add designation" }).click();
    await expectDialogFits(signedIn, "Save");
  });

  test("the body scrolls and the buttons stay where they are", async ({ signedIn }) => {
    await signedIn.goto("/collection");
    await signedIn.getByRole("button", { name: "Add a gun" }).click();
    const dialog = signedIn.getByRole("dialog");
    const body = dialog.locator(".modal__body");
    const save = dialog.getByRole("button", { name: "Save" });
    const before = await save.boundingBox();
    await body.evaluate((element) => element.scrollTo(0, element.scrollHeight));
    expect((await save.boundingBox()).y).toBe(before.y);
    await expect(dialog.getByLabel("Notes")).toBeInViewport();
  });
});
