/**
 * Capture the README screenshots with Playwright.
 *
 * Driven by scripts/screenshots.sh, which starts the app and passes the URL and
 * credentials through the environment. Output lands in marketing/images/.
 *
 * Deterministic on purpose: the app is driven to a known state before each
 * shot, so re-running produces comparable images rather than whatever happened
 * to be on screen.
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.env.MILSURP_URL || "http://127.0.0.1:8730";
const USER = process.env.MILSURP_USER || "admin";
const PASS = process.env.MILSURP_PASSWORD || "";
const OUT = resolve(process.env.MILSURP_SHOTS || "../marketing/images");

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

mkdirSync(OUT, { recursive: true });

const failures = [];

async function shot(page, name) {
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log(`  ✓ ${name}.png`);
}

async function signIn(page) {
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForSelector('input[name="username"]', { timeout: 15000 });
  await page.fill('input[name="username"]', USER);
  await page.fill('input[name="password"]', PASS);
  await page.click('button[type="submit"]');
  await page.waitForSelector('h1:has-text("Inventory")', { timeout: 20000 });
  // Photos are fetched one at a time through the authenticated endpoint, so
  // networkidle alone is not enough - give the grid a moment to fill in.
  await page.waitForTimeout(3000);
}

const browser = await chromium.launch({ args: ["--no-sandbox"] });

try {
  const context = await browser.newContext({
    viewport: DESKTOP,
    deviceScaleFactor: 2, // retina-quality images for the README
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => failures.push(`pageerror: ${error.message}`));

  console.log("Capturing desktop views…");

  // 1. Sign-in screen.
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForSelector('input[name="username"]');
  await shot(page, "screenshot-login");

  // 2. Inventory browser.
  await signIn(page);
  await shot(page, "screenshot-inventory");

  // 3. Item detail, with its gallery and price history.
  const cards = await page.locator(".item-card").count();
  if (cards > 0) {
    await page.locator(".item-card").first().click();
    await page.waitForSelector(".detail", { timeout: 15000 });
    await page.waitForTimeout(2500);
    await shot(page, "screenshot-item-detail");
  } else {
    failures.push(
      "no listings in the database - run 'make scan' before 'make screenshots'",
    );
  }

  // 4. Site administration.
  await page.goto(`${BASE}/sites`, { waitUntil: "networkidle" });
  await page.waitForSelector('h1:has-text("Sites")', { timeout: 15000 });
  await page.waitForTimeout(1200);
  await shot(page, "screenshot-sites");

  // 5. Email digest settings.
  await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
  await page.waitForSelector('h1:has-text("Email digest")', { timeout: 15000 });
  await page.waitForTimeout(1000);
  await shot(page, "screenshot-settings");

  // Mobile, to show the responsive layout.
  console.log("Capturing mobile views…");
  const mobileContext = await browser.newContext({
    viewport: MOBILE,
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  });
  const mobile = await mobileContext.newPage();
  mobile.on("pageerror", (error) => failures.push(`mobile pageerror: ${error.message}`));

  await signIn(mobile);
  await shot(mobile, "screenshot-mobile");
} finally {
  await browser.close();
}

if (failures.length) {
  console.error("\nProblems encountered:");
  failures.forEach((line) => console.error(`  ! ${line}`));
  process.exit(1);
}

console.log(`\nScreenshots written to ${OUT}`);
