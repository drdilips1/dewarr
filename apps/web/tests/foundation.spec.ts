import { expect, test } from "@playwright/test";

test("setup, catalog, private list and durable worker are usable together", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
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
  await expect(
    page.getByRole("status").filter({ hasText: "Added to your list." }),
  ).toBeVisible();
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
  await page
    .getByText("Advanced provider preferences", { exact: true })
    .click();
  const editionLookup = page.getByRole("checkbox", {
    name: /Look up missing editions before automatic import/,
  });
  await expect(editionLookup).toBeChecked();
  await editionLookup.uncheck();
  await page.getByRole("button", { name: "Save metadata defaults" }).click();
  await expect(
    page.getByText("Metadata defaults saved.", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await page
    .getByText("Advanced provider preferences", { exact: true })
    .click();
  await expect(editionLookup).not.toBeChecked();
  await editionLookup.check();
  await page.getByRole("button", { name: "Save metadata defaults" }).click();
  await expect(
    page.getByText("Metadata defaults saved.", { exact: true }),
  ).toBeVisible();
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
  await page.getByLabel("Download path", { exact: true }).fill("completed");
  await page
    .getByLabel(
      "The download has finished and its files are no longer changing",
    )
    .check();
  await page
    .getByRole("button", { name: "Inspect files", exact: true })
    .click();
  const inspected = page.getByRole("region", { name: "Inspected download" });
  await expect(inspected).toContainText("1 file inspected · 1 book group");
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
  await expect(inspected).toContainText("1 file inspected · 0 book groups");
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
  await expect(inspected).toContainText("1 file inspected · 1 book group");
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
  await expect(
    inspected.getByLabel("Include selected catalog covers in new imports"),
  ).toBeChecked();
  await inspected.getByRole("button", { name: "Save import plan" }).click();
  const savedPlan = page.getByRole("article", { name: "Saved import plan" });
  await expect(savedPlan).toContainText(
    "1 planned item folders · 0 need attention",
  );
  await page.reload();
  await expect(savedPlan).toContainText("book.epub → ebooks/");
  await expect(savedPlan).toContainText(
    "0 selected covers. Unavailable artwork is reported without blocking the book import.",
  );
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
  const automaticPolicy = page.getByRole("region", {
    name: "Automatic import policy",
  });
  await expect(automaticPolicy).toContainText("Automatic importing is off");
  await automaticPolicy
    .getByRole("button", { name: "Enable automatic import", exact: true })
    .click();
  await expect(automaticPolicy).toContainText(
    "New completed downloads with clear catalog and file evidence can import automatically",
  );
  await page.reload();
  await automaticPolicy
    .getByRole("button", { name: "Disable automatic import", exact: true })
    .click();
  await expect(automaticPolicy).toContainText("Automatic importing is off");
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
  await page.request.post("http://127.0.0.1:13379/fixture/watcher", {
    data: { enabled: false },
  });
  await page
    .getByRole("button", { name: "Import resolved books", exact: true })
    .click();
  const stoppedImport = page
    .getByRole("region", { name: "Import result" })
    .first();
  await expect(stoppedImport).toContainText("Needs attention");
  await stoppedImport
    .getByRole("button", { name: "Stop pending import" })
    .click();
  await expect(stoppedImport).toContainText(
    "Import stopped; downloaded files are unchanged",
  );
  await expect(
    stoppedImport.getByRole("link", {
      name: "Review files and create a new plan",
    }),
  ).toHaveAttribute("href", /\/organization\/inspections\?inspection=/);
  await page.reload();
  await expect(stoppedImport).toContainText(
    "Import stopped; downloaded files are unchanged",
  );
  await page.request.post("http://127.0.0.1:13379/fixture/watcher", {
    data: { enabled: true },
  });
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
  await page
    .getByLabel("Download path", { exact: true })
    .fill("matched/book.epub");
  await page
    .getByLabel(
      "The download has finished and its files are no longer changing",
    )
    .check();
  await page
    .getByRole("button", { name: "Inspect files", exact: true })
    .click();
  await expect(inspected).toContainText(
    "One catalog edition agrees with the embedded identity evidence",
  );
  await expect(inspected).toContainText("Only the selected file is included.");

  await inspected
    .getByRole("button", {
      name: "Use clear matches on this page (1)",
      exact: true,
    })
    .click();
  await expect(inspected).toContainText(
    "Selected from catalog evidence: My protected catalog title",
  );
  const completeMatchedBook = inspected.getByLabel(
    "These files contain the complete book, not a sample or companion document",
  );
  await expect(completeMatchedBook).not.toBeChecked();
  await inspected
    .getByRole("button", { name: "Save import plan", exact: true })
    .click();
  await expect(savedPlan).toContainText(
    "0 planned item folders · 1 need attention",
  );
  await completeMatchedBook.check();
  await inspected
    .getByRole("button", { name: "Refresh catalog matches", exact: true })
    .click();
  await expect(completeMatchedBook).toBeChecked();
  await expect(
    inspected.getByRole("button", {
      name: "Use clear matches on this page (0)",
      exact: true,
    }),
  ).toBeDisabled();
  const matchedPlanResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/plans") &&
      response.request().method() === "POST",
  );
  await inspected
    .getByRole("button", { name: "Save import plan", exact: true })
    .click();
  const matchedPlan = await (await matchedPlanResponse).json();
  expect(matchedPlan.document.source.source_kind).toBe("file");
  expect(matchedPlan.document.source.relative_path).toBe("matched/book.epub");
  const matchProof =
    matchedPlan.document.matching_evidence[matchedPlan.document.groups[0].id];
  expect(matchProof.status).toBe("matched");
  expect(matchProof.evidence.identifiers).toEqual([
    { namespace: "isbn", value: "9781234567897" },
  ]);
  await expect(savedPlan).toContainText(
    "1 planned item folders · 0 need attention",
  );
  await page.screenshot({
    path: testInfo.outputPath("catalog-match-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.reload();
  await expect(savedPlan).toContainText(
    "1 planned item folders · 0 need attention",
  );
  await page.getByLabel("Download path", { exact: true }).fill("formats");
  await page
    .getByLabel(
      "The download has finished and its files are no longer changing",
    )
    .check();
  await page
    .getByRole("button", { name: "Inspect files", exact: true })
    .click();
  await expect(inspected).toContainText("2 files inspected · 2 book groups");
  await inspected
    .getByRole("button", { name: "Review file groups", exact: true })
    .click();
  const editionGroup = await groupEditor
    .getByRole("combobox", { name: "Book group for book.epub", exact: true })
    .inputValue();
  await groupEditor
    .getByRole("combobox", { name: "Book group for book.pdf", exact: true })
    .selectOption(editionGroup);
  const editionConfirmation = groupEditor.getByRole("checkbox", {
    name: /different formats of the same complete ebook edition/,
  });
  await expect(editionConfirmation).not.toBeChecked();
  await groupEditor
    .getByRole("button", { name: "Save file groups", exact: true })
    .click();
  await expect(groupEditor).toContainText(
    "Confirm that these ebook formats contain the same complete edition",
  );
  await editionConfirmation.check();
  await groupEditor
    .getByRole("button", { name: "Save file groups", exact: true })
    .click();
  await expect(inspected).toContainText("2 files inspected · 1 book group");
  await expect(inspected).toContainText(
    "Reviewed as multiple formats of one complete edition",
  );
  await page.reload();
  await inspected
    .getByRole("button", { name: "Review file groups", exact: true })
    .click();
  await expect(editionConfirmation).toBeChecked();
  const reviewedEditionGroup = await groupEditor
    .getByRole("combobox", { name: "Book group for book.epub", exact: true })
    .inputValue();
  await groupEditor
    .getByRole("combobox", { name: "Book group for book.pdf", exact: true })
    .selectOption("__new__");
  await groupEditor
    .getByRole("combobox", { name: "Book group for book.pdf", exact: true })
    .selectOption(reviewedEditionGroup);
  await expect(editionConfirmation).not.toBeChecked();
  await groupEditor
    .getByRole("button", { name: "Cancel group changes" })
    .click();
  await page.getByLabel("Download path", { exact: true }).fill("companion");
  await page
    .getByLabel(
      "The download has finished and its files are no longer changing",
    )
    .check();
  await page
    .getByRole("button", { name: "Inspect files", exact: true })
    .click();
  await expect(inspected).toContainText("2 files inspected · 2 book groups");
  await inspected
    .getByRole("button", { name: "Review file groups", exact: true })
    .click();
  const audioGroup = await groupEditor
    .getByRole("combobox", { name: "Book group for book.mp3", exact: true })
    .inputValue();
  await groupEditor
    .getByRole("combobox", { name: "Book group for notes.pdf", exact: true })
    .selectOption(audioGroup);
  await groupEditor
    .getByRole("combobox", { name: /File role for notes.pdf/ })
    .selectOption("supplement");
  await page.screenshot({
    path: testInfo.outputPath("companion-review-mobile.png"),
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
  await expect(inspected).toContainText("2 files inspected · 1 book group");
  await page.reload();
  await inspected
    .getByRole("button", { name: "Review file groups", exact: true })
    .click();
  await expect(
    groupEditor.getByRole("combobox", { name: /File role for notes.pdf/ }),
  ).toHaveValue("supplement");
  await groupEditor
    .getByRole("button", { name: "Cancel group changes" })
    .click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("link", { name: "Sources", exact: true }).click();
  await page
    .getByText("MAM connection · not-configured", { exact: true })
    .click();
  const mamConnection = page.getByRole("form", {
    name: "MAM connection settings",
  });
  await mamConnection
    .getByLabel("MAM URL", { exact: true })
    .fill("http://127.0.0.1:13379/mam");
  await mamConnection
    .getByLabel("mam_id", { exact: true })
    .fill("browser-mam-fixture");
  await mamConnection
    .getByRole("button", { name: "Save MAM connection", exact: true })
    .click();
  await expect(mamConnection.getByLabel("mam_id", { exact: true })).toHaveValue(
    "",
  );
  await mamConnection
    .getByRole("button", { name: "Test saved connection", exact: true })
    .click();
  await expect(mamConnection).toContainText("Connection: connected");
  await page
    .getByLabel("Search title, author or series", { exact: true })
    .fill("Harbor Stories");
  await page
    .getByRole("button", { name: "Search source", exact: true })
    .click();
  const sourceResults = page.getByRole("region", {
    name: "MAM results",
    exact: true,
  });
  await expect(sourceResults).toContainText(
    "Harbor & Roads — Complete Stories",
  );
  await expect(sourceResults).toContainText("42 seeders");
  await expect(sourceResults).toContainText("321 snatches");
  await sourceResults
    .getByRole("button", { name: "View source details", exact: true })
    .click();
  const mamDetails = sourceResults.getByRole("region", {
    name: "Details for Harbor & Roads — Complete Stories",
    exact: true,
  });
  await expect(mamDetails).toContainText("Harbor Stories · 1-3");
  await expect(mamDetails).toContainText("An invented three-book collection.");
  await expect(mamDetails).not.toContainText("unsafe()");
  await expect(mamDetails).not.toContainText("fixture-private-download-token");
  await expect(
    mamDetails.getByText("Refreshing source details…", { exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("mam-search-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("mam-search-mobile.png"),
    fullPage: true,
  });
  await mamDetails
    .getByRole("button", { name: "Inspect torrent manifest", exact: true })
    .click();
  await mamDetails
    .getByRole("link", { name: "View saved manifest", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Torrent manifest", exact: true }),
  ).toBeVisible();
  const torrentFiles = page.getByRole("list", {
    name: "Torrent files",
    exact: true,
  });
  await expect(torrentFiles).toContainText("Harbor Stories/01 - Harbor.m4b");
  await expect(torrentFiles).toContainText("Harbor Stories/02 - Roads.m4b");
  await expect(page.getByRole("main")).not.toContainText(
    "fixture-private-download-token",
  );
  await expect(page.getByRole("main")).not.toContainText(
    "private-fixture-passkey",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("torrent-manifest-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await expect(torrentFiles).toContainText("Harbor Stories/02 - Roads.m4b");
  await page.screenshot({
    path: testInfo.outputPath("torrent-manifest-desktop.png"),
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Return to source search", exact: true })
    .click();
  await page
    .getByLabel("Search title, author or series", { exact: true })
    .fill("No source matches");
  await page
    .getByRole("button", { name: "Search source", exact: true })
    .click();
  await expect(sourceResults).toContainText("No matching releases");
  await page.reload();
  await page.getByText("MAM connection · connected", { exact: true }).click();
  await expect(mamConnection.getByLabel("mam_id", { exact: true })).toHaveValue(
    "",
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("link", { name: "Connections", exact: true }).click();
  await page.getByRole("link", { name: "Downloaders", exact: true }).click();
  await page
    .getByRole("button", { name: "Connect qBittorrent", exact: true })
    .click();
  const downloaderForm = page.getByRole("form", {
    name: "qBittorrent connection settings",
  });
  await downloaderForm
    .getByLabel("qBittorrent URL", { exact: true })
    .fill("http://127.0.0.1:13379/qbit");
  await downloaderForm
    .getByLabel("qBittorrent username", { exact: true })
    .fill("browser-qbit-user");
  await downloaderForm
    .getByLabel("qBittorrent password", { exact: true })
    .fill("browser-qbit-password");
  await downloaderForm
    .getByRole("button", { name: "Save downloader", exact: true })
    .click();
  const downloaderCard = page.getByRole("article", {
    name: "qBittorrent",
    exact: true,
  });
  await expect(downloaderCard).toBeVisible();
  await downloaderCard
    .getByRole("button", { name: "Test saved connection", exact: true })
    .click();
  await expect(downloaderCard).toContainText("connected");
  await expect(downloaderCard).toContainText("v5.2.3");
  await downloaderCard
    .getByText("Preview path mapping", { exact: true })
    .click();
  await downloaderCard
    .getByLabel("Path in qBittorrent", { exact: true })
    .fill("/downloads/books/Example/book.m4b");
  await downloaderCard
    .getByRole("button", { name: "Preview saved mapping", exact: true })
    .click();
  await expect(downloaderCard).toContainText(
    "Relative path: books/Example/book.m4b",
  );
  await expect(downloaderCard).toContainText("Mapping preview only");
  await page.screenshot({
    path: testInfo.outputPath("downloaders-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("downloaders-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("link", { name: "Catalog", exact: true }).click();
  await page.getByRole("button", { name: "Add a title", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("The Next Harbor");
  await page.getByLabel("Author", { exact: true }).fill("Alex Morgan");
  await page.getByRole("button", { name: "Save title", exact: true }).click();
  await page.getByRole("link", { name: /^The Next Harbor/ }).click();
  const nextWanted = page.getByRole("region", {
    name: "Wanted media",
    exact: true,
  });
  await nextWanted
    .getByRole("combobox", { name: "Media to request", exact: true })
    .selectOption("ebook");
  await nextWanted
    .getByRole("button", { name: "Save to wanted", exact: true })
    .click();
  await nextWanted
    .getByRole("link", { name: "Choose a source release", exact: true })
    .click();
  await expect(
    page.getByLabel("Release search query", { exact: true }),
  ).toHaveValue("The Next Harbor");
  await page
    .getByRole("region", { name: "Book download sources", exact: true })
    .getByRole("button", { name: "Inspect this release", exact: true })
    .click();
  const selectionForm = page.getByRole("region", {
    name: "Release selection",
    exact: true,
  });
  await expect(
    selectionForm.getByRole("combobox", { name: "Wanted book", exact: true }),
  ).not.toHaveValue("");
  await selectionForm
    .getByRole("checkbox", {
      name: "I checked the release details and it contains The Next Harbor.",
      exact: true,
    })
    .check();
  await selectionForm
    .getByRole("button", { name: "Save release selection", exact: true })
    .click();
  await expect(selectionForm.getByRole("status")).toHaveText(
    "Release selection saved. No download has been started.",
  );
  await page.reload();
  await expect(selectionForm).toContainText(
    "Release selected; download not started",
  );
  await page.screenshot({
    path: testInfo.outputPath("release-selection-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("release-selection-mobile.png"),
    fullPage: true,
  });
  await selectionForm
    .getByRole("button", { name: "Cancel selection", exact: true })
    .click();
  await expect(selectionForm).toContainText(
    "Release selection cancelled; no download was started",
  );
  await selectionForm
    .getByRole("checkbox", {
      name: "I checked the release details and it contains The Next Harbor.",
      exact: true,
    })
    .check();
  await selectionForm
    .getByRole("button", { name: "Save release selection", exact: true })
    .click();
  await selectionForm
    .getByRole("button", { name: "Start download", exact: true })
    .click();
  await selectionForm
    .getByRole("link", { name: "View download", exact: true })
    .click();
  const downloadActivity = page.getByRole("region", {
    name: "Downloads",
    exact: true,
  });
  await expect(downloadActivity).toContainText(
    "Transfer associated; waiting for complete files",
  );
  await expect(downloadActivity).toContainText("25% downloaded");
  await expect(
    downloadActivity.getByRole("button", { name: "Cancel before submission" }),
  ).toHaveCount(0);
  await page.reload();
  await expect(downloadActivity).toContainText("The Next Harbor");
  await page.screenshot({
    path: testInfo.outputPath("download-activity-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: testInfo.outputPath("download-activity-desktop.png"),
    fullPage: true,
  });

  await page.getByRole("link", { name: "Connections", exact: true }).click();
  await page.getByRole("link", { name: "Downloaders", exact: true }).click();
  await page.reload();
  await downloaderCard
    .getByRole("button", { name: "Edit downloader", exact: true })
    .click();
  await expect(
    downloaderForm.getByLabel("qBittorrent username", { exact: true }),
  ).toHaveValue("");
  await expect(
    downloaderForm.getByLabel("qBittorrent password", { exact: true }),
  ).toHaveValue("");
  await downloaderForm
    .getByRole("button", { name: "Save downloader", exact: true })
    .click();
  await downloaderCard
    .getByRole("button", { name: "Test saved connection", exact: true })
    .click();
  await expect(downloaderCard).toContainText("connected");
  await page.getByRole("link", { name: "Activity", exact: true }).click();
  await downloadActivity
    .getByRole("button", { name: "Review updated connections" })
    .click();
  const repairReview = downloadActivity.getByRole("region", {
    name: "Review updated download connections",
  });
  await expect(repairReview).toContainText("updated qBittorrent connection");
  await page.screenshot({
    path: testInfo.outputPath("download-repair-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("download-repair-mobile.png"),
    fullPage: true,
  });
  await repairReview
    .getByRole("button", { name: "Confirm and check existing transfer" })
    .click();
  await expect(downloadActivity).toContainText(
    "Updated connections verified against the existing transfer",
  );
  await expect(downloadActivity).toContainText("25% downloaded");
  await page.reload();
  await expect(downloadActivity).toContainText("no download was added");
  await page.getByRole("link", { name: "Connections", exact: true }).click();
  await page.getByRole("link", { name: "Downloaders", exact: true }).click();
  await downloaderCard
    .getByRole("button", { name: "Edit downloader", exact: true })
    .click();
  await downloaderForm
    .getByLabel("Enable connection", { exact: true })
    .uncheck();
  await downloaderForm
    .getByRole("button", { name: "Save downloader", exact: true })
    .click();
  await expect(downloaderCard).toContainText("Disabled");
  await expect(
    downloaderCard.getByRole("button", {
      name: "Test saved connection",
      exact: true,
    }),
  ).toBeDisabled();
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

test("administrator review queue retries a command and shows its assigned inspection", async ({
  page,
}, testInfo) => {
  // UI contract fixture; the PostgreSQL/file suite exercises real claims and publication.
  const attempt = "a8c84f97-b555-4843-a10d-10bf505e774b";
  const inspection = "fc7cc890-65d5-4bdb-98ef-d19481a5db56";
  let assigned = false;
  const keys: string[] = [];
  const row = () => ({
    attempt_id: attempt,
    work_title: "Member review fixture",
    medium: "audio",
    message: assigned
      ? "Assigned to you"
      : "Ready for administrator inspection",
    revision: (assigned ? "b" : "a").repeat(64),
    inspection_id: assigned ? inspection : null,
    can_claim: !assigned,
    reassignment: assigned,
    retry: false,
  });
  await page.route("**/api/acquisition/reviews?*", (route) =>
    route.fulfill({
      json: { items: [row()], total: 1, offset: 0, limit: 10 },
    }),
  );
  await page.route(
    `**/api/acquisition/reviews/${attempt}/claim`,
    async (route) => {
      keys.push(route.request().headers()["idempotency-key"]);
      if (keys.length === 1) {
        await route.fulfill({
          status: 503,
          json: { detail: "Temporary review connection failure" },
        });
      } else {
        assigned = true;
        await route.fulfill({ status: 202, json: row() });
      }
    },
  );
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Activity", exact: true }).click();
  const review = page.getByRole("region", { name: "Download import reviews" });
  await review.getByRole("button", { name: "Review this download" }).click();
  await expect(review).toContainText("Temporary review connection failure");
  await review.getByRole("button", { name: "Review this download" }).click();
  await expect(review).toContainText("Assigned to you");
  await expect(
    review.getByRole("link", { name: "Open file review" }),
  ).toHaveAttribute(
    "href",
    `/organization/inspections?inspection=${inspection}`,
  );
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  await page.reload();
  await expect(review).toContainText("Assigned to you");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("download-review-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByLabel("Username", { exact: true }).fill("guest");
  await page
    .getByLabel("Password", { exact: true })
    .fill("guest reader password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Activity", exact: true }).click();
  await expect(review).toHaveCount(0);
});

test("Prowlarr sources retain successful results beside an outage and inspect through the shared manifest", async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your catalog", exact: true }),
  ).toBeVisible();
  await page.goto("/sources/prowlarr");
  await page
    .getByText("Prowlarr connection · not-configured", { exact: true })
    .click();
  await page
    .getByLabel("Server URL", { exact: true })
    .fill("http://127.0.0.1:13379/prowlarr");
  await page
    .getByLabel("API key", { exact: true })
    .fill("browser-prowlarr-key");
  await page
    .getByRole("button", { name: "Save connection", exact: true })
    .click();
  await expect(page.getByLabel("API key", { exact: true })).toHaveValue("");
  await expect(page.getByLabel(/MAM duplicate/)).toBeDisabled();
  await page
    .getByLabel("Title, author or series", { exact: true })
    .fill("Prowlarr browser");
  await page
    .getByRole("button", { name: "Search sources", exact: true })
    .click();
  const successful = page.getByRole("region", {
    name: "Book tracker results",
    exact: true,
  });
  await expect(
    successful.getByRole("heading", { name: "Prowlarr browser audiobook" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Unavailable tracker results" }),
  ).toContainText("Prowlarr could not complete this request");
  await expect(
    page
      .getByRole("region", { name: "NZB books results" })
      .getByRole("button", { name: "Inspect torrent" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Search sources", exact: true }),
  ).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("prowlarr-mobile.png"),
    fullPage: true,
  });
  await successful.getByRole("button", { name: "Inspect torrent" }).click();
  await expect(
    page.getByRole("heading", { name: "Torrent manifest", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("PROWLARR RELEASE", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Torrent manifest", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Return to source search" }),
  ).toHaveAttribute("href", /sources\/prowlarr/);
  await expect(page.locator("body")).not.toContainText("private_fixture");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});

test("book sources aggregate durable results and apply saved release preferences", async ({
  page,
}, testInfo) => {
  test.setTimeout(75_000);
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: "Add a title" }).click();
  await page
    .getByLabel("Title", { exact: true })
    .fill("Harbor & Roads — Complete Stories");
  await page.getByLabel("Author", { exact: true }).fill("Alex Morgan");
  await page.getByRole("button", { name: "Save title" }).click();
  await page
    .getByRole("link", { name: /Harbor & Roads — Complete Stories/ })
    .click();
  await page
    .getByRole("link", { name: "Search download sources", exact: true })
    .click();
  const sources = page.getByRole("region", { name: "Book download sources" });
  const mam = sources.getByRole("article", {
    name: "Harbor & Roads — Complete Stories",
    exact: true,
  });
  await expect(mam).toBeVisible();
  await expect(
    sources.getByRole("article", {
      name: "Prowlarr browser audiobook",
      exact: true,
    }),
  ).toBeVisible();
  await expect(sources.getByRole("status")).toContainText(
    "Search finished with source errors",
    { timeout: 25_000 },
  );
  await mam.getByText("Why this ranking?", { exact: true }).click();
  await expect(mam).toContainText(
    "Source title and author agree with the catalog",
  );
  await expect(mam).toContainText("Jordan Lee");
  await page.reload();
  await expect(mam).toBeVisible();
  await sources
    .getByText("Customize download preferences", { exact: true })
    .click();
  await sources
    .getByLabel("Profile name", { exact: true })
    .fill("Most seeded audio");
  await sources
    .getByRole("button", {
      name: "Move seeders up in Ranking priorities",
      exact: true,
    })
    .click();
  await sources
    .getByRole("button", {
      name: "Move seeders up in Ranking priorities",
      exact: true,
    })
    .click();
  await sources
    .getByText("Formats and transfer limits", { exact: true })
    .click();
  await sources.getByLabel("M4B", { exact: true }).check();
  await sources
    .getByRole("button", { name: "Create profile", exact: true })
    .click();
  await expect(
    sources.getByRole("combobox", { name: "Download profile", exact: true }),
  ).toHaveValue(/.+/);
  await sources
    .getByRole("button", { name: "Refresh source results", exact: true })
    .click();
  await expect(
    mam.getByText("Blocked format: m4b", { exact: true }),
  ).toBeVisible({ timeout: 25_000 });
  await expect(
    mam.getByRole("button", { name: "Inspect this release" }),
  ).toBeDisabled();
  await expect(sources.getByRole("status")).toContainText(
    "Search finished with source errors",
    { timeout: 25_000 },
  );
  await page.reload();
  await expect(
    sources.getByRole("combobox", { name: "Download profile", exact: true }),
  ).toHaveValue(/.+/);
  await expect(
    mam.getByText("Blocked format: m4b", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("book-sources-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});

test("Goodreads shelf observation persists additions, omissions, exclusions and pause settings", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page
    .getByLabel("Create a private list")
    .fill("Followed Goodreads Shelf");
  await page.getByRole("button", { name: "Create list", exact: true }).click();
  await page.getByRole("link", { name: /Followed Goodreads Shelf/ }).click();
  const panel = page.getByRole("region", {
    name: "Goodreads shelf subscription",
  });
  await panel
    .getByLabel("Goodreads RSS URL")
    .fill(
      "https://www.goodreads.com/review/list_rss/123?key=private-browser-feed-key&shelf=to-read",
    );
  await panel
    .getByRole("button", { name: "Follow shelf", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("Observed 2 books", {
    timeout: 20_000,
  });
  await expect(
    page.getByRole("link", { name: /Goodreads Shelf Arrival/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Remove Goodreads Shelf Arrival from list" })
    .click();
  await expect(
    page.getByRole("link", { name: /Goodreads Shelf Arrival/ }),
  ).toHaveCount(0);
  await page.request.post("http://127.0.0.1:13379/goodreads/control", {
    data: { mode: "omission", version: 2 },
  });
  await panel
    .getByRole("button", { name: "Refresh Goodreads shelf", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("Observed 1 books", {
    timeout: 80_000,
  });
  await page.reload();
  await expect(panel).toContainText("2 observed · 1 excluded");
  await panel
    .getByText("Observed entries and exclusions", { exact: true })
    .click();
  const entry = panel.getByRole("article", {
    name: "Shelf entry: Goodreads Shelf Arrival",
  });
  await expect(entry).toBeVisible();
  await entry.getByRole("button", { name: "Restore to this list" }).click();
  await expect(panel).toContainText("2 observed · 0 excluded");
  await panel
    .getByText("Observed entries and exclusions", { exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: /Goodreads Shelf Arrival/ }),
  ).toBeVisible();
  await page.request.post("http://127.0.0.1:13379/goodreads/control", {
    data: { mode: "addition", version: 3 },
  });
  await panel
    .getByRole("button", { name: "Refresh Goodreads shelf", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Observed 3 books; 1 new",
    { timeout: 80_000 },
  );
  await expect(
    page.getByRole("link", { name: /Goodreads Later Addition/ }),
  ).toBeVisible();
  await panel.getByText("Shelf connection settings", { exact: true }).click();
  await expect(panel.getByLabel("Goodreads RSS URL")).toHaveValue("");
  await panel.getByLabel("Observe shelf additions").uncheck();
  await panel.getByRole("button", { name: "Save shelf settings" }).click();
  await expect(panel.getByRole("status")).toContainText("Observation paused");
  await page.reload();
  await expect(
    panel.getByRole("button", { name: "Refresh Goodreads shelf" }),
  ).toBeDisabled();
  await expect(page.locator("body")).not.toContainText(
    "private-browser-feed-key",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("goodreads-shelf-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});

test("CSV snapshots preview mapped columns, import selected shelves and retain receipts", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page.getByLabel("Create a private list").fill("CSV curated shelf");
  await page.getByRole("button", { name: "Create list", exact: true }).click();
  await page.getByRole("link", { name: /CSV curated shelf/ }).click();
  await page.getByRole("button", { name: "Import a CSV", exact: true }).click();
  const panel = page.getByRole("region", { name: "CSV list import" });
  const content =
    "Name,Creator,Book Id,Bookshelves,Private Notes\r\nCSV Café,Fixture Author,901,favorites,private-browser-note\r\nCSV Other Book,Fixture Author,902,later,another-private-note\r\nCSV Café,Fixture Author,901,favorites,duplicate-private-note\r\n";
  const file = {
    name: "shelf.csv",
    mimeType: "text/csv",
    buffer: Buffer.concat([
      Buffer.from([0xff, 0xfe]),
      Buffer.from(content, "utf16le"),
    ]),
  };
  await panel.getByLabel("CSV file", { exact: true }).setInputFiles(file);
  await panel.getByRole("button", { name: "Preview CSV", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText(
    "Choose the title column",
  );
  await panel.getByText("File format and columns", { exact: true }).click();
  await panel
    .getByRole("combobox", { name: "Title column", exact: true })
    .selectOption("Name");
  await panel
    .getByRole("combobox", { name: "Author column", exact: true })
    .selectOption("Creator");
  await panel.getByRole("button", { name: "Preview CSV", exact: true }).click();
  await expect(
    panel.getByText(/2 unique rows · 1 duplicate rows combined/),
  ).toBeVisible();
  await panel.getByLabel("Filter CSV shelf").selectOption("favorites");
  await panel
    .getByRole("button", { name: "Select this shelf only", exact: true })
    .click();
  await expect(
    panel.getByText("1 books selected across all shelves."),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Import 1 selected books", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "CSV imported: 1 added",
    { timeout: 20_000 },
  );
  await expect(
    page.getByRole("heading", { name: "CSV Café", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "CSV Other Book", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("private-browser-note");
  await page.reload();
  await page.getByRole("button", { name: "Import a CSV", exact: true }).click();
  await panel
    .getByText("Recent CSV previews and imports", { exact: true })
    .click();
  await panel
    .getByRole("button", {
      name: /CSV imported: 1 added, 0 already listed · completed/,
    })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "CSV imported: 1 added",
  );
  await panel.getByLabel("CSV file", { exact: true }).setInputFiles({
    name: "repeat.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Book Id,Title,Author\n901,CSV Café,Fixture Author\n"),
  });
  await panel.getByRole("button", { name: "Preview CSV", exact: true }).click();
  await expect(
    panel.getByRole("link", { name: "Matched catalog book", exact: true }),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Import 1 selected books", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "CSV imported: 0 added, 1 already listed",
    { timeout: 20_000 },
  );
  await expect(
    page.getByRole("heading", { name: "CSV Café", exact: true }),
  ).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("csv-list-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});

test("Hardcover lists verify pages before syncing and retain exclusions after source changes", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page
    .getByLabel("Create a private list")
    .fill("Hardcover curated shelf");
  await page.getByRole("button", { name: "Create list", exact: true }).click();
  await page.getByRole("link", { name: /Hardcover curated shelf/ }).click();
  await page
    .getByRole("combobox", { name: "List provider", exact: true })
    .selectOption("hardcover");
  const panel = page.getByRole("region", {
    name: "Hardcover list subscription",
  });
  await expect(
    panel.getByRole("combobox", { name: "Choose a Hardcover list" }),
  ).toContainText("Fixture Hardcover List");
  await panel
    .getByRole("combobox", { name: "Choose a Hardcover list" })
    .selectOption("91");
  await panel
    .getByRole("button", { name: "Follow shelf", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Hardcover list verified: 2 books",
    { timeout: 40_000 },
  );
  await expect(
    page.getByRole("link", { name: /Hardcover List Arrival/ }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Remove Hardcover List Arrival from list",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("link", { name: /Hardcover List Arrival/ }),
  ).toHaveCount(0);
  await page.request.post("http://127.0.0.1:13379/fixture/hardcover-list", {
    data: { mode: "omission" },
  });
  await panel
    .getByRole("button", { name: "Refresh Hardcover list", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Hardcover list verified: 1 books",
    { timeout: 40_000 },
  );
  await page.request.post("http://127.0.0.1:13379/fixture/hardcover-list", {
    data: { mode: "addition" },
  });
  await panel
    .getByRole("button", { name: "Refresh Hardcover list", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Hardcover list verified: 3 books",
    { timeout: 40_000 },
  );
  await expect(
    page.getByRole("link", { name: /Hardcover Later Arrival/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Hardcover List Arrival/ }),
  ).toHaveCount(0);
  await panel.getByText("Shelf connection settings", { exact: true }).click();
  await panel.getByLabel("Observe shelf additions").uncheck();
  await panel
    .getByRole("button", { name: "Save shelf settings", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText("Observation paused");
  await page.reload();
  await expect(panel.getByRole("status")).toContainText("Observation paused");
  await expect(page.locator("body")).not.toContainText(
    "browser-hardcover-token",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("hardcover-list-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});

test("list batches preview media, cancel before saving, and persist wanted receipts", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page.getByLabel("Create a private list").fill("Batch wanted reading");
  await page.getByRole("button", { name: "Create list", exact: true }).click();
  for (const title of ["Batch Harbor", "Batch Mountain"]) {
    await page.getByRole("link", { name: "Catalog", exact: true }).click();
    await page
      .getByRole("button", { name: "Add a title", exact: true })
      .click();
    await page.getByLabel("Title", { exact: true }).fill(title);
    await page.getByLabel("Author", { exact: true }).fill("Batch Author");
    await page.getByRole("button", { name: "Save title", exact: true }).click();
    await page.getByRole("link", { name: new RegExp(title) }).click();
    await page
      .getByLabel("Reading list")
      .selectOption({ label: "Batch wanted reading" });
    await page
      .getByRole("button", { name: "Add to list", exact: true })
      .click();
    await expect(
      page.getByRole("status").filter({ hasText: "Added to your list." }),
    ).toBeVisible();
  }
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page.getByRole("link", { name: /Batch wanted reading/ }).click();
  await page
    .getByRole("button", { name: "Request books", exact: true })
    .click();
  const panel = page.getByRole("region", { name: "List wanted media" });
  await panel
    .getByRole("button", { name: "Select this page", exact: true })
    .click();
  await panel
    .getByRole("combobox", { name: "Media to request", exact: true })
    .selectOption("both");
  await panel
    .getByRole("button", { name: "Preview wanted media", exact: true })
    .click();
  await expect(
    panel.getByRole("heading", { name: /Both · 2 selected books/ }),
  ).toBeVisible();
  await expect(panel).toContainText("4 missing");
  await panel
    .getByRole("button", { name: "Cancel this batch", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "no wanted requests were saved",
  );
  await panel
    .getByRole("button", { name: "New selection", exact: true })
    .click();
  await panel
    .getByRole("checkbox", { name: "Batch Mountain", exact: true })
    .uncheck();
  await panel
    .getByRole("button", { name: "Preview wanted media", exact: true })
    .click();
  await expect(
    panel.getByRole("heading", {
      name: "Both · 1 selected book",
      exact: true,
    }),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Save wanted media", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Saved wanted media for 1 book",
    { timeout: 20_000 },
  );
  await expect(panel).toContainText("2 already requested");
  await page.reload();
  await page
    .getByRole("button", { name: "Request books", exact: true })
    .click();
  await panel
    .getByText("Saved previews and request receipts", { exact: true })
    .click();
  await panel.getByRole("button", { name: /1 book · completed/ }).click();
  await expect(panel.getByRole("status")).toContainText(
    "downloads have not been started",
  );
  await expect(
    panel.getByRole("button", { name: "Save wanted media", exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("list-requests-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});

test("wanted list title prepares an eligible release and reloads its saved selection", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Connections", exact: true }).click();
  await page.getByRole("link", { name: "Downloaders", exact: true }).click();
  const downloader = page.getByRole("article", {
    name: "qBittorrent",
    exact: true,
  });
  await downloader
    .getByRole("button", { name: "Edit downloader", exact: true })
    .click();
  const settings = page.getByRole("form", {
    name: "qBittorrent connection settings",
  });
  await settings.getByLabel("Enable connection", { exact: true }).check();
  await settings
    .getByRole("button", { name: "Save downloader", exact: true })
    .click();
  await downloader
    .getByRole("button", { name: "Test saved connection", exact: true })
    .click();
  await expect(downloader).toContainText("connected");
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page.getByRole("link", { name: /Hardcover curated shelf/ }).click();
  await page.getByRole("link", { name: /Hardcover Later Arrival/ }).click();
  const wanted = page.getByRole("region", {
    name: "Wanted media",
    exact: true,
  });
  await wanted
    .getByRole("combobox", { name: "Media to request", exact: true })
    .selectOption("ebook");
  await wanted
    .getByRole("button", { name: "Save to wanted", exact: true })
    .click();
  await wanted
    .getByRole("link", { name: "Choose a source release", exact: true })
    .click();
  const preparation = page.getByRole("region", {
    name: "Automatic release preparation",
    exact: true,
  });
  await expect(preparation).toBeVisible();
  await expect(
    preparation.getByRole("button", {
      name: "Prepare best eligible release",
      exact: true,
    }),
  ).toBeEnabled();
  await preparation
    .getByRole("button", { name: "Prepare best eligible release", exact: true })
    .click();
  await expect(preparation.getByRole("status")).toContainText(
    "Best eligible release prepared",
    { timeout: 25_000 },
  );
  await expect(preparation).toContainText("download has not started");
  await page.reload();
  await expect(preparation.getByRole("status")).toContainText(
    "Best eligible release prepared",
  );
  await preparation.getByText(/Candidate decisions/).click();
  await expect(preparation).toContainText("Eligible torrent prepared");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("automatic-selection-mobile.png"),
    fullPage: true,
  });
  await preparation
    .getByRole("link", { name: "Open prepared release", exact: true })
    .click();
  const saved = page.getByRole("region", {
    name: "Release selection",
    exact: true,
  });
  await expect(saved).toContainText("Hardcover Later Arrival");
  await expect(
    saved.getByRole("button", { name: "Start download", exact: true }),
  ).toBeEnabled();
  await saved
    .getByRole("button", { name: "Start download", exact: true })
    .click();
  await expect(
    saved.getByRole("link", { name: "View download", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    saved.getByRole("link", { name: "View download", exact: true }),
  ).toBeVisible();
  await expect(page.locator("body")).not.toContainText(
    "fixture-private-download-token",
  );
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});

test("installation capacity limits persist and remain usable on mobile", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Connections", exact: true }).click();
  await page.getByRole("link", { name: "Downloaders", exact: true }).click();
  await page.getByText("Transfer and storage limits", { exact: true }).click();
  const settings = page.getByRole("form", {
    name: "Transfer and storage limits",
  });
  await expect(
    settings.getByLabel("Active downloads per downloader"),
  ).toHaveValue("3");
  await expect(
    settings.getByLabel("Automatic transfers per 24 hours"),
  ).toHaveValue("10");
  await settings.getByLabel("Active downloads per downloader").fill("2");
  await settings.getByLabel("Automatic transfers per 24 hours").fill("7");
  await settings.getByLabel("Minimum free storage (GiB)").fill("6");
  await settings.getByLabel("Minimum free storage (%)").fill("6");
  await settings.getByRole("button", { name: "Save capacity limits" }).click();
  await expect(page.getByRole("status")).toContainText("Capacity limits saved");
  await page.reload();
  await page.getByText("Transfer and storage limits", { exact: true }).click();
  await expect(
    settings.getByLabel("Active downloads per downloader"),
  ).toHaveValue("2");
  await expect(
    settings.getByLabel("Automatic transfers per 24 hours"),
  ).toHaveValue("7");
  await expect(settings.getByLabel("Minimum free storage (GiB)")).toHaveValue(
    "6",
  );
  await expect(settings.getByLabel("Minimum free storage (%)")).toHaveValue(
    "6",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("capacity-mobile.png"),
    fullPage: true,
  });
  await settings.getByLabel("Active downloads per downloader").fill("3");
  await settings.getByLabel("Automatic transfers per 24 hours").fill("10");
  await settings.getByLabel("Minimum free storage (GiB)").fill("5");
  await settings.getByLabel("Minimum free storage (%)").fill("5");
  await settings.getByRole("button", { name: "Save capacity limits" }).click();
  await expect(page.getByRole("status")).toContainText("Capacity limits saved");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});
