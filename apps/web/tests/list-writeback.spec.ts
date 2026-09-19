import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test.beforeEach(() => {
  execFileSync("uv", ["run", "python", "scripts/e2e_auth_budget.py"], {
    cwd: fileURLToPath(new URL("../../../", import.meta.url)),
    stdio: "pipe",
  });
});

test("Hardcover write-back confirms membership, reconciles lost responses and reviews conflicts", async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000);
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.request.post("http://127.0.0.1:13379/fixture/writeback", {
    data: { reset: true },
  });
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Lists", exact: true }).click();
  await page
    .getByLabel("Create a private list")
    .fill("Hardcover two-way shelf");
  await page.getByRole("button", { name: "Create list", exact: true }).click();
  await page.getByRole("link", { name: /Hardcover two-way shelf/ }).click();
  await expect(
    page.getByRole("heading", { name: "Hardcover two-way shelf" }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "List provider", exact: true })
    .selectOption("hardcover");
  const subscription = page.getByRole("region", {
    name: "Hardcover list subscription",
  });
  await subscription
    .getByLabel("Hardcover list ID", { exact: true })
    .fill("92");
  await subscription
    .getByRole("button", { name: "Follow shelf", exact: true })
    .click();
  await expect(
    subscription
      .getByRole("status")
      .filter({ hasText: "Hardcover list verified: 1 books" }),
  ).toBeVisible({ timeout: 45_000 });
  const listId = page.url().split("/").pop()!;
  const list = await (await page.request.get(`/api/lists/${listId}`)).json();
  const title = list.items[0].title as string;
  await subscription
    .getByText("Sync local changes back to Hardcover", { exact: true })
    .click();
  const panel = subscription.locator(".writeback-controls");
  await expect(
    panel.getByText("Write-back off", { exact: true }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Review enablement" }).click();
  await expect(panel).toContainText("Write-back fixture list");
  await panel.getByRole("button", { name: "Enable future changes" }).click();
  await expect(
    panel.getByText("Write-back enabled", { exact: true }),
  ).toBeVisible();
  const remote = async () =>
    (await page.request.get("http://127.0.0.1:13379/fixture/writeback")).json();
  expect((await remote()).writes).toHaveLength(0);
  await page.request.post("http://127.0.0.1:13379/fixture/writeback", {
    data: { lose_response: true },
  });
  const books = page.getByRole("region", { name: "List books", exact: true });
  await books
    .getByRole("button", { name: `Remove ${title} from list`, exact: true })
    .click();
  await expect(panel.locator(".writeback-change").first()).toContainText(
    "completed",
    { timeout: 45_000 },
  );
  expect((await remote()).writes).toHaveLength(1);
  expect((await remote()).members).toHaveLength(0);

  const addFromCatalog = async () => {
    await books
      .getByRole("button", { name: "Add books from catalog", exact: true })
      .click();
    const picker = page.getByRole("region", {
      name: "Add catalog books",
      exact: true,
    });
    await picker.getByLabel("Find catalog books", { exact: true }).fill(title);
    await picker
      .getByRole("button", { name: "Search catalog", exact: true })
      .click();
    await picker
      .getByRole("checkbox", { name: `Add ${title}`, exact: true })
      .check();
    await picker
      .getByRole("button", {
        name: "Add selected catalog books (1)",
        exact: true,
      })
      .click();
    await expect(
      books.getByRole("button", {
        name: `Remove ${title} from list`,
        exact: true,
      }),
    ).toBeVisible();
    await books
      .getByRole("button", { name: "Close catalog picker", exact: true })
      .click();
  };
  await addFromCatalog();
  await expect(panel.locator(".writeback-change")).toHaveCount(2);
  await expect(panel.locator(".writeback-change").first()).toContainText(
    "completed",
    { timeout: 45_000 },
  );
  expect((await remote()).writes).toHaveLength(2);
  expect((await remote()).members).toHaveLength(1);

  // A different upstream membership episode must be explicitly reviewed.
  await page.request.post("http://127.0.0.1:13379/fixture/writeback", {
    data: { readd: true },
  });
  await books
    .getByRole("button", { name: `Remove ${title} from list`, exact: true })
    .click();
  const conflict = panel
    .locator(".writeback-change")
    .filter({ hasText: "attention" });
  await expect(conflict).toHaveCount(1, { timeout: 45_000 });
  expect((await remote()).writes).toHaveLength(2);
  await conflict.getByRole("button", { name: "Review difference" }).click();
  const review = panel.getByRole("region", {
    name: "Review Hardcover membership",
  });
  await expect(review).toContainText("Local list: absent. Hardcover: present");
  await page.screenshot({
    path: testInfo.outputPath("writeback-review-desktop.png"),
    fullPage: true,
  });
  await review.getByRole("button", { name: "Apply local state" }).click();
  await expect(panel.locator(".writeback-change")).toHaveCount(4);
  await expect(panel.locator(".writeback-change").first()).toContainText(
    "completed",
    { timeout: 45_000 },
  );
  expect(
    (await remote()).writes.map((row: { action: string }) => row.action),
  ).toEqual(["remove", "add", "remove"]);
  expect((await remote()).members).toHaveLength(0);

  await panel.getByRole("button", { name: "Pause write-back" }).click();
  await expect(
    panel.getByText("Write-back off", { exact: true }),
  ).toBeVisible();
  await addFromCatalog();
  await expect(panel.locator(".writeback-change")).toHaveCount(4);
  expect((await remote()).writes).toHaveLength(3);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("writeback-mobile.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
});
