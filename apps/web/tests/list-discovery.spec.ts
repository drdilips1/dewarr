import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("followed lists expose saved books and ownership without starting acquisition", async ({
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
  const auth = await (await page.request.get("/api/auth/me")).json();
  const headers = {
    "X-CSRF-Token": auth.csrf_token,
    Origin: "http://127.0.0.1:8001",
  };
  async function post(url: string, data: unknown) {
    const response = await page.request.post(url, { headers, data });
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  }
  const holdings = await (
    await page.request.get("/api/discovery/library")
  ).json();
  const owned = holdings.items[0].work;
  const extra = await post("/api/catalog/works", {
    title: "Followed list discovery newcomer",
    authors: ["Discovery writer"],
  });
  const second = await post("/api/catalog/works", {
    title: "Another followed list title",
    authors: [],
  });
  let latest: { id: string; name: string } | null = null;
  for (let i = 0; i < 6; i++) {
    const item = await post("/api/lists", { name: `Followed discovery ${i}` });
    const subscription = await page.request.put(
      `/api/lists/${item.id}/subscription`,
      {
        headers,
        data:
          i === 0
            ? { provider: "hardcover", hardcover_list_id: 9101, enabled: false }
            : {
                feed_url: `https://www.goodreads.com/review/list_rss/123?key=browser-test-only&shelf=discovery-${i}`,
                enabled: false,
              },
      },
    );
    expect(subscription.ok(), await subscription.text()).toBe(true);
    if (i === 5) {
      latest = item;
      for (const work of [owned, extra, second]) {
        const response = await page.request.post(
          `/api/lists/${item.id}/entries`,
          { headers, data: { work_id: work.id } },
        );
        expect(response.ok()).toBe(true);
      }
    }
  }
  expect(latest).not.toBeNull();
  const hardcoverLists = await (
    await page.request.get(
      "/api/discovery/followed-lists?provider=hardcover&limit=4",
    )
  ).json();
  const writes: string[] = [];
  page.on("request", (request) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method()))
      writes.push(request.url());
  });
  await page.getByRole("link", { name: "Discover", exact: true }).click();
  const shelf = page.getByRole("region", {
    name: "Your followed lists",
    exact: true,
  });
  await expect(shelf.getByRole("article")).toHaveCount(4);
  const card = shelf.getByRole("article", {
    name: `${latest!.name} followed list`,
    exact: true,
  });
  await expect(card).toContainText("3 books · 1 in your library");
  await expect(card).toContainText("List observations paused");
  await expect(card).toContainText("No successful observation yet");
  await expect(card).toContainText("RSS can show only part of a shelf");
  await expect(card.locator(".book-card")).toHaveCount(3);
  await expect(card.locator(".book-card").first()).toContainText("In library");
  await card.screenshot({
    path: testInfo.outputPath("followed-lists-desktop.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await card.screenshot({
    path: testInfo.outputPath("followed-lists-mobile.png"),
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await shelf.getByRole("button", { name: "Next followed lists" }).click();
  await expect(shelf.getByRole("status")).toHaveText("Page 2");
  await expect(card).toHaveCount(0);
  await shelf
    .getByRole("combobox", { name: "List source" })
    .selectOption("hardcover");
  await expect(
    shelf.getByRole("article", { name: "Followed discovery 0 followed list" }),
  ).toBeVisible();
  await expect(shelf.getByRole("article")).toHaveCount(
    hardcoverLists.items.length,
  );
  await expect(shelf.getByRole("status")).toHaveCount(0);
  await shelf
    .getByRole("combobox", { name: "List source" })
    .selectOption("goodreads");
  await expect(card).toBeVisible();
  await page.route("**/api/discovery/followed-lists?*", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Synthetic followed-list outage" },
    }),
  );
  await shelf
    .getByRole("combobox", { name: "List source" })
    .selectOption("all");
  await expect(shelf.getByRole("alert")).toHaveText(
    "Synthetic followed-list outage",
  );
  await expect(shelf.getByRole("article")).toHaveCount(0);
  await page.unroute("**/api/discovery/followed-lists?*");
  await shelf.getByRole("button", { name: "Retry followed lists" }).click();
  await expect(card).toBeVisible();
  const openList = card.getByRole("link", {
    name: "Open list · curate and review automation →",
  });
  await openList.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`/lists/${latest!.id}`);
  await expect(
    page.getByRole("heading", { name: latest!.name, exact: true }),
  ).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
