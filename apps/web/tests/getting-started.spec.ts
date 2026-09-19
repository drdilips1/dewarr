import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("getting started distinguishes disabled dispatch and unavailable status", async ({
  page,
}, testInfo) => {
  execFileSync("uv", ["run", "python", "scripts/e2e_auth_budget.py"], {
    cwd: fileURLToPath(new URL("../../../", import.meta.url)),
    stdio: "pipe",
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your catalog" }),
  ).toBeVisible();
  // The disposable server enables dispatch for acquisition tests. Exercise the
  // disabled presentation without mutating the server's deployment settings.
  await page.route("**/api/setup/readiness", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    await route.fulfill({
      response,
      json: { ...(await response.json()), download_dispatch_enabled: false },
    });
  });
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/") && request.method() !== "GET")
      writes.push(request.url());
  });
  await page
    .getByRole("link", { name: "Getting started", exact: true })
    .click();
  await expect(
    page.getByText(/Download dispatch is disabled in this installation/),
  ).toBeVisible();
  await page
    .getByText("How to enable download dispatch", { exact: true })
    .click();
  await expect(
    page.getByText("BOOK_DOWNLOAD_DISPATCH_ENABLED=true", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Refresh setup status" }).click();
  await expect(
    page.getByRole("button", { name: "Refresh setup status" }),
  ).toBeEnabled();
  await page.screenshot({
    path: testInfo.outputPath("getting-started-connected.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: testInfo.outputPath("getting-started-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(writes).toEqual([]);
  await page.unroute("**/api/setup/readiness");
  await page.route("**/api/setup/readiness", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Synthetic setup outage" }),
    }),
  );
  await page.getByRole("button", { name: "Refresh setup status" }).click();
  await expect(
    page.getByText("Setup status is unavailable. Refresh to check it again."),
  ).toBeVisible();
  await expect(page.getByLabel("Library setup")).toHaveCount(0);
  await page.unroute("**/api/setup/readiness");
  await page.getByRole("button", { name: "Refresh setup status" }).click();
  await expect(page.getByLabel("Library setup")).toBeVisible();
  await expect(
    page.getByText(/Download dispatch is enabled in this installation/),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
