import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  projects: [
    { name: "foundation", testMatch: "foundation.spec.ts" },
    {
      name: "browser",
      testIgnore: "foundation.spec.ts",
      dependencies: ["foundation"],
    },
  ],
  reporter: [["list"], ["junit", { outputFile: "test-results/browser.xml" }]],
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:8001",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "uv run python scripts/e2e_server.py",
    cwd: "../..",
    url: "http://127.0.0.1:8001/api/health/ready",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
