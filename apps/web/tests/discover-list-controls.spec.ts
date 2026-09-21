import { expect, test } from "./fixtures";

test.beforeEach(async ({ page }) => {
  const bootstrap = await page.request.post("/api/auth/bootstrap", {
    headers: { Origin: "http://127.0.0.1:8001" },
    data: {
      username: "reader",
      display_name: "Reader",
      password: "browser test password",
    },
  });
  const login =
    bootstrap.status() === 201
      ? bootstrap
      : await page.request.post("/api/auth/login", {
          headers: { Origin: "http://127.0.0.1:8001" },
          data: { username: "reader", password: "browser test password" },
        });
  expect(login.ok()).toBeTruthy();
  const auth = await login.json();
  await page.request.put("/api/setup/onboarding", {
    headers: {
      Origin: "http://127.0.0.1:8001",
      "X-CSRF-Token": auth.csrf_token,
    },
    data: { status: "completed", step: 0, skipped: [] },
  });
});

const listId = "00000000-0000-4000-8000-000000000001";
const revision = "a".repeat(64);
const works = Array.from({ length: 101 }, (_, i) => ({
  id: `00000000-0000-4000-9000-${String(i + 1).padStart(12, "0")}`,
  title: `Shelf book ${i + 1}`,
  authors: ["A. Reader"],
  provisional: false,
  cover_url: null,
  identifiers: [],
  availability: { owned: false, ebook: false, audio: false },
}));
const list = {
  id: listId,
  name: "Want to read",
  count: works.length,
  shared: false,
  editable: true,
  owner_id: listId,
  settings_revision: revision,
};

test("Discover owns list browsing, refresh, format downloads and settings", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let synced = false;
  const downloadModes: string[] = [];
  const downloadedIds: string[] = [];
  const offsets: number[] = [];
  await page.route("**/api/lists/page?*", (route) =>
    route.fulfill({ json: { items: [list], total: 1, offset: 0, limit: 4 } }),
  );
  await page.route(`**/api/lists/${listId}?*`, (route) => {
    const q = new URL(route.request().url()).searchParams;
    const offset = Number(q.get("offset") || 0),
      limit = Number(q.get("limit") || 16);
    offsets.push(offset);
    if (limit === 16) expect(q.get("sort")).toBe("newest");
    const current = synced
      ? [{ ...works[0], title: "Newly synced book" }, ...works.slice(1)]
      : works;
    return route.fulfill({
      json: {
        ...list,
        items: current.slice(offset, offset + limit),
        content_revision: revision,
        offset,
        limit,
      },
    });
  });
  await page.route(`**/api/lists/${listId}/subscription`, (route) =>
    route.fulfill({
      json: {
        provider: "goodreads",
        enabled: true,
        state: "idle",
        generation: 1,
        last_success_at: synced ? "2026-09-20T12:00:00Z" : null,
        message: "Up to date",
        shelf: "to-read",
      },
    }),
  );
  await page.route(`**/api/lists/${listId}/subscription/sync`, (route) => {
    synced = true;
    return route.fulfill({
      status: 202,
      json: { id: listId, status: "queued" },
    });
  });
  await page.route("**/api/requests/quick-add", (route) => {
    const body = route.request().postDataJSON();
    downloadModes.push(body.specification.mode);
    downloadedIds.push(body.work_id);
    return route.fulfill({
      status: 202,
      json: { id: body.work_id, status: "queued", message: "Searching" },
    });
  });
  await page.goto("/lists");
  await expect(page).toHaveURL(/discover\?view=yours/);
  const shelf = page.getByRole("region", {
    name: "Want to read followed list",
  });
  await expect(
    shelf.getByRole("heading", { name: "Want to read" }),
  ).toBeVisible();
  await expect(
    shelf.getByRole("link", { name: "View all", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Manage all lists")).toHaveCount(0);
  await expect(
    shelf.getByRole("button", { name: "Hide Want to read on For you" }),
  ).toBeVisible();
  await shelf.locator(".discovery-shelf").evaluate((el) => {
    el.scrollLeft = el.scrollWidth;
  });
  await expect(shelf.locator(".discovery-shelf > li")).toHaveCount(32);
  await shelf
    .getByRole("button", { name: "Refresh Want to read", exact: true })
    .click();
  await expect.poll(() => synced).toBe(true);
  await expect(
    shelf.getByText("Newly synced book", { exact: true }).first(),
  ).toBeVisible();
  await expect
    .poll(() =>
      shelf.locator(".discovery-shelf").evaluate((el) => el.scrollLeft),
    )
    .toBeLessThan(10);
  await expect(
    shelf.getByRole("button", { name: "Refresh Want to read", exact: true }),
  ).toBeEnabled();
  await shelf.locator(".discovery-shelf").evaluate((el) => {
    el.scrollLeft = el.scrollWidth;
  });
  await expect.poll(() => offsets.includes(16)).toBe(true);
  await expect(
    shelf.getByText("Shelf book 17", { exact: true }).first(),
  ).toBeVisible();
  for (const [label, mode] of [
    ["Both", "both"],
    ["Ebook", "ebook"],
    ["Audiobook", "audio"],
  ]) {
    await shelf.getByLabel("Download format for Want to read").click();
    await shelf.getByRole("button", { name: label, exact: true }).click();
    await expect(shelf.getByText("101 queued", { exact: false })).toBeVisible({
      timeout: 20000,
    });
    expect(downloadModes.filter((value) => value === mode)).toHaveLength(101);
  }
  expect(new Set(downloadedIds).size).toBe(101);
  expect(offsets).toContain(100);
  await page.screenshot({
    path: info.outputPath("lists-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await shelf.getByLabel("Download format for Want to read").click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("lists-mobile.png"),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(
    shelf.getByRole("link", { name: "Settings for Want to read" }),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "Reading accounts", exact: true })
    .click();
  await expect(page).toHaveURL(/settings#reading/);
  await expect(
    page
      .getByRole("navigation", { name: "Settings categories" })
      .getByRole("link", { name: "Lists", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("Observed entries and exclusions")).toHaveCount(
    0,
  );
  await expect(
    page.getByText("Advanced requests", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("tablist", { name: "List settings" }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("local list creation stays within Discover", async ({ page }) => {
  await page.goto("/discover?view=yours");
  await page.getByRole("button", { name: "Add list", exact: true }).click();
  await page.getByRole("button", { name: "Create a local list" }).click();
  const dialog = page.getByRole("dialog", { name: "Create a list" });
  await dialog.getByLabel("List name").fill("Weekend reading");
  await dialog.getByRole("button", { name: "Create list" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Weekend reading" }),
  ).toBeVisible();
});

test("reading accounts owns monitoring and compact list details", async ({
  page,
}, info) => {
  await page.goto("/discover?view=yours");
  await page.getByRole("button", { name: "Add list", exact: true }).click();
  await page.getByRole("button", { name: "Create a local list" }).click();
  const create = page.getByRole("dialog", { name: "Create a list" });
  await create.getByLabel("List name").fill("Settings test shelf");
  await create.getByRole("button", { name: "Create list" }).click();
  await expect(create).toHaveCount(0);
  const id = (
    await (
      await page.request.get("/api/lists/page?q=Settings%20test%20shelf")
    ).json()
  ).items[0].id;
  let monitoring = true;
  let subscription = {
    provider: "goodreads",
    enabled: true,
    interval_minutes: 30,
    generation: 1,
    state: "idle",
    observed_count: 0,
  };
  await page.route("**/api/reading-accounts/goodreads", (route) =>
    route.fulfill({ json: null }),
  );
  await page.route("**/api/reading-accounts/subscriptions", async (route) => {
    const response = await page.request.get(`/api/lists/${id}`);
    const list = response.ok() ? await response.json() : null;
    await route.fulfill({
      json:
        monitoring && list
          ? [
              {
                list_id: id,
                name: list.name,
                external_id: "to-read",
                account_id: "123",
                subscription,
              },
            ]
          : [],
    });
  });
  await page.route(`**/api/lists/${id}/subscription`, async (route) => {
    if (route.request().method() === "DELETE") {
      monitoring = false;
      await route.fulfill({ status: 204 });
      return;
    }
    const body = route.request().postDataJSON();
    expect(body.expected_generation).toBe(subscription.generation);
    subscription = {
      ...subscription,
      ...body,
      generation: subscription.generation + 1,
    };
    await route.fulfill({ json: subscription });
  });
  await page.goto(`/settings?list=${id}#lists`);
  await expect(page).toHaveURL(`/settings?list=${id}#reading`);
  const dialog = page.getByRole("dialog", { name: "List details" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Check for new books")).toHaveCount(0);
  await dialog.getByLabel("Name", { exact: true }).fill("Evening reading");
  await dialog.getByLabel("Share with this household").check();
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog).toHaveCount(0);
  const row = page.getByRole("article", { name: "Evening reading monitoring" });
  await expect(row).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Settings categories" })
      .getByRole("link", { name: "Lists", exact: true }),
  ).toHaveCount(0);
  await row
    .getByLabel("Check Evening reading for new books")
    .selectOption("1440");
  await expect.poll(() => subscription.interval_minutes).toBe(1440);
  await row
    .getByRole("button", { name: "Pause tracking Evening reading" })
    .click();
  await expect(
    row.getByLabel("Check Evening reading for new books"),
  ).toBeDisabled();
  await page.screenshot({
    path: info.outputPath("reading-accounts-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("reading-accounts-mobile.png"),
    fullPage: true,
  });
  await row.getByRole("link", { name: "Edit Evening reading" }).click();
  await expect(dialog.getByLabel("Share with this household")).toBeChecked();
  await page.screenshot({
    path: info.outputPath("list-details-mobile.png"),
    fullPage: true,
  });
  await dialog
    .getByRole("button", { name: "Stop monitoring", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page
      .getByRole("region", { name: "Local lists" })
      .getByRole("link", { name: "Evening reading", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Edit Evening reading" }).click();
  await dialog
    .getByRole("button", { name: "Remove this list…", exact: true })
    .click();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue(
    "Evening reading",
  );
  await dialog
    .getByRole("button", { name: "Remove this list…", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Remove list", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  expect((await page.request.get(`/api/lists/${id}`)).status()).toBe(404);
});
