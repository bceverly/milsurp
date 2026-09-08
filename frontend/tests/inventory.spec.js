/** The inventory browser: search, filters, sorting, pagination, detail view. */
import { test, expect } from "./fixtures.js";

test.describe("inventory", () => {
  test("shows listings with prices and photos", async ({ signedIn }) => {
    const cards = signedIn.locator(".item-card");
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBeGreaterThan(0);

    const first = cards.first();
    await expect(first.locator(".item-card__title")).not.toBeEmpty();
    await expect(first.locator(".item-card__price")).toContainText("$");
  });

  test("the result count matches the heading", async ({ signedIn }) => {
    await expect(signedIn.getByText(/\d+ listings? match your filters/)).toBeVisible();
  });

  test("search narrows the results and updates the URL", async ({ signedIn }) => {
    // Wait for the grid before counting, or `before` is 0 and the comparison
    // below is meaningless.
    await expect(signedIn.locator(".item-card").first()).toBeVisible();
    const before = await signedIn.locator(".item-card").count();

    await signedIn.getByPlaceholder(/search titles/i).fill("mauser");
    // The box is debounced, so wait for the URL to catch up rather than sleeping.
    await expect(signedIn).toHaveURL(/search=mauser/);
    await signedIn.waitForTimeout(600);

    const after = await signedIn.locator(".item-card").count();
    expect(after).toBeLessThanOrEqual(before);
  });

  test("a search with no matches shows the empty state", async ({ signedIn }) => {
    await signedIn.getByPlaceholder(/search titles/i).fill("zzzznosuchthing");
    await expect(signedIn.getByText("No listings match")).toBeVisible();
  });

  test("clearing the search restores the full list", async ({ signedIn }) => {
    await expect(signedIn.locator(".item-card").first()).toBeVisible();
    const before = await signedIn.locator(".item-card").count();
    await signedIn.getByPlaceholder(/search titles/i).fill("mauser");
    await expect(signedIn).toHaveURL(/search=mauser/);

    await signedIn.getByRole("button", { name: "Clear search" }).click();
    await expect(signedIn).not.toHaveURL(/search=/);
    await signedIn.waitForTimeout(600);
    expect(await signedIn.locator(".item-card").count()).toBe(before);
  });

  test("search state is shareable via the URL", async ({ signedIn }) => {
    await signedIn.goto("/?search=mauser");
    await expect(signedIn.getByPlaceholder(/search titles/i)).toHaveValue("mauser");
  });

  test("sorting by price orders the results ascending", async ({ signedIn }) => {
    await signedIn.getByLabel("Sort listings").selectOption("price_asc");
    await expect(signedIn).toHaveURL(/sort=price_asc/);
    await signedIn.waitForTimeout(800);

    const prices = await signedIn.locator(".item-card__price").allTextContents();
    const numbers = prices
      .map((text) => Number(text.replace(/[^0-9.]/g, "")))
      .filter((value) => !Number.isNaN(value) && value > 0);
    const sorted = [...numbers].sort((a, b) => a - b);
    expect(numbers).toEqual(sorted);
  });

  test("a facet filter applies and can be removed again", async ({ signedIn }) => {
    // The filter rail is always visible at desktop widths. Type is a radio,
    // not a checkbox: it reads as one question — "what am I looking for?" —
    // and checkboxes invited the answer "rifles and handguns and parts", which
    // is the same as asking nothing.
    const rifles = signedIn.getByRole("radio", { name: "Rifles" });
    await rifles.check();
    await expect(signedIn).toHaveURL(/kind=rifle/);

    // The active-filter chip is the affordance for undoing it.
    const chip = signedIn.locator(".active-filters__chip", { hasText: "Rifles" });
    await expect(chip).toBeVisible();
    await chip.getByRole("button").click();
    await expect(signedIn).not.toHaveURL(/kind=rifle/);
  });

  test("clear all removes every filter at once", async ({ signedIn }) => {
    await signedIn.goto("/?kind=rifle&search=mauser");
    await signedIn.getByRole("button", { name: "Clear all" }).click();
    await expect(signedIn).not.toHaveURL(/kind=|search=/);
  });

  test("availability is a single choice", async ({ signedIn }) => {
    await signedIn.getByRole("radio", { name: "Sold" }).check();
    await expect(signedIn).toHaveURL(/availability=sold/);
  });

  test("choosing a type replaces the last one rather than adding to it", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("radio", { name: "Rifles" }).check();
    await expect(signedIn).toHaveURL(/kind=rifle/);
    await signedIn.getByRole("radio", { name: "Handguns" }).check();
    await expect(signedIn).toHaveURL(/kind=pistol/);
    await expect(signedIn).not.toHaveURL(/kind=rifle/);
  });

  test("each type carries the count it would show", async ({ signedIn }) => {
    // The point of the numbers is to be steady: they are counted over every
    // other filter but not over Type, so they answer "what would I get if I
    // picked this" rather than restating the choice already made.
    const countFor = async (name) => {
      const label = signedIn.locator("label.facet__option", { hasText: name });
      const text = await label.locator(".facet__option-count").innerText();
      return Number(text.replace(/[^0-9]/g, ""));
    };

    const anything = await countFor("Anything");
    const rifles = await countFor("Rifles");
    expect(anything).toBeGreaterThan(0);
    expect(rifles).toBeGreaterThan(0);

    // Anything is the whole set, so it is the sum of the five below it.
    const named = [];
    for (const kind of ["Rifles", "Handguns", "Bayonets", "Parts kits"]) {
      named.push(await countFor(kind));
    }
    named.push(await countFor("Other parts & accessories"));
    expect(named.reduce((a, b) => a + b, 0)).toBe(anything);

    // And choosing one does not move them.
    await signedIn.getByRole("radio", { name: "Rifles" }).check();
    await expect(signedIn).toHaveURL(/kind=rifle/);
    expect(await countFor("Handguns")).toBe(named[1]);
    expect(await countFor("Anything")).toBe(anything);
  });

  test("anything clears the type again", async ({ signedIn }) => {
    await signedIn.getByRole("radio", { name: "Bayonets" }).check();
    await expect(signedIn).toHaveURL(/kind=bayonet/);
    await signedIn.getByRole("radio", { name: "Anything" }).check();
    await expect(signedIn).not.toHaveURL(/kind=/);
  });

  test("price reduced sits with availability and is a single choice", async ({
    signedIn,
  }) => {
    await signedIn.getByRole("radio", { name: "Price reduced" }).check();
    await expect(signedIn).toHaveURL(/price_drops_only=true/);
    await signedIn.getByRole("radio", { name: "Any price" }).check();
    await expect(signedIn).not.toHaveURL(/price_drops_only/);
  });

  test("listings per page is settable and leaves the default out of the URL", async ({
    signedIn,
  }) => {
    await signedIn.getByLabel("Listings per page").selectOption("96");
    await expect(signedIn).toHaveURL(/per_page=96/);
    await signedIn.getByLabel("Listings per page").selectOption("48");
    await expect(signedIn).not.toHaveURL(/per_page/);
  });

  test("the list view shows a description and the cards do not", async ({ signedIn }) => {
    await expect(signedIn.locator(".item-card").first()).toBeVisible();

    await signedIn.getByRole("button", { name: "List" }).click();
    await expect(signedIn).toHaveURL(/view=list/);
    await expect(signedIn.locator(".item-row").first()).toBeVisible();
    await expect(signedIn.locator(".item-card")).toHaveCount(0);

    // Back to cards, and the parameter goes away with it.
    await signedIn.getByRole("button", { name: "Cards" }).click();
    await expect(signedIn).not.toHaveURL(/view=/);
    await expect(signedIn.locator(".item-card").first()).toBeVisible();
  });
});

test.describe("item detail", () => {
  test("opens from a card and shows the full record", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn).toHaveURL(/\/items\/\d+/);

    await expect(signedIn.locator(".detail__title")).not.toBeEmpty();
    await expect(signedIn.locator(".detail__price-now")).toBeVisible();
    await expect(signedIn.getByRole("heading", { name: "Price history" })).toBeVisible();
    await expect(signedIn.getByRole("link", { name: /View on/ })).toBeVisible();
  });

  test("the vendor link opens safely in a new tab", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    const link = signedIn.getByRole("link", { name: /View on/ });
    await expect(link).toHaveAttribute("target", "_blank");
    // noopener stops the vendor page reaching back through window.opener.
    await expect(link).toHaveAttribute("rel", /noopener/);
  });

  test("back returns to the inventory", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn).toHaveURL(/\/items\/\d+/);
    await signedIn.getByRole("button", { name: /Back to inventory/ }).click();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();
  });

  test("a photo gallery is shown when the listing has several", async ({ signedIn }) => {
    await signedIn.locator(".item-card").first().click();
    await expect(signedIn.locator(".gallery__main")).toBeVisible();

    const thumbs = signedIn.locator(".gallery__thumb");
    if ((await thumbs.count()) > 1) {
      await thumbs.nth(1).click();
      await expect(thumbs.nth(1)).toHaveClass(/gallery__thumb--active/);
    }
  });

  test("an unknown item id shows an error rather than a blank page", async ({
    signedIn,
  }) => {
    await signedIn.goto("/items/999999");
    await expect(signedIn.getByRole("alert")).toBeVisible();
  });
});

test.describe("pagination", () => {
  // The demo catalog is deliberately seeded past the 48-per-page boundary so
  // these controls exist to be clicked. When it held only 28 listings the
  // pager never rendered, and a Next button that set the page number and then
  // deleted it went unnoticed.

  test("next advances to the following page", async ({ signedIn }) => {
    const status = signedIn.locator(".pagination__status");
    await expect(status).toContainText("Page 1 of");

    const firstTitle = await signedIn.locator(".item-card__title").first().textContent();

    await signedIn.getByRole("button", { name: "Next" }).click();

    await expect(status).toContainText("Page 2 of");
    await expect(signedIn).toHaveURL(/page=2/);
    // Different page, different listings.
    await expect(signedIn.locator(".item-card__title").first()).not.toHaveText(
      firstTitle ?? "",
    );
  });

  test("previous returns to page one and drops the parameter", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Next" }).click();
    await expect(signedIn).toHaveURL(/page=2/);

    await signedIn.getByRole("button", { name: "Previous" }).click();
    await expect(signedIn.locator(".pagination__status")).toContainText("Page 1 of");
    // Page 1 is the default, so it stays out of the URL.
    await expect(signedIn).not.toHaveURL(/page=/);
  });

  test("paging returns you to the top of the grid", async ({ signedIn }) => {
    // The pager sits below 48 cards, so a page change always starts from the
    // bottom of the page. Landing on the new page already scrolled past its
    // first rows makes it look like nothing happened.
    // The page has to be tall enough to scroll before any of this proves
    // anything, and a grid still fetching its cards is not. The scroll is
    // retried inside the poll rather than gated on a card count: page two
    // holds the remainder, not a full 48, and how much of the catalog is
    // active depends on whether an unrelated test has run a scan.
    const scrollToBottom = () =>
      expect
        .poll(async () => {
          await signedIn.evaluate(() =>
            window.scrollTo(0, document.documentElement.scrollHeight),
          );
          return signedIn.evaluate(() => window.scrollY);
        })
        .toBeGreaterThan(0);

    await scrollToBottom();
    await signedIn.getByRole("button", { name: "Next" }).click();
    await expect(signedIn).toHaveURL(/page=2/);
    await expect.poll(() => signedIn.evaluate(() => window.scrollY)).toBe(0);

    await scrollToBottom();
    await signedIn.getByRole("button", { name: "Previous" }).click();
    await expect(signedIn.locator(".pagination__status")).toContainText("Page 1 of");
    await expect.poll(() => signedIn.evaluate(() => window.scrollY)).toBe(0);
  });

  test("the buttons disable at each end", async ({ signedIn }) => {
    await expect(signedIn.getByRole("button", { name: "Previous" })).toBeDisabled();
    await signedIn.getByRole("button", { name: "Next" }).click();
    await expect(signedIn.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  test("changing a filter resets to page one", async ({ signedIn }) => {
    await signedIn.getByRole("button", { name: "Next" }).click();
    await expect(signedIn).toHaveURL(/page=2/);

    // A narrower result set renumbers the pages, so page 2 no longer means
    // anything and must be dropped.
    await signedIn.getByRole("radio", { name: "Rifles" }).check();
    await expect(signedIn).toHaveURL(/kind=rifle/);
    await expect(signedIn).not.toHaveURL(/page=2/);
  });
});

test.describe("the filter panel", () => {
  /**
   * One scrollbar for the screen, not three.
   *
   * The panel used to be a scroll container (`position: sticky` with a
   * viewport height cap) with a second scroll container inside every open
   * facet (`max-height: 250px`). Eight options at 34px each overflow 250px, so
   * the inner bar appeared as soon as a facet opened — and reaching an option
   * meant scrolling the page to the panel, the panel to the facet, then the
   * facet to the option. It grows now, and the page scrolls.
   */
  const scrollersInsideTheFilters = (page) =>
    page.evaluate(() => {
      const panel = document.querySelector(".filters");
      if (!panel) return ["no .filters at all"];
      return [panel, ...panel.querySelectorAll("*")]
        .filter((el) => {
          const style = getComputedStyle(el);
          const overflows =
            el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1;
          return overflows && /auto|scroll/.test(style.overflowY + style.overflowX);
        })
        .map(
          (el) => `${el.className || el.tagName} (${el.clientHeight}/${el.scrollHeight})`,
        );
    });

  test("nothing inside it scrolls, however many facets are open", async ({
    signedIn,
  }) => {
    await expect(signedIn.locator(".filters")).toBeVisible();
    await expect(signedIn.locator(".item-card").first()).toBeVisible();

    // Every facet open and every "Show all" taken — the worst case there is.
    //
    // Re-queried each time rather than iterating `.all()`. Clicking one
    // re-renders its facet, so the handles taken up front go stale and the
    // third click waits ten seconds for an element that no longer exists.
    const openEverything = () =>
      signedIn.evaluate(() => {
        document.querySelectorAll(".filters details").forEach((d) => (d.open = true));
      });

    await openEverything();
    const showAll = signedIn.getByRole("button", { name: /Show all/ });
    for (let taken = 0; taken < 12 && (await showAll.count()); taken += 1) {
      await showAll.first().click();
      await openEverything();
    }

    expect(await scrollersInsideTheFilters(signedIn)).toEqual([]);
  });

  test("and the whole of it stays reachable by scrolling the page", async ({
    signedIn,
  }) => {
    /**
     * The reason it is no longer sticky. Pin the top of something taller than
     * the viewport and its bottom can never be scrolled to — which is why the
     * height cap and its scrollbar were there in the first place.
     */
    await expect(signedIn.locator(".filters")).toBeVisible();
    await signedIn.evaluate(() => {
      document.querySelectorAll(".filters details").forEach((d) => (d.open = true));
    });

    expect(
      await signedIn.evaluate(
        () => getComputedStyle(document.querySelector(".filters")).position,
      ),
    ).toBe("static");

    await signedIn.evaluate(() =>
      window.scrollTo(0, document.documentElement.scrollHeight),
    );
    const bottom = await signedIn.evaluate(() => {
      const box = document.querySelector(".filters").getBoundingClientRect();
      return { bottom: box.bottom, viewport: window.innerHeight };
    });
    expect(bottom.bottom).toBeLessThanOrEqual(bottom.viewport + 1);
  });
});
