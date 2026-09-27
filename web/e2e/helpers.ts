import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

export function credentials(): { username: string; password: string } {
  const meta = test.info().config.metadata as { username: string; password: string };
  if (!meta.password) throw new Error("no dev admin password: run make dev-secrets first");
  return meta;
}

export async function signIn(page: Page) {
  const { username, password } = credentials();
  await page.goto("/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

export async function expectNoAxeViolations(page: Page) {
  // Colors mid-transition can fail contrast checks; wait until nothing is animating.
  await page.waitForFunction(() => document.getAnimations().length === 0);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const found = results.violations.flatMap((v) =>
    v.nodes.map((n) => `${v.id}: ${n.target.join(" ")} :: ${n.failureSummary ?? v.help}`),
  );
  expect(found).toEqual([]);
}

export async function setTheme(page: Page, theme: "Light" | "Dark") {
  await page.getByRole("button", { name: `${theme} theme` }).click();
  await expect(page.locator("html")).toHaveClass(theme === "Dark" ? /dark/ : /^(?!.*dark).*$/);
}

/** Fail the test on any console error; CSP violations are reported there. */
export function watchConsole() {
  test.beforeEach(({ page }) => {
    const problems: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") problems.push(msg.text());
    });
    page.on("pageerror", (err) => problems.push(err.message));
    (page as Page & { problems?: string[] }).problems = problems;
  });
  test.afterEach(({ page }) => {
    const problems = (page as Page & { problems?: string[] }).problems ?? [];
    expect(problems.filter((p) => !p.includes("401"))).toEqual([]);
  });
}
