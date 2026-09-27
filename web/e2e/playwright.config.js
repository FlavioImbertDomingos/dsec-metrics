// @ts-check
import { existsSync, readFileSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

const secretFile = new URL("../../deploy/compose/secrets/dev_admin_password", import.meta.url);
const password =
  process.env["DSEC_E2E_PASSWORD"] ??
  (existsSync(secretFile) ? readFileSync(secretFile, "utf8").trim() : "");

// Set PW_CHROMIUM_PATH to use a preinstalled Chromium instead of `playwright install`.
const executablePath = process.env["PW_CHROMIUM_PATH"];

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env["CI"]),
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "../playwright-report" }]],
  outputDir: "../test-results",
  metadata: { username: process.env["DSEC_E2E_USERNAME"] ?? "dev-admin", password },
  use: {
    baseURL: process.env["DSEC_E2E_BASE_URL"] ?? "https://localhost",
    // The stack serves a certificate from the local development CA.
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(executablePath ? { launchOptions: { executablePath } } : {}),
      },
    },
  ],
});
