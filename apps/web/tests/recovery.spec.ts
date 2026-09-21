import { expect, test } from "./fixtures";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("restore review fences ordinary work and observes inventory without side effects", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const fixture = (mode: string) =>
    execFileSync("uv", ["run", "python", "scripts/e2e_recovery.py", mode], {
      cwd: root,
      stdio: "pipe",
    });
  execFileSync("uv", ["run", "python", "scripts/e2e_auth_budget.py"], {
    cwd: root,
    stdio: "pipe",
  });
  const login = await page.request.post("/api/auth/login", {
    headers: { Origin: "http://127.0.0.1:8001" },
    data: { username: "reader", password: "browser test password" },
  });
  expect(login.status()).toBe(200);
  const headers = {
    Origin: "http://127.0.0.1:8001",
    "X-CSRF-Token": (await login.json()).csrf_token,
  };
  const list = await page.request.post("/api/lists", {
    headers,
    data: { name: "Recovery RSS baseline" },
  });
  expect(list.status()).toBe(201);
  const listId = (await list.json()).id;
  const subscription = await page.request.put(
    `/api/lists/${listId}/subscription`,
    {
      headers,
      data: {
        enabled: false,
        feed_url:
          "https://www.goodreads.com/review/list_rss/123?key=private-feed-key&shelf=to-read",
      },
    },
  );
  expect(subscription.status()).toBe(200);
  fixture("pause");
  try {
    await page.goto("/");
    await page.getByLabel("Username", { exact: true }).fill("reader");
    await page
      .getByLabel("Password", { exact: true })
      .fill("browser test password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Your restored library is paused" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Historical queue protection" }),
    ).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Main navigation" }),
    ).toHaveCount(0);
    expect((await page.request.get("/api/lists")).status()).toBe(423);
    const before = await (
      await page.request.get("http://127.0.0.1:13379/fixture/recovery-stats")
    ).json();
    await page
      .getByRole("button", { name: "Run read-only checks", exact: true })
      .click();
    await expect(
      page.getByRole("status").filter({ hasText: "Observation finished" }),
    ).toBeVisible({ timeout: 60_000 });
    await page.getByLabel("Filter observations").selectOption("library");
    await page
      .getByRole("button", { name: /^Review inventory for/ })
      .first()
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Review current library inventory",
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Record current inventory", exact: true })
      .click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Current inventory recorded" }),
    ).toBeVisible({ timeout: 30_000 });
    expect((await page.request.get("/api/lists")).status()).toBe(423);
    const after = await (
      await page.request.get("http://127.0.0.1:13379/fixture/recovery-stats")
    ).json();
    expect(after).toEqual(before);
    await page.goto("/library");
    await expect(
      page.getByRole("heading", { name: "Your restored library is paused" }),
    ).toBeVisible();
  } finally {
    fixture("clear");
  }
});
