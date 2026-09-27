// Regenerates docs/assets/screenshot.png from the running Compose stack.
// Usage: node e2e/screenshot.js  (after `docker compose up -d --wait`)
import { readFileSync } from "node:fs";

import { chromium } from "@playwright/test";

const password = readFileSync(
  new URL("../../deploy/compose/secrets/dev_admin_password", import.meta.url),
  "utf8",
).trim();
const executablePath = process.env["PW_CHROMIUM_PATH"];

const browser = await chromium.launch(executablePath ? { executablePath } : {});
const page = await browser.newPage({
  ignoreHTTPSErrors: true,
  viewport: { width: 1280, height: 900 },
  colorScheme: "light",
});
await page.goto(process.env["DSEC_E2E_BASE_URL"] ?? "https://localhost");
await page.getByLabel("Username").fill("dev-admin");
await page.getByLabel("Password").fill(password);
await page.getByRole("button", { name: "Sign in" }).click();
await page.getByRole("heading", { name: "Overview" }).waitFor();
await page.goto(
  `${process.env["DSEC_E2E_BASE_URL"] ?? "https://localhost"}/dashboards/risk-committee`,
);
await page.getByRole("heading", { name: "Risk committee" }).waitFor();
await page.waitForLoadState("networkidle");
await page.screenshot({
  path: new URL("../../docs/assets/screenshot.png", import.meta.url).pathname,
});
await browser.close();
