/**
 * Two-factor authentication and password reset links, end to end.
 *
 * The backend tests cover the arithmetic and the exchange. These cover the
 * part a person meets: that turning it on shows the recovery codes exactly
 * once, that signing in then asks for a code without looking like a failure,
 * and that an admin can hand somebody a way back in.
 */
import { test, expect } from "./fixtures.js";

/** The six digits an authenticator would show for this secret, right now. */
function codeFor(page, secret) {
  return page.evaluate(async (base32) => {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
    let bits = "";
    for (const character of base32.replace(/[\s=]/g, "").toUpperCase()) {
      bits += alphabet.indexOf(character).toString(2).padStart(5, "0");
    }
    const bytes = new Uint8Array(Math.floor(bits.length / 8));
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = parseInt(bits.slice(index * 8, index * 8 + 8), 2);
    }
    const counter = Math.floor(Date.now() / 1000 / 30);
    const message = new ArrayBuffer(8);
    new DataView(message).setUint32(4, counter);
    const key = await crypto.subtle.importKey(
      "raw",
      bytes,
      { name: "HMAC", hash: "SHA-1" },
      false,
      ["sign"],
    );
    const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, message));
    const offset = digest[digest.length - 1] & 0x0f;
    const chunk =
      ((digest[offset] & 0x7f) << 24) |
      (digest[offset + 1] << 16) |
      (digest[offset + 2] << 8) |
      digest[offset + 3];
    return String(chunk % 1000000).padStart(6, "0");
  }, secret);
}

test.describe("two-factor", () => {
  /**
   * Always leave two-factor off.
   *
   * These tests turn it on for the shared admin account, and a run that fails
   * halfway would otherwise leave it on — which does not break this file, it
   * breaks *every file after it*, because nothing else in the suite knows how
   * to answer a code prompt. Written the first time without this, it took out
   * three tests here and would have taken out the rest of the suite.
   *
   * Through the API rather than the UI, so it runs whatever state the page was
   * left in.
   */
  test.afterEach(async ({ signedIn }) => {
    await signedIn.evaluate(async (password) => {
      const token = sessionStorage.getItem("milsurp.token");
      if (!token) return;
      await fetch("/api/auth/totp/disable", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ password }),
      }).catch(() => {});
    }, "playwright-test-passphrase");
  });

  test("turning it on shows the recovery codes exactly once", async ({ signedIn }) => {
    await signedIn.goto("/security");
    const panel = signedIn.locator(".panel", { hasText: "Two-factor authentication" });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "Turn on two-factor" }).click();
    const secret = (await panel.locator(".totp-secret").innerText()).replace(/\s/g, "");
    expect(secret).toHaveLength(32);

    await panel.getByLabel("Code from the app").fill(await codeFor(signedIn, secret));
    await panel.getByRole("button", { name: /Finish turning it on/ }).click();

    // Ten of them, and this is the only time they are shown: a list of second
    // factors retrievable by anybody already signed in is not a second factor.
    await expect(panel.locator(".recovery-codes li")).toHaveCount(10);
    await panel.getByRole("button", { name: "I have saved them" }).click();
    await expect(panel.locator(".recovery-codes")).toHaveCount(0);

    await signedIn.reload();
    await expect(panel.locator(".recovery-codes")).toHaveCount(0);
    await expect(panel.getByText(/recovery code/)).toBeVisible();
  });

  test("and then signing in asks for a code", async ({ signedIn, page: _page }) => {
    await signedIn.goto("/security");
    const panel = signedIn.locator(".panel", { hasText: "Two-factor authentication" });
    await panel.getByRole("button", { name: "Turn on two-factor" }).click();
    const secret = (await panel.locator(".totp-secret").innerText()).replace(/\s/g, "");
    await panel.getByLabel("Code from the app").fill(await codeFor(signedIn, secret));
    await panel.getByRole("button", { name: /Finish turning it on/ }).click();
    await expect(panel.locator(".recovery-codes li")).toHaveCount(10);

    // Sign out and back in.
    await signedIn.getByRole("button", { name: /Sign out/i }).click();
    await expect(signedIn).toHaveURL(/\/login/);

    await signedIn.getByLabel("Username").fill("admin");
    await signedIn.getByLabel("Password").fill("playwright-test-passphrase");
    await signedIn.getByRole("button", { name: "Sign in" }).click();

    // Asked, not refused: the password was right, so no error box.
    const field = signedIn.getByLabel("Authenticator code");
    await expect(field).toBeVisible();
    await expect(signedIn.locator(".alert--error")).toHaveCount(0);

    await field.fill(await codeFor(signedIn, secret));
    await signedIn.getByRole("button", { name: "Verify" }).click();
    await expect(signedIn.getByRole("heading", { name: "Inventory" })).toBeVisible();

    // Signed back in, so afterEach has a token to turn it off with — which is
    // the only reason this test can end here rather than in the login screen.
  });
});

test.describe("password reset links", () => {
  test("an admin can send one, and it sets a password", async ({ signedIn }) => {
    await signedIn.goto("/users");
    await expect(signedIn.getByRole("heading", { name: "Users" })).toBeVisible();

    // A second account to reset — never the admin's own, which would lock this
    // test out of the session it is using.
    // Unique per run: this suite shares one database, so a fixed name collides
    // with whatever an earlier run left behind and the dialog simply stays
    // open on "that username is taken".
    const username = `reset-${Date.now().toString(36)}`;
    await signedIn.getByRole("button", { name: /Add user/ }).click();
    const dialog = signedIn.getByRole("dialog");
    await dialog.getByLabel("Username").fill(username);
    // example.com, not .test: EmailStr refuses RFC 2606 special-use
    // domains, and the dialog simply stays open saying so.
    await dialog.getByLabel("Email address").fill(`${username}@example.com`);
    await dialog.getByLabel("Password", { exact: true }).fill("an-original-passphrase");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(signedIn.getByRole("dialog")).toHaveCount(0);

    const row = signedIn.locator("tbody tr", { hasText: username });
    await row.getByRole("button", { name: "Reset link" }).click();

    // Email is off in this harness, so the link comes back for the admin to
    // pass on rather than the button silently doing nothing.
    const link = signedIn.locator(".reset-link");
    await expect(link).toBeVisible();
    const url = await link.innerText();
    expect(url).toContain("/reset/");

    await signedIn.goto(new URL(url).pathname);
    await expect(signedIn.getByText(/Choose a new password/)).toBeVisible();
    await signedIn.getByLabel("New password").fill("a-brand-new-passphrase");
    await signedIn.getByLabel("Again, to be sure").fill("a-brand-new-passphrase");
    await signedIn.getByRole("button", { name: "Set my password" }).click();
    await expect(signedIn.getByText(/Your password is set/)).toBeVisible();
  });

  test("a link that is not real says so rather than offering a form", async ({
    signedIn,
  }) => {
    await signedIn.goto("/reset/not-a-real-token");
    await expect(signedIn.getByText(/expired or has already been used/)).toBeVisible();
    await expect(signedIn.getByLabel("New password")).toHaveCount(0);
  });
});
