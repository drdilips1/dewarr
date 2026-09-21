import { expect, test } from "./fixtures";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("unified search keeps local ownership usable during a provider outage and opens known books", async ({
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
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeVisible();
  await page.goto("/library?view=saved");
  await expect(page.getByRole("heading", { name: "My Library" })).toBeVisible();
  const auth = await (await page.request.get("/api/auth/me")).json();
  const headers = {
    Origin: "http://127.0.0.1:8001",
    "X-CSRF-Token": auth.csrf_token,
  };
  const imported = await page.request.post(
    "/api/metadata/books/hardcover/42/import",
    { headers },
  );
  expect(imported.ok()).toBeTruthy();
  const work = await imported.json();
  const edited = await page.request.patch(`/api/metadata/works/${work.id}`, {
    headers,
    data: { values: { title: "My protected catalog title" } },
  });
  expect(edited.ok()).toBeTruthy();
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/") && request.method() !== "GET")
      writes.push(request.url());
  });
  const search = async (value: string) => {
    await page
      .getByLabel("Search books or authors", { exact: true })
      .fill(value);
    await page
      .getByLabel("Search books or authors", { exact: true })
      .press("Enter");
    await expect(page.getByLabel("Title, author or identifier")).toHaveValue(
      value,
    );
  };
  let releaseProvider!: () => void;
  const gate = new Promise<void>((resolve) => {
    releaseProvider = resolve;
  });
  await page.route("**/api/metadata/search?*", async (route) => {
    await gate;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Synthetic metadata outage" }),
    });
  });
  const failed = page.waitForResponse((response) =>
    response.url().includes("/api/metadata/search?"),
  );
  await search("The First Harbor");
  const local = page.getByRole("region", { name: "Matches in your catalog" });
  const owned = local.getByRole("link", { name: /The First Harbor/ });
  try {
    await expect(
      owned
        .locator("..")
        .getByRole("img", { name: /in library/ })
        .first(),
    ).toBeVisible();
    await expect(
      page.getByText("Synthetic metadata outage", { exact: true }),
    ).toHaveCount(0);
  } finally {
    releaseProvider();
  }
  await failed;
  await expect(
    page.getByText("Synthetic metadata outage", { exact: true }),
  ).toBeVisible();
  await expect(
    owned
      .locator("..")
      .getByRole("img", { name: /in library/ })
      .first(),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("local-during-outage.png"),
    fullPage: true,
  });
  await page.unroute("**/api/metadata/search?*");

  // The provider's original title maps to the protected local title through
  // an accepted provider identity, even when a title-text match is absent.
  await search("The Catalog Journey");
  const known = page.getByRole("link", {
    name: /View The Catalog Journey/,
  });
  await expect(known).toHaveAttribute("href", `/books/${work.id}`);
  await expect(
    page.getByRole("button", { name: "Add to catalog", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("known-provider-book.png"),
    fullPage: true,
  });
  await known.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "My protected catalog title", level: 1 }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("Title, author or identifier")).toHaveValue(
    "The Catalog Journey",
  );
  await search("My protected catalog title");
  await expect(
    local.getByRole("link", { name: /My protected catalog title/ }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "These results are already shown in your catalog matches above.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /View The Catalog Journey/ }),
  ).toHaveCount(0);
  await page.goBack();
  await expect(page.getByLabel("Title, author or identifier")).toHaveValue(
    "The Catalog Journey",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByLabel("Search books or authors", { exact: true }),
  ).toHaveValue("The Catalog Journey");
  await expect(known).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("known-provider-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  // An identity may become known after search. The preview reads it again
  // rather than offering another catalog import based on the earlier result.
  await page.route("**/api/metadata/search?*", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), known_works: {} },
    });
  });
  await page.reload();
  await page.getByRole("link", { name: /View The Catalog Journey/ }).click();
  await expect(
    page.getByRole("heading", { name: "My protected catalog title", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByText("In your catalog", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add to catalog", exact: true }),
  ).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
