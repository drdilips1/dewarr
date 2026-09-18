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
  await page.getByRole("link", { name: "My Library", exact: true }).click();
  await page.getByRole("button", { name: "Correct match" }).first().click();
  await page.getByText("Match correction history", { exact: true }).click();
  await page
    .getByRole("button", { name: "Undo correction", exact: true })
    .click();
  await page.getByRole("link", { name: "Catalog", exact: true }).click();
  await expect(
    page.getByRole("link", { name: /The Synthetic Archive/ }),
  ).not.toContainText("In library");
  await page.getByRole("link", { name: "My Library", exact: true }).click();
  await page.getByRole("button", { name: "Correct match" }).first().click();
  await page
    .getByLabel("Search catalog", { exact: true })
    .fill("The Synthetic Archive");
  await page
    .getByRole("combobox", { name: "Book", exact: true })
    .selectOption({ label: "The Synthetic Archive — Example Author" });
  await page.getByRole("button", { name: "Confirm match" }).click();
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
  await expect(page.getByLabel("Automatic metadata lookup")).toContainText(
    "Missing metadata checked against Open Library",
    { timeout: 15_000 },
  );
  await expect(
    page.getByRole("button", { name: "Refresh Open Library", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Not confirmed in library", { exact: true }),
  ).toBeVisible();
  await page
    .getByText("Metadata sources and protected edits", { exact: true })
    .click();
  await page.getByRole("button", { name: "Edit book details" }).click();
  await expect(
    page.getByLabel("Publication year", { exact: true }),
  ).toHaveValue("2020");
  await expect(page.getByLabel("Book description")).toHaveValue(
    "A synthetic book for catalog and metadata verification.",
  );
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
  const wanted = page.getByRole("region", {
    name: "Wanted media",
    exact: true,
  });
  await wanted.getByLabel("Media to request").selectOption("both");
  const requestPreview = wanted.getByLabel("Request preview", { exact: true });
  await expect(requestPreview).toContainText("Ebook · Wanted");
  await expect(requestPreview).toContainText("Audiobook · Wanted");
  await wanted.getByRole("button", { name: "Save to wanted" }).click();
  await expect(wanted.getByRole("status")).toHaveText(
    "Your media request was saved.",
  );
  await expect(wanted.locator("article")).toHaveCount(1);
  await page.reload();
  await expect(wanted.locator("article")).toHaveCount(1);
  await wanted
    .locator("article")
    .getByRole("button", { name: "Cancel your request", exact: true })
    .click();
  await expect(wanted.locator("article")).toContainText("Ebook · Cancelled");
  await expect(wanted.locator("article")).toContainText(
    "Audiobook · Cancelled",
  );
  await page
    .getByRole("button", { name: "Request this recording", exact: true })
    .click();
  await expect(
    wanted.getByRole("heading", { name: "Wanted media" }),
  ).toBeFocused();
  await expect(wanted).toContainText("Sample Narrator");
  await expect(requestPreview).toContainText("Audiobook · Wanted");
  await wanted.getByRole("button", { name: "Save to wanted" }).click();
  await expect(wanted.getByRole("status")).toHaveText(
    "Your media request was saved.",
  );
  await expect(wanted.locator("article")).toHaveCount(2);
  await expect(
    wanted.locator("article").filter({ hasText: "Sample Narrator" }),
  ).toContainText("Audiobook · Wanted");
  await page.screenshot({
    path: testInfo.outputPath("wanted-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await wanted.scrollIntoViewIfNeeded();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("wanted-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.request.post("http://127.0.0.1:13379/fixture/catalog/narrator", {
    data: { narrator: "Changed Narrator" },
  });
  await page
    .getByRole("button", { name: "Refresh Hardcover", exact: true })
    .click();
  const review = page.getByRole("region", { name: "Changed edition review" });
  await expect(review).toContainText("Changed Narrator");
  await page.screenshot({
    path: testInfo.outputPath("edition-review-desktop.png"),
    fullPage: true,
  });
  await review.getByRole("button", { name: "Keep current version" }).click();
  await expect(review).toHaveCount(0);
  await page.getByText("Match correction history", { exact: true }).click();
  await page
    .getByRole("button", { name: "Undo correction", exact: true })
    .click();
  await expect(review).toBeVisible();
  await review
    .getByRole("button", { name: "Accept as separate version" })
    .click();
  await expect(
    page.getByText("Narrated by Changed Narrator", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Unmatch Hardcover", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Remove catalog match", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Refresh Hardcover", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "My protected catalog title", level: 1 }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Undo correction", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Refresh Hardcover", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Narrated by Changed Narrator", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("correction-history-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const mainBookUrl = page.url();
  await page.getByRole("link", { name: "Catalog", exact: true }).click();
  await page.getByRole("button", { name: "Add a title" }).click();
  await page
    .getByLabel("Title", { exact: true })
    .fill("My duplicate catalog entry");
  await page.getByLabel("Author", { exact: true }).fill("Catalog Author");
  await page.getByRole("button", { name: "Save title" }).click();
  await page.getByRole("link", { name: /My duplicate catalog entry/ }).click();
  await expect(
    page.getByRole("heading", { name: "My duplicate catalog entry", level: 1 }),
  ).toBeVisible();
  const duplicateBookUrl = page.url();
  await page
    .getByRole("button", { name: "Merge duplicate book", exact: true })
    .click();
  await page
    .getByLabel("Find the book to keep")
    .fill("My protected catalog title");
  await page.getByRole("button", { name: "Find duplicate" }).click();
  await page
    .getByRole("button", {
      name: "Keep My protected catalog title · Catalog Author",
      exact: true,
    })
    .click();
  const mergePreview = page.getByRole("region", { name: "Merge preview" });
  await expect(mergePreview).toBeFocused();
  await expect(mergePreview).toContainText("Recordings stay distinct");
  await page.screenshot({
    path: testInfo.outputPath("merge-preview-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("merge-preview-mobile.png"),
    fullPage: true,
  });
  await page.getByLabel("These records describe the same book").check();
  await page.getByRole("button", { name: "Merge into selected book" }).click();
  await expect(page).toHaveURL(mainBookUrl);
  await page.goto(duplicateBookUrl);
  await expect(page).toHaveURL(mainBookUrl);
  await page.getByText("Match correction history", { exact: true }).click();
  const merged = page.locator("article").filter({
    hasText:
      "Merged My duplicate catalog entry into My protected catalog title",
  });
  await merged
    .getByRole("button", { name: "Undo correction", exact: true })
    .click();
  await expect(merged).toContainText("Undone");
  await page.goto(duplicateBookUrl);
  await expect(
    page.getByRole("heading", { name: "My duplicate catalog entry", level: 1 }),
  ).toBeVisible();
  await page.goto(mainBookUrl);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("link", { name: "Organization", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "File organization", exact: true }),
  ).toBeVisible();
  const examples = page.getByRole("region", { name: "Naming examples" });
  await expect(examples).toContainText(
    "5 planned item folders · 0 need attention",
  );
  await expect(examples).toContainText("2024 - The First Harbor - Casey Reed");
  await page.getByText("Customize naming", { exact: true }).click();
  await page
    .getByLabel("Ebook folder", { exact: true })
    .fill("{author}/{title}[ - {edition_year}]");
  await expect(examples).toContainText(
    "Library: ebooks/Alex Morgan/The First Harbor - 2017/The First Harbor.epub",
  );
  const namingSaved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/organization/settings") &&
      response.request().method() === "PUT",
  );
  await page.getByRole("button", { name: "Save naming settings" }).click();
  expect((await namingSaved).status()).toBe(200);
  await page.reload();
  await page.getByText("Customize naming", { exact: true }).click();
  await expect(page.getByLabel("Ebook folder", { exact: true })).toHaveValue(
    "{author}/{title}[ - {edition_year}]",
  );
  await page.screenshot({
    path: testInfo.outputPath("organization-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("organization-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Reset naming defaults" }).click();
  const namingReset = page.waitForResponse(
    (response) =>
      response.url().endsWith("/organization/settings") &&
      response.request().method() === "PUT",
  );
  await page.getByRole("button", { name: "Save naming settings" }).click();
  expect((await namingReset).status()).toBe(200);
  await page.getByRole("link", { name: "Inspect completed downloads" }).click();
  await page.getByLabel("Download folder", { exact: true }).fill("completed");
  await page
    .getByLabel(
      "The download has finished and its files are no longer changing",
    )
    .check();
  await page
    .getByRole("button", { name: "Inspect files", exact: true })
    .click();
  const inspected = page.getByRole("region", { name: "Inspected download" });
  await expect(inspected).toContainText("1 files inspected · 1 book groups");
  await inspected
    .getByRole("button", { name: "Review file groups", exact: true })
    .click();
  const groupEditor = page.getByRole("region", {
    name: "Edit file groups",
    exact: true,
  });
  await groupEditor
    .getByRole("combobox", { name: "Book group for book.epub", exact: true })
    .selectOption("");
  await groupEditor
    .getByLabel("Exclusion reason for book.epub")
    .fill("Not part of this reading list");
  await page.screenshot({
    path: testInfo.outputPath("grouping-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await groupEditor
    .getByRole("button", { name: "Save file groups", exact: true })
    .click();
  await expect(inspected).toContainText("1 files inspected · 0 book groups");
  await page.reload();
  await expect(inspected).toContainText("1 files excluded from this plan");
  await inspected
    .getByRole("button", { name: "Review file groups", exact: true })
    .click();
  await expect(
    groupEditor.getByLabel("Exclusion reason for book.epub"),
  ).toHaveValue("Not part of this reading list");
  await groupEditor
    .getByRole("button", { name: "Restore proposed groups", exact: true })
    .click();
  await expect(inspected).toContainText("1 files inspected · 1 book groups");
  await inspected
    .getByLabel("Find catalog book")
    .fill("My protected catalog title");
  await inspected.getByRole("button", { name: "Find matching book" }).click();
  await inspected
    .getByRole("combobox", { name: "Catalog book", exact: true })
    .selectOption({ label: "My protected catalog title · Catalog Author" });
  await expect(
    inspected
      .getByRole("combobox", { name: "Catalog version", exact: true })
      .locator("option"),
  ).not.toHaveCount(1);
  await inspected
    .getByRole("combobox", { name: "Catalog version", exact: true })
    .selectOption({ index: 1 });
  await inspected
    .getByLabel(
      "These files contain the complete book, not a sample or companion document",
    )
    .check();
  await inspected.getByRole("button", { name: "Save import plan" }).click();
  const savedPlan = page.getByRole("article", { name: "Saved import plan" });
  await expect(savedPlan).toContainText(
    "1 planned item folders · 0 need attention",
  );
  await page.reload();
  await expect(savedPlan).toContainText("book.epub → ebooks/");
  await savedPlan.getByRole("link", { name: "Check destination" }).click();
  await page
    .getByRole("combobox", { name: "Audiobookshelf library", exact: true })
    .selectOption({ index: 1 });
  await page.getByLabel("Audiobookshelf folder path").fill("/fixture/books");
  await page
    .getByRole("button", { name: "Save destination", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Test destination route", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Destination ebooks" }),
  ).toContainText(
    "Filesystem and ABS folder mapping verified; ready for a reviewed import plan",
  );
  await page.screenshot({
    path: testInfo.outputPath("destinations-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.goBack();
  await expect(savedPlan).toContainText("book.epub → ebooks/");
  await page
    .getByRole("button", { name: "Import resolved books", exact: true })
    .click();
  const importResult = page
    .getByRole("region", { name: "Import result" })
    .first();
  await expect(importResult).toContainText("Waiting for Audiobookshelf");
  await page.request.post("http://127.0.0.1:13379/fixture/scan");
  await importResult
    .getByRole("button", { name: "Retry library detection" })
    .click();
  await expect(importResult).toContainText("Available in Audiobookshelf");
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Import result" }).first(),
  ).toContainText("Available in Audiobookshelf");
  await page.screenshot({
    path: testInfo.outputPath("inspection-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
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
  ).toHaveCount(3);
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
