import { expect, test } from "@playwright/test";

import { expectNoAxeViolations, setTheme, signIn, watchConsole } from "./helpers";

// These tests expect the sample data: `make e2e` loads it with `dsec-metrics demo`.
watchConsole();

const DASHBOARDS = [
  { path: "/dashboards/team-operations", title: "Team operations" },
  { path: "/dashboards/management", title: "Management" },
  { path: "/dashboards/risk-committee", title: "Risk committee" },
];

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

for (const { path, title } of DASHBOARDS) {
  test(`${title} dashboard renders in under 1.5 seconds and passes axe`, async ({ page }) => {
    const start = Date.now();
    await page.goto(path);
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    // Every widget has content, and the loading placeholders are gone.
    await expect(page.locator("[data-widget]").first()).toBeVisible();
    await expect(page.locator("[aria-busy=true]")).toHaveCount(0);
    const elapsed = Date.now() - start;
    test.info().annotations.push({ type: "render ms", description: String(elapsed) });
    expect(elapsed).toBeLessThan(1500);

    await setTheme(page, "Light");
    await expectNoAxeViolations(page);
    await setTheme(page, "Dark");
    await expectNoAxeViolations(page);
  });
}

test("drill down from a dashboard number to the source batch", async ({ page }) => {
  await page.goto("/dashboards/risk-committee");
  const rag = page.locator('[data-widget="rag_list"]');
  const value = rag.getByRole("link", { name: /^\d/ }).first();
  await value.click();

  await expect(page.getByRole("heading", { name: /^Measurement \d+$/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Calculation record" })).toBeVisible();
  await expectNoAxeViolations(page);

  await page.getByRole("region", { name: "Source batches" }).getByRole("link").first().click();
  await expect(page.getByText("The hash covers the records exactly as shown here")).toBeVisible();
  await expect(page.getByRole("region", { name: "Batch records" })).toBeVisible();
  await expectNoAxeViolations(page);

  await page.goBack();
  await page
    .getByRole("link", { name: /^KRI-|^KCI-|^KPI-/ })
    .first()
    .click();
  await expect(page.getByRole("region", { name: "Thresholds" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Version history" })).toBeVisible();
  await expectNoAxeViolations(page);
});

test("filters live in the URL and narrow the heatmap", async ({ page }) => {
  await page.goto("/dashboards/risk-committee");
  await page.getByLabel("Business unit", { exact: true }).selectOption("cards");
  await expect(page).toHaveURL(/business_unit=cards/);
  const heatmap = page.locator('[data-widget="heatmap"]');
  await expect(heatmap.getByRole("rowheader")).toHaveText(["Cards"]);
  await page.reload();
  await expect(page.getByLabel("Business unit", { exact: true })).toHaveValue("cards");
});

test("charts have a table view with linked values", async ({ page }) => {
  await page.goto("/dashboards/management");
  const toggle = page.getByRole("button", { name: /^View .* as table$/ }).first();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("table a[href^='/measurements/']").first()).toBeVisible();
  await expectNoAxeViolations(page);
});

for (const path of ["/", "/metrics", "/controls", "/exceptions", "/findings"]) {
  test(`${path} passes axe in light and dark`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("[aria-busy=true]")).toHaveCount(0);
    await setTheme(page, "Light");
    await expectNoAxeViolations(page);
    await setTheme(page, "Dark");
    await expectNoAxeViolations(page);
  });
}

test("control detail links requirements, metrics and evidence", async ({ page }) => {
  await page.goto("/controls");
  await page.getByRole("link", { name: /^DS-KM-01 / }).click();
  await expect(page.getByRole("region", { name: "Requirements" })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Evidence" }).getByRole("link").first(),
  ).toBeVisible();
  await expectNoAxeViolations(page);
});

test("keyboard users can reach every navigation item", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  const nav = page.getByRole("navigation", { name: "Main" }).getByRole("link");
  await expect(nav).toHaveCount(11); // the admin also sees Reports, Audit room and Audit log
  await nav.nth(3).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Risk committee", level: 1 })).toBeVisible();
});
