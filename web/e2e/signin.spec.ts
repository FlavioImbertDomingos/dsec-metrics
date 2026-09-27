import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

function credentials(): { username: string; password: string } {
  const meta = test.info().config.metadata as { username: string; password: string };
  if (!meta.password) throw new Error("no dev admin password: run make dev-secrets first");
  return meta;
}

async function expectNoAxeViolations(page: Page) {
  // Colors mid-transition can fail contrast checks; wait until nothing is animating.
  await page.waitForFunction(() => document.getAnimations().length === 0);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  // Name each failing element so a CI log is enough to find and fix it.
  const found = results.violations.flatMap((v) =>
    v.nodes.map((n) => `${v.id}: ${n.target.join(" ")} :: ${n.failureSummary ?? v.help}`),
  );
  expect(found).toEqual([]);
}

async function setTheme(page: Page, theme: "Light" | "Dark") {
  await page.getByRole("button", { name: `${theme} theme` }).click();
  await expect(page.locator("html")).toHaveClass(theme === "Dark" ? /dark/ : /^(?!.*dark).*$/);
}

test.beforeEach(({ page }) => {
  const problems: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") problems.push(msg.text());
  });
  page.on("pageerror", (err) => problems.push(err.message));
  test
    .info()
    .attach("console", { body: "" })
    .catch(() => undefined);
  (page as Page & { problems?: string[] }).problems = problems;
});

test.afterEach(({ page }) => {
  // Any console error (a CSP violation shows up here) fails the test.
  const problems = (page as Page & { problems?: string[] }).problems ?? [];
  expect(problems.filter((p) => !p.includes("401"))).toEqual([]);
});

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

test("dev admin signs in, sees the placeholder page, and signs out", async ({ page }) => {
  const { username, password } = credentials();
  await page.goto("/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: /^Welcome, / })).toBeVisible();
  await expect(page.getByText(`Signed in as ${username}.`, { exact: false })).toBeVisible();
  await expect(page.getByText("Development mode")).toBeVisible();

  await setTheme(page, "Light");
  await expectNoAxeViolations(page);
  await setTheme(page, "Dark");
  await expectNoAxeViolations(page);

  // The session survives a reload.
  await page.reload();
  await expect(page.getByRole("heading", { name: /^Welcome, / })).toBeVisible();

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
