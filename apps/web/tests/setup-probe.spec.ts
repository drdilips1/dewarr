import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("destination setup qualifies an empty save folder without an import plan", async ({
  page,
  request,
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
  const before = await (
    await request.get("http://127.0.0.1:13379/fixture/recovery-stats")
  ).json();
  await page.goto("/downloaders");
  const card = page.getByRole("article", { name: "qBittorrent", exact: true });
  await card.getByRole("button", { name: "Edit downloader" }).click();
  const form = page.getByRole("form", {
    name: "qBittorrent connection settings",
  });
  await form
    .getByLabel("Download save folder", { exact: true })
    .fill("/downloads/bootstrap");
  await form.getByLabel("Enable connection", { exact: true }).check();
  await form
    .getByRole("button", { name: "Save downloader", exact: true })
    .click();
  await card
    .getByRole("button", { name: "Test saved connection", exact: true })
    .click();
  await expect(card).toContainText("connected");
  await page.goto("/organization/destinations");
  const destination = page.getByRole("region", {
    name: "Destination ebooks",
    exact: true,
  });
  await expect(destination.getByLabel("Downloader to test")).toHaveValue(/.+/);
  await expect(destination).toContainText(
    "qBittorrent save folder: /downloads/bootstrap",
  );
  let releaseActivity!: () => void;
  const activityGate = new Promise<void>((resolve) => {
    releaseActivity = resolve;
  });
  await page.route("**/api/activity", async (route) => {
    await activityGate;
    await route.continue();
  });
  const response = page.waitForResponse(
    (response) =>
      response.url().endsWith("/setup-probe") &&
      response.request().method() === "POST",
  );
  await destination
    .getByRole("button", { name: "Test destination route", exact: true })
    .click();
  const queued = await response;
  expect(queued.status()).toBe(202);
  expect(queued.request().postDataJSON()).not.toHaveProperty("plan_id");
  try {
    await expect(
      destination.getByText(
        "Filesystem and ABS folder mapping verified; ready for a reviewed import plan",
        { exact: true },
      ),
    ).toHaveCount(0);
  } finally {
    releaseActivity();
  }
  await expect(destination).toContainText(
    "Filesystem and ABS folder mapping verified; ready for a reviewed import plan",
  );
  await expect(
    destination.getByRole("button", {
      name: "Test destination route",
      exact: true,
    }),
  ).toBeEnabled();
  await page.reload();
  await expect(destination).toContainText(
    "Filesystem and ABS folder mapping verified; ready for a reviewed import plan",
  );
  await page.screenshot({
    path: testInfo.outputPath("empty-folder-probe-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: testInfo.outputPath("empty-folder-probe-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(
    await (
      await request.get("http://127.0.0.1:13379/fixture/recovery-stats")
    ).json(),
  ).toEqual(before);
  expect(errors).toEqual([]);
});
