import { expect, test } from "@playwright/test";

test("setup, catalog, private list and durable worker are usable together", async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Set up your library" }),
  ).toBeVisible();
  await page.getByLabel("Your name").fill("Test Reader");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByLabel("Setup token").fill("browser-test-bootstrap-token");
  await page.getByRole("button", { name: "Create administrator" }).click();
  await expect(
    page.getByRole("heading", { name: "Your catalog" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add a title" }).click();
  await page.getByLabel("Title", { exact: true }).fill("The Synthetic Archive");
  await page.getByLabel("Author", { exact: true }).fill("Example Author");
  await page
    .getByLabel("Description")
    .fill("A synthetic title used to verify catalog and list workflows.");
  await page.getByRole("button", { name: "Save title" }).click();
  await expect(
    page.getByRole("heading", { name: "The Synthetic Archive" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page.getByLabel("Create a private list").fill("Weekend reads");
  await page.getByRole("button", { name: "Create list" }).click();
  await expect(
    page.getByRole("heading", { name: "Weekend reads" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Catalog", exact: true }).click();
  await page.getByRole("link", { name: /The Synthetic Archive/ }).click();
  await expect(
    page.getByText("Not confirmed in library", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Reading list")
    .selectOption({ label: "Weekend reads" });
  await page.getByRole("button", { name: "Add to list" }).click();
  await expect(page.getByRole("status")).toHaveText("Added to your list.");
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page.getByRole("link", { name: /Weekend reads/ }).click();
  await expect(
    page.getByRole("heading", { name: "The Synthetic Archive" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("reading-list-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Activity", exact: true }).click();
  await page.getByRole("button", { name: "Check background worker" }).click();
  await expect(page.getByText("completed", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("link", { name: "Connections", exact: true }).click();
  await page
    .getByRole("button", { name: "Connect Audiobookshelf", exact: true })
    .click();
  await page.getByLabel("Connection name").fill("Fixture ABS");
  await page.getByLabel(/^Server URL/).fill("http://127.0.0.1:13379/abs");
  await page
    .getByLabel("API token", { exact: true })
    .fill("browser-abs-fixture-token");
  await page.getByRole("button", { name: "Save connection" }).click();
  await page
    .getByRole("button", { name: "Test connection", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Fixture ABS connected");
  await page.getByRole("button", { name: "Sync library", exact: true }).click();
  await page.getByRole("link", { name: "Activity", exact: true }).click();
  const inventory = page.locator("article").filter({
    has: page.getByRole("heading", { name: "Audiobookshelf inventory sync" }),
  });
  await expect(inventory.getByText("completed", { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole("link", { name: "My Library", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "The First Harbor", exact: true }),
  ).toHaveCount(2);
  await expect(
    page.getByRole("link", { name: "Open in Audiobookshelf" }).first(),
  ).toHaveAttribute("href", "http://127.0.0.1:13379/abs/item/fixture-harbor");
  await page.screenshot({
    path: testInfo.outputPath("library-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Correct match" }).first().click();
  await page
    .getByLabel("Search catalog", { exact: true })
    .fill("The Synthetic Archive");
  await page
    .getByRole("combobox", { name: "Book", exact: true })
    .selectOption({ label: "The Synthetic Archive — Example Author" });
  await page.getByRole("button", { name: "Confirm match" }).click();
  await page.getByRole("link", { name: "Catalog", exact: true }).click();
  const owned = page.getByRole("link", { name: /The Synthetic Archive/ });
  await expect(owned).toContainText("In library");
  await page.getByRole("link", { name: "Metadata", exact: true }).click();
  await page.getByLabel("Hardcover API token").fill("browser-hardcover-token");
  await page.getByRole("button", { name: "Save catalog connection" }).click();
  await page.getByRole("button", { name: "Test catalog connection" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Hardcover catalog access verified.",
  );
  await page.getByRole("link", { name: "Search books", exact: true }).click();
  await page
    .getByLabel("Title, author or identifier")
    .fill("The Catalog Journey");
  await page.getByRole("button", { name: "Search books", exact: true }).click();
  await page
    .getByRole("button", { name: /The Catalog Journey Catalog Author/ })
    .click();
  const preview = page.getByRole("region", { name: "Catalog preview" });
  await expect(preview).toBeFocused();
  await expect(preview.getByText("2 catalog editions loaded.")).toBeVisible();
  await preview.getByRole("button", { name: "Add to catalog" }).click();
  await expect(
    page.getByRole("heading", { name: "The Catalog Journey", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Narrated by Sample Narrator")).toBeVisible();
  await expect(
    page.getByText("Not confirmed in library", { exact: true }),
  ).toBeVisible();
  await page
    .getByText("Metadata sources and protected edits", { exact: true })
    .click();
  await page.getByRole("button", { name: "Edit book details" }).click();
  await page
    .getByLabel("Book title", { exact: true })
    .fill("My protected catalog title");
  await page.getByRole("button", { name: "Save protected edits" }).click();
  await expect(
    page.getByRole("heading", { name: "My protected catalog title", level: 1 }),
  ).toBeVisible();
  const refreshed = page.waitForResponse(
    (response) =>
      response.url().endsWith("/source") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Refresh Hardcover", exact: true })
    .click();
  expect((await refreshed).status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "My protected catalog title", level: 1 }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("catalog-metadata-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("catalog-metadata-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("link", { name: "Accounts", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill("Guest reader");
  await page.getByLabel("Username", { exact: true }).fill("guest");
  await page
    .getByLabel("Password", { exact: true })
    .fill("guest reader password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("guest", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Connections", exact: true }).click();
  await page.getByRole("checkbox", { name: "Guest reader" }).check();
  const granted = page.waitForResponse(
    (response) =>
      response.url().endsWith("/grants") &&
      response.request().method() === "PUT",
  );
  await page.getByRole("button", { name: "Save access" }).click();
  expect((await granted).status()).toBe(204);
  await page.screenshot({
    path: testInfo.outputPath("connections-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: "Catalog", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your catalog" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("catalog-mobile.png"),
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "The Synthetic Archive" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
  await page.getByLabel("Username", { exact: true }).fill("guest");
  await page
    .getByLabel("Password", { exact: true })
    .fill("guest reader password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "My Library", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Open in Audiobookshelf" }),
  ).toHaveCount(2);
  await expect(
    page.getByRole("link", { name: "Connections", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("library-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
