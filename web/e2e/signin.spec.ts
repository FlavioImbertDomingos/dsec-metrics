import { expect, test } from "@playwright/test";

import { credentials, expectNoAxeViolations, setTheme, watchConsole } from "./helpers";

watchConsole();

test("sign-in page passes axe in light and dark", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to dsec-metrics" })).toBeVisible();
  await setTheme(page, "Light");
  await expectNoAxeViolations(page);
  await setTheme(page, "Dark");
  await expectNoAxeViolations(page);
});

test("wrong password shows an error", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill("no-such-user");
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Wrong username or password.");
});

test("dev admin signs in, sees the overview, and signs out", async ({ page }) => {
  const { username, password } = credentials();
  await page.goto("/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Development mode")).toBeVisible();

  await setTheme(page, "Light");
  await expectNoAxeViolations(page);
  await setTheme(page, "Dark");
  await expectNoAxeViolations(page);

  // The session survives a reload.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to dsec-metrics" })).toBeVisible();
});

test("responses carry the security headers", async ({ request }) => {
  for (const path of ["/", "/api/meta"]) {
    const response = await request.get(path);
    expect(response.ok()).toBe(true);
    const h = response.headers();
    expect(h["strict-transport-security"]).toContain("max-age=31536000");
    expect(h["content-security-policy"]).toContain("script-src 'self'");
    expect(h["content-security-policy"]).not.toContain("unsafe-inline");
    expect(h["x-content-type-options"]).toBe("nosniff");
    expect(h["referrer-policy"]).toBe("no-referrer");
    expect(h["cross-origin-opener-policy"]).toBe("same-origin");
    expect(h.server).toBeUndefined();
  }
});
