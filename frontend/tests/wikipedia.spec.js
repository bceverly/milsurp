/**
 * Wikipedia for makers, models and calibers: proposed articles decided on the
 * Armory's Wikipedia tab, and one click from a listing to the maker's and the model's article.
 * Which articles are proposed is the server's business (app/services/wikipedia);
 * these check the page shows and sends what it should.
 */
import { test, expect, openPage } from "./fixtures.js";
import { addModel, openArmoryModels, searchFor } from "./armory-helpers.js";

const PROPOSALS = [
  {
    id: 1,
    target_type: "manufacturer",
    target_id: 7,
    target_name: "Mauser",
    url: "https://en.wikipedia.org/wiki/Mauser",
    title: "Mauser",
    confident: true,
    reason: "title matches; in Category:Firearm manufacturers of Germany",
  },
  {
    id: 2,
    target_type: "model",
    target_id: 9,
    target_name: "Karabiner 98k",
    url: "https://en.wikipedia.org/wiki/Gewehr_98",
    title: "Gewehr 98",
    confident: false,
    reason: "in Category:Bolt-action rifles",
  },
];

test("proposed articles are accepted and rejected on the Armory's Wikipedia tab", async ({
  signedIn,
}) => {
  let remaining = [...PROPOSALS];
  const sent = [];
  await signedIn.route("**/api/armory/references**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({ json: remaining });
      return;
    }
    const path = new URL(request.url()).pathname;
    sent.push([path, request.postDataJSON?.() ?? null]);
    if (path.endsWith("/accept-confident"))
      remaining = remaining.filter((p) => !p.confident);
    else
      remaining = remaining.filter(
        (p) => !(request.postDataJSON()?.ids || []).includes(p.id),
      );
    await route.fulfill({ json: { changed: 1, message: "ok" } });
  });
  await openPage(signedIn, "Armory");
  // A tab of their own since 2026-10-12, saying how many are waiting; not a
  // panel above every tab.
  await expect(signedIn.getByTestId("wikipedia-suggestions")).toHaveCount(0);
  await signedIn.getByRole("tab", { name: "Wikipedia (2)" }).click();
  await expect(signedIn).toHaveURL(/#wikipedia$/);
  const panel = signedIn.getByTestId("wikipedia-suggestions");
  await expect(panel).toContainText("Mauser");
  // Showing picks which decisions to look at (2026-10-13); Search narrows them.
  await expect(signedIn.getByLabel("Showing")).toHaveValue("pending");
  await signedIn.getByLabel("Search").fill("gewehr");
  await expect(panel).not.toContainText("Mauser");
  await expect(panel).toContainText("Karabiner 98k");
  await signedIn.getByLabel("Search").fill("");
  await expect(panel).toContainText("Mauser");
  await expect(panel.getByRole("link", { name: "Gewehr 98" })).toHaveAttribute(
    "href",
    "https://en.wikipedia.org/wiki/Gewehr_98",
  );

  await panel.getByRole("button", { name: "Accept all confident (1)" }).click();
  await expect(panel).not.toContainText("Mauser");
  await panel.getByRole("button", { name: "Reject Gewehr 98 for Karabiner 98k" }).click();
  await expect(panel).toContainText("No suggestions waiting.");
  await expect(
    signedIn.getByRole("tab", { name: "Wikipedia", exact: true }),
  ).toBeVisible();
  expect(sent.map(([path]) => path)).toEqual([
    "/api/armory/references/accept-confident",
    "/api/armory/references/reject",
  ]);
  expect(sent[1][1]).toEqual({ ids: [2] });
});

test("a listing links its maker and its model to Wikipedia", async ({ signedIn }) => {
  await signedIn.route(/\/api\/items\/\d+$/, async (route) => {
    const response = await route.fetch();
    const item = await response.json();
    item.model = item.model || "Karabiner 98k";
    item.firearm_model_id = item.firearm_model_id || 1;
    item.manufacturer = "Mauser";
    item.model_reference_url = "https://en.wikipedia.org/wiki/Karabiner_98k";
    item.maker_wikipedia_url = "https://en.wikipedia.org/wiki/Mauser";
    await route.fulfill({ response, json: item });
  });
  await signedIn.goto("/?availability=all");
  await signedIn.locator(".item-card").first().click();
  await expect(signedIn.locator(".detail__facts")).toBeVisible();
  await expect(
    signedIn.getByRole("link", { name: "Mauser on Wikipedia" }),
  ).toHaveAttribute("href", "https://en.wikipedia.org/wiki/Mauser");
  await expect(signedIn.getByRole("link", { name: /on Wikipedia$/ })).toHaveCount(2);
});

test("a model's page on its maker's site is decided on its own tab", async ({
  signedIn,
}) => {
  const rows = [
    {
      id: 7,
      field: "maker_page",
      target_type: "model",
      target_id: 3,
      target_name: "Glock 19",
      url: "https://us.glock.com/en/products/commercial-firearms/pistols/g19-v",
      title: "g19-v",
      confident: true,
      reason: "in the maker's sitemap: /en/products/commercial-firearms/pistols/g19-v",
    },
    { ...PROPOSALS[0], field: "wikipedia" },
  ];
  const sent = [];
  await signedIn.route("**/api/armory/references**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({ json: rows });
      return;
    }
    sent.push(request.url());
    await route.fulfill({ json: { changed: 1, message: "ok" } });
  });
  await openPage(signedIn, "Armory");
  await signedIn.getByRole("tab", { name: "Manufacturer pages (1)" }).click();
  await expect(signedIn).toHaveURL(/#manufacturer-pages$/);
  const panel = signedIn.getByTestId("maker-page-suggestions");
  await expect(panel).toContainText("Glock 19");
  // Each tab its own kind: the Wikipedia article is not here.
  await expect(panel).not.toContainText("Mauser");
  await panel.getByRole("button", { name: "Accept all confident (1)" }).click();
  await expect.poll(() => sent[0]).toContain("accept-confident?field=maker_page");
});

test("a Wikipedia article is added, edited and removed by hand under Production", async ({
  signedIn,
}) => {
  await openArmoryModels(signedIn);
  const name = `Wiki Test ${Date.now()}`;
  await addModel(signedIn, name);
  await searchFor(signedIn, name);
  await signedIn.locator("tbody tr", { hasText: name }).getByRole("checkbox").check();
  await signedIn.getByRole("button", { name: "Promote to production" }).click();
  await expect(signedIn.locator(".alert--success")).toContainText(
    "moved into production",
  );
  await signedIn.getByLabel("Search").fill("");

  await signedIn.getByRole("tab", { name: /^Wikipedia/ }).click();
  await signedIn.getByLabel("Showing").selectOption("approved");
  const production = signedIn.getByTestId("wikipedia-production");
  // Exactly: "For" is also inside every row's "Edit the article for …",
  // and the shipped armory has carried production's articles since
  // 2026-10-13 -- 173 of them matched.
  await production.getByLabel("For", { exact: true }).fill(`${name} (Model)`);
  await production
    .getByLabel("Wikipedia article")
    .fill("https://en.wikipedia.org/wiki/First");
  await production.getByRole("button", { name: "Add Wikipedia article" }).click();
  await signedIn.getByLabel("Search").fill(name);
  const listed = production.locator("tbody tr", { hasText: name });
  await expect(listed.getByRole("link")).toHaveAttribute(
    "href",
    "https://en.wikipedia.org/wiki/First",
  );
  await expect(listed).toContainText("Model");

  await listed.getByRole("button", { name: `Edit the article for ${name}` }).click();
  await listed
    .getByLabel(`Wikipedia article for ${name}`)
    .fill("https://en.wikipedia.org/wiki/Second");
  await listed.getByRole("button", { name: "Save" }).click();
  await expect(listed.getByRole("link")).toHaveAttribute(
    "href",
    "https://en.wikipedia.org/wiki/Second",
  );
  await listed.getByRole("button", { name: `Remove the article for ${name}` }).click();
  await expect(production.locator("tbody tr", { hasText: name })).toHaveCount(0);

  // Leave the armory as found.
  await signedIn.getByRole("tab", { name: "Models" }).click();
  await signedIn.getByLabel("Showing").selectOption("");
  await searchFor(signedIn, name);
  await signedIn.getByRole("button", { name: `Delete ${name}` }).click();
  await signedIn
    .getByRole("dialog")
    .getByRole("button", { name: /^Delete/ })
    .click();
  await expect(signedIn.locator("tbody tr", { hasText: name })).toHaveCount(0);
});
