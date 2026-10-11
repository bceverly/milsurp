/**
 * Wikipedia for makers and models: proposed articles decided on the Armory
 * page, and one click from a listing to the maker's and the model's article.
 * Which articles are proposed is the server's business (app/services/wikipedia);
 * these check the page shows and sends what it should.
 */
import { test, expect, openPage } from "./fixtures.js";

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

test("proposed articles are accepted and rejected on the Armory page", async ({
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
  const panel = signedIn.getByTestId("wikipedia-suggestions");
  await expect(panel).toContainText("Mauser");
  await expect(panel.getByRole("link", { name: "Gewehr 98" })).toHaveAttribute(
    "href",
    "https://en.wikipedia.org/wiki/Gewehr_98",
  );

  await panel.getByRole("button", { name: "Accept all confident (1)" }).click();
  await expect(panel).not.toContainText("Mauser");
  await panel.getByRole("button", { name: "Reject Gewehr 98 for Karabiner 98k" }).click();
  await expect(signedIn.getByTestId("wikipedia-suggestions")).toHaveCount(0);
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
