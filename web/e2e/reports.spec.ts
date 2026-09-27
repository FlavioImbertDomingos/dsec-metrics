import { expect, type Page, test } from "@playwright/test";

import { expectNoAxeViolations, setTheme, signIn, watchConsole } from "./helpers";
import { checkPackage, devPassword, flipManifestByte, reportOf } from "./package-check.js";

// `make e2e` loads the sample data and creates e2e-auditor with a PCI DSS grant for 2026.
watchConsole();

async function buildReport(page: Page, type: string, fields: Record<string, string> = {}) {
  await page.goto("/reports");
  await page.getByLabel("Report type").selectOption(type);
  for (const [label, value] of Object.entries(fields)) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByRole("button", { name: "Build and sign" }).click();
  await expect(page.getByText(/^Built /)).toBeVisible({ timeout: 30_000 });
}

test("build a package, download it and verify it independently", async ({ page }) => {
  await signIn(page);
  await buildReport(page, "framework", {
    "Framework pack": "pci-dss-4.0.1",
    Requirements: "3, 8",
    "Prepared for": "Example QSA",
  });
  await setTheme(page, "Light");
  await expectNoAxeViolations(page);
  await setTheme(page, "Dark");
  await expectNoAxeViolations(page);

  const key = (await (await page.request.get("/api/reports/public-key")).json()) as {
    fingerprint: string;
  };
  const href = await page
    .getByRole("table", { name: "Report packages" })
    .getByRole("link", { name: "Download" })
    .first()
    .getAttribute("href");
  expect(href).toMatch(/^\/api\/reports\/[0-9a-f-]+\/download$/);
  const response = await page.request.get(href ?? "");
  expect(response.ok()).toBe(true);
  const body = await response.body();
  expect(checkPackage(body, key.fingerprint)).toEqual([]);
  expect(reportOf(body)?.prepared_for).toBe("Example QSA");
  // One changed byte fails the check.
  expect(checkPackage(flipManifestByte(body), key.fingerprint)).not.toEqual([]);
});

test("an auditor reaches the package through a link and sees only the audit room", async ({
  page,
  browser,
}) => {
  await signIn(page);
  await buildReport(page, "control", { Control: "DS-SM-02" });
  await page.getByRole("button", { name: "Auditor link" }).first().click();
  await page.getByLabel("Auditor username").fill("e2e-auditor");
  await page.getByRole("button", { name: "Create link" }).click();
  const code = page.locator("code", { hasText: "/api/links/" });
  await expect(code).toBeVisible();
  const url = (await code.textContent()) ?? "";

  const password = devPassword();
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const auditor = await context.newPage();
  await auditor.goto("/");
  await auditor.getByLabel("Username").fill("e2e-auditor");
  await auditor.getByLabel("Password").fill(password);
  await auditor.getByRole("button", { name: "Sign in" }).click();
  await expect(auditor.getByRole("heading", { name: "Audit room" })).toBeVisible();
  const nav = auditor.getByRole("navigation", { name: "Main" }).getByRole("link");
  await expect(nav).toHaveText(["Audit room"]);
  expect((await auditor.request.get(url)).ok()).toBe(true);
  expect((await auditor.request.get("/api/metrics")).status()).toBe(403);
  await auditor.reload();
  await expect(auditor.getByRole("table", { name: "Access log" })).toBeVisible();
  await expectNoAxeViolations(auditor);
  await context.close();

  // The link is personal: the admin cannot use it.
  expect((await page.request.get(url)).status()).toBe(404);
});

test("admins verify the audit chain", async ({ page }) => {
  await signIn(page);
  await page.goto("/audit-log");
  await page.getByRole("button", { name: "Verify chain" }).click();
  await expect(page.getByText(/^Chain intact: \d+ entries/)).toBeVisible();
  await expect(page.getByRole("table", { name: "Audit log entries" })).toBeVisible();
  await expectNoAxeViolations(page);
  await page.goto("/audit-room");
  await expect(page.getByRole("heading", { name: "Audit room" })).toBeVisible();
  await expectNoAxeViolations(page);
});
