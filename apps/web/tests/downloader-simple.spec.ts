import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("qBittorrent setup only needs an address and category", async ({
  page,
}, testInfo) => {
  execFileSync("uv", ["run", "python", "scripts/e2e_auth_budget.py"], {
    cwd: fileURLToPath(new URL("../../../", import.meta.url)),
    stdio: "pipe",
  });
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  if (await page.getByLabel("Your name").isVisible()) {
    await page.getByLabel("Your name").fill("Test Reader");
    await page.getByLabel("Setup token").fill("browser-test-bootstrap-token");
    await page.getByRole("button", { name: "Create administrator" }).click();
    await page.getByRole("button", { name: "Skip setup", exact: true }).click();
  } else {
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
  }
  await page.goto("/catalog");
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeVisible();
  let rootsRequested = false;
  await page.route("**/api/organization/download-roots", async (route) => {
    rootsRequested = true;
    await route.abort();
  });
  await page.goto("/settings#downloaders");
  await page
    .getByRole("button", { name: "Connect qBittorrent", exact: true })
    .click();
  const form = page.getByRole("form", {
    name: "qBittorrent connection settings",
  });
  await expect(form.locator("input")).toHaveCount(4);
  await form
    .getByLabel("qBittorrent URL or IP address", { exact: true })
    .fill("10.0.0.2:8080");
  await form
    .getByLabel("Download category", { exact: true })
    .fill("simple-books");
  await expect(
    form.getByLabel("qBittorrent username (optional)"),
  ).not.toHaveAttribute("required");
  await expect(
    form.getByLabel("qBittorrent password (optional)"),
  ).not.toHaveAttribute("required");
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/downloaders") &&
      response.request().method() === "POST",
  );
  await form
    .getByRole("button", { name: "Save downloader", exact: true })
    .click();
  const response = await saved;
  expect(response.status()).toBe(201);
  expect(response.request().postDataJSON()).not.toHaveProperty("save_path");
  expect(response.request().postDataJSON()).not.toHaveProperty("mappings");
  await expect(form).toHaveCount(0);
  await page.reload();
  const card = page
    .getByRole("article")
    .filter({ hasText: "http://10.0.0.2:8080" });
  await expect(card).toContainText("simple-books");
  await card
    .getByRole("button", { name: "Edit downloader", exact: true })
    .click();
  await expect(form.locator("input")).toHaveCount(4);
  await expect(
    form.getByLabel("Download category", { exact: true }),
  ).toHaveValue("simple-books");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("simple-qbittorrent-mobile.png"),
    fullPage: true,
  });
  expect(rootsRequested).toBe(false);
});
