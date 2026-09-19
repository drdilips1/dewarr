import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("recent library additions show confirmed holdings and recover from shelf failures", async ({
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
  const actual = await (
    await page.request.get("/api/discovery/library")
  ).json();
  expect(actual.items.length).toBeGreaterThan(0);
  const first = actual.items[0].work;
  const writes: string[] = [];
  page.on("request", (request) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method()))
      writes.push(request.url());
  });
  let outage = false;
  // Preserve actual holdings. Override only has_more so this small fixture
  // exercises page navigation; API tests qualify real pagination boundaries.
  const queries: URLSearchParams[] = [];
  await page.route("**/api/discovery/library?*", async (route) => {
    queries.push(new URL(route.request().url()).searchParams);
    if (outage) {
      await route.fulfill({
        status: 503,
        json: { detail: "Synthetic library shelf outage" },
      });
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const body = await response.json();
    await route.fulfill({
      response,
      json: { ...body, has_more: body.page === 1 },
    });
  });
  await page.getByRole("link", { name: "Discover", exact: true }).click();
  const shelf = page.getByRole("region", {
    name: "Recent library additions",
    exact: true,
  });
  const book = shelf.getByRole("link", {
    name: new RegExp(first.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
  });
  await expect(book).toContainText("In library");
  await expect(
    shelf.getByText(/Library copy first observed/).first(),
  ).toBeVisible();
  await shelf
    .getByRole("button", { name: "Next library page", exact: true })
    .click();
  await expect(shelf.getByRole("status")).toHaveText("Page 2");
  expect(queries.at(-1)?.get("page")).toBe("2");
  await shelf
    .getByRole("combobox", { name: "Show library additions" })
    .selectOption("audio");
  await expect(shelf.getByRole("status")).toHaveText("Page 1");
  expect(queries.at(-1)?.get("medium")).toBe("audio");
  for (const item of await shelf.locator(".book-card").all())
    await expect(item).toContainText("Audio");
  await shelf
    .getByRole("combobox", { name: "Show library additions" })
    .selectOption("ebook");
  await expect(
    shelf.getByRole("button", { name: "Next library page" }),
  ).toBeEnabled();
  expect(queries.at(-1)?.get("medium")).toBe("ebook");
  for (const item of await shelf.locator(".book-card").all())
    await expect(item).toContainText("Ebook");
  await shelf.screenshot({
    path: testInfo.outputPath("recent-library-desktop.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await shelf.screenshot({
    path: testInfo.outputPath("recent-library-mobile.png"),
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  outage = true;
  await shelf
    .getByRole("combobox", { name: "Show library additions" })
    .selectOption("any");
  await expect(
    shelf.getByText("Synthetic library shelf outage", { exact: true }),
  ).toBeVisible();
  await expect(shelf.locator(".book-card")).toHaveCount(0);
  outage = false;
  await shelf.getByRole("button", { name: "Retry library shelf" }).click();
  await expect(book).toBeVisible();
  await book.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: first.title, exact: true, level: 1 }),
  ).toBeVisible();
  expect(errors).toEqual([]);
  expect(writes).toEqual([]);
});
