import { expect, test } from "@playwright/test";

test("one bookshelf keeps filters and separates matching review", async ({
  page,
}) => {
  const requests: URL[] = [];
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith("/api/")) return route.continue();
    requests.push(url);
    let data: unknown = {};
    if (url.pathname === "/api/auth/me")
      data = {
        csrf_token: "test",
        user: {
          id: "reader",
          display_name: "Reader",
          role: "admin",
          onboarding_status: "complete",
        },
      };
    if (url.pathname === "/api/library/libraries") data = [];
    if (
      url.pathname === "/api/library/books" ||
      url.pathname === "/api/library/assets"
    )
      data = { items: [], total: 0 };
    if (url.pathname === "/api/catalog/works") data = { items: [], total: 80 };
    await route.fulfill({ json: data });
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/library$/);
  await expect(
    page.getByRole("heading", { name: "My Library", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Catalog", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Inventory state")).toHaveCount(0);
  await expect(page.getByLabel("Review queue")).toHaveCount(0);
  await page
    .getByRole("combobox", { name: "Media", exact: true })
    .selectOption("audio");
  await page.getByLabel("Sort books").selectOption("recent");
  await page
    .getByRole("searchbox", { name: "Search your library" })
    .fill("Harbor");
  await page
    .getByRole("button", { name: "Search library", exact: true })
    .click();
  await page.reload();
  await expect(page.getByLabel("Sort books")).toHaveValue("recent");
  await expect(
    page.getByRole("combobox", { name: "Media", exact: true }),
  ).toHaveValue("audio");
  await expect(
    page.getByRole("searchbox", { name: "Search your library" }),
  ).toHaveValue("Harbor");
  await page.getByRole("link", { name: "Review", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "All caught up" }),
  ).toBeVisible();
  expect(
    requests.some(
      (url) =>
        url.pathname === "/api/library/assets" &&
        url.searchParams.get("needs_review") === "true",
    ),
  ).toBe(true);
  await page.getByLabel("Review queue").selectOption("all");
  await page.getByLabel("Inventory state").selectOption("missing-confirmed");
  await expect(page).toHaveURL(/state=missing-confirmed/);
  await page.goto("/library?view=copies&medium=ebook&offset=40");
  await expect(page).toHaveURL(/\/review\?/);
  await expect(page.getByLabel("Review queue")).toHaveValue("all");
  await expect(
    page.getByRole("combobox", { name: "Media", exact: true }),
  ).toHaveValue("ebook");
  await page.goto("/library?review=true");
  await expect(page).toHaveURL(/\/review\?review=true/);
  await expect(page.getByLabel("Review queue")).toHaveValue("matching");
  await page.getByRole("link", { name: "My Library", exact: true }).click();
  await page
    .getByRole("link", { name: "All saved titles", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Add a title", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/view=saved/);
  await expect(page).toHaveURL(/offset=30/);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/library");
  await expect(
    page.getByRole("heading", { name: "Your bookshelf" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
