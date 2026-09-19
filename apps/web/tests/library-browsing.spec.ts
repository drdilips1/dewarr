import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("library browsing searches all copies and preserves filters through navigation", async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
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
  const all = await (await page.request.get("/api/library/assets")).json();
  expect(all.total).toBeGreaterThan(1);
  const first = all.items.find(
    (item: { medium: string; title: string }) =>
      item.medium === "ebook" && item.title,
  );
  expect(first).toBeTruthy();
  const writes: string[] = [];
  page.on("request", (request) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method()))
      writes.push(request.url());
  });
  await page.goto("/library?offset=999");
  const copies = page.getByRole("region", {
    name: "Library copies",
    exact: true,
  });
  await expect(copies.getByText(/This page is empty/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reset library view" }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Media", exact: true })
    .selectOption("ebook");
  await expect(page).not.toHaveURL(/offset=/);
  await expect(copies.locator("article").first()).toBeVisible();
  await page
    .getByRole("searchbox", { name: "Search your library" })
    .fill(first.title);
  await page
    .getByRole("button", { name: "Search library", exact: true })
    .click();
  await expect(page).toHaveURL(/q=/);
  const expected = await (
    await page.request.get(
      `/api/library/assets?medium=ebook&q=${encodeURIComponent(first.title)}`,
    )
  ).json();
  await expect(copies.locator("article")).toHaveCount(expected.total);
  await expect(copies.getByRole("status")).toContainText(
    `${expected.total} library`,
  );
  await page
    .getByRole("combobox", { name: "Sort copies" })
    .selectOption("recent");
  await expect(page).toHaveURL(/sort=recent/);
  await page
    .getByRole("combobox", { name: "Library", exact: true })
    .selectOption(first.library_id);
  await page.reload();
  await expect(
    page.getByRole("searchbox", { name: "Search your library" }),
  ).toHaveValue(first.title);
  await expect(
    page.getByRole("combobox", { name: "Media", exact: true }),
  ).toHaveValue("ebook");
  await expect(
    page.getByRole("combobox", { name: "Library", exact: true }),
  ).toHaveValue(first.library_id);
  await expect(page.getByRole("combobox", { name: "Sort copies" })).toHaveValue(
    "recent",
  );
  await expect(copies.locator("article").first()).toBeVisible();
  await page
    .getByRole("combobox", { name: "Inventory state" })
    .selectOption("missing-confirmed");
  await expect(copies.getByText(/No copies match these filters/)).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("combobox", { name: "Inventory state" }),
  ).toHaveValue("any");
  await expect(copies.locator("article").first()).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("library-browsing-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: testInfo.outputPath("library-browsing-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.route("**/api/library/assets?*", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Synthetic library inventory outage" },
    }),
  );
  // Fail the next periodic refresh of the same populated query, rather than
  // switching to a new query with no cached holdings.
  await expect(
    copies.getByText("Synthetic library inventory outage", { exact: true }),
  ).toBeVisible({ timeout: 20_000 });
  await expect(copies.locator("article")).toHaveCount(0);
  await page.unroute("**/api/library/assets?*");
  await copies.getByRole("button", { name: "Retry library copies" }).click();
  await expect(
    copies.getByText("Synthetic library inventory outage", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Reset library view" }).click();
  await expect(page).toHaveURL(/\/library$/);
  await expect(copies.locator("article")).toHaveCount(all.total);
  await page
    .getByRole("checkbox", { name: "Needs matching", exact: true })
    .click();
  await expect(
    page.getByRole("checkbox", { name: "Needs matching", exact: true }),
  ).toBeChecked();
  await expect(page).toHaveURL(/review=true/);
  const reviews = await (
    await page.request.get("/api/library/assets?needs_review=true")
  ).json();
  await expect(copies.locator("article")).toHaveCount(reviews.total);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
