import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

test("restored-state operator review replaces navigation and blocks catalog access", async ({
  page,
}) => {
  test.setTimeout(180_000);
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
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const login = await page.request.post("/api/auth/login", {
    headers: { Origin: "http://127.0.0.1:8001" },
    data: { username: "reader", password: "browser test password" },
  });
  expect(login.status()).toBe(200);
  const headers = {
    Origin: "http://127.0.0.1:8001",
    "X-CSRF-Token": (await login.json()).csrf_token,
  };
  const listResponse = await page.request.post("/api/lists", {
    headers,
    data: { name: "Recovery RSS baseline" },
  });
  expect(listResponse.status()).toBe(201);
  const listId = (await listResponse.json()).id;
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
      page.getByRole("heading", { name: "Saved workflow evidence" }),
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
    await expect(page.getByRole("status")).toContainText(
      "Observation finished",
      { timeout: 60_000 },
    );
    await page.getByLabel("Filter observations").selectOption("downloads");
    await expect(
      page.getByText(
        "Current transfer identity and destination match the saved attempt",
        { exact: true },
      ),
    ).toBeVisible();
    await page.getByText("Observed evidence", { exact: true }).first().click();
    await expect(
      page.getByText('"saved_external_may_exist"', { exact: false }),
    ).toBeVisible();
    await page
      .getByRole("checkbox", { name: /Select .* for recovery review/ })
      .check();
    await page
      .getByRole("button", { name: "Review selected transfers", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Review existing transfers",
        exact: true,
      }),
    ).toBeVisible();
    const evidence = root + "/.local/evidence/recovery-outbound-ui";
    mkdirSync(evidence, { recursive: true });
    await page.screenshot({ path: evidence + "/review.png", fullPage: true });
    await page
      .getByRole("button", { name: "Record verified transfers", exact: true })
      .click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Selected transfers recorded" }),
    ).toBeVisible({ timeout: 30_000 });
    expect((await page.request.get("/api/recovery")).status()).toBe(200);
    expect((await page.request.get("/api/lists")).status()).toBe(423);
    const after = await (
      await page.request.get("http://127.0.0.1:13379/fixture/recovery-stats")
    ).json();
    expect(after).toEqual(before);
    const previousScan = (
      await (await page.request.get("/api/recovery")).json()
    ).latest_scan.id;
    await page
      .getByRole("button", { name: "Run read-only checks", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await (await page.request.get("/api/recovery")).json()).latest_scan
            .id,
      )
      .not.toBe(previousScan);
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
    await page.screenshot({
      path: evidence + "/inventory-review.png",
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Record current inventory", exact: true })
      .click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Current inventory recorded" }),
    ).toBeVisible({ timeout: 30_000 });
    expect((await page.request.get("/api/lists")).status()).toBe(423);
    const inventoryAfter = await (
      await page.request.get("http://127.0.0.1:13379/fixture/recovery-stats")
    ).json();
    expect(inventoryAfter).toEqual(before);
    const inventoryScan = (
      await (await page.request.get("/api/recovery")).json()
    ).latest_scan.id;
    await page
      .getByRole("button", { name: "Run read-only checks", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await (await page.request.get("/api/recovery")).json()).latest_scan
            .id,
      )
      .not.toBe(inventoryScan);
    await expect(
      page.getByRole("status").filter({ hasText: "Observation finished" }),
    ).toBeVisible({ timeout: 60_000 });
    await page.getByLabel("Filter observations").selectOption("files");
    await page
      .getByRole("button", { name: /^Review publication for/ })
      .first()
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Review published books",
        exact: true,
      }),
    ).toBeFocused();
    await page.screenshot({
      path: evidence + "/publication-review.png",
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Record published books", exact: true })
      .click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Selected publications recorded" }),
    ).toBeVisible({ timeout: 30_000 });
    expect((await page.request.get("/api/lists")).status()).toBe(423);
    const publicationAfter = await (
      await page.request.get("http://127.0.0.1:13379/fixture/recovery-stats")
    ).json();
    expect(publicationAfter).toEqual(before);
    const publicationScan = (
      await (await page.request.get("/api/recovery")).json()
    ).latest_scan.id;
    await page
      .getByRole("button", { name: "Run read-only checks", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await (await page.request.get("/api/recovery")).json()).latest_scan
            .id,
      )
      .not.toBe(publicationScan);
    await expect(
      page.getByRole("status").filter({ hasText: "Observation finished" }),
    ).toBeVisible({ timeout: 60_000 });
    await page.getByLabel("Filter observations").selectOption("lists");
    await page
      .getByRole("button", {
        name: "Review list baseline for Recovery RSS baseline",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Review current list baseline",
        exact: true,
      }),
    ).toBeFocused();
    await expect(
      page.getByText("RSS is a partial view.", { exact: false }),
    ).toBeVisible();
    await page.screenshot({
      path: evidence + "/list-review.png",
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Record list baseline", exact: true })
      .click();
    await expect(
      page.getByRole("status").filter({ hasText: "List baselines recorded" }),
    ).toBeVisible({ timeout: 30_000 });
    expect((await page.request.get("/api/lists")).status()).toBe(423);
    expect(
      await (
        await page.request.get("http://127.0.0.1:13379/fixture/recovery-stats")
      ).json(),
    ).toEqual(before);

    fixture("outbound");
    await page.request.post("http://127.0.0.1:13379/fixture/writeback", {
      data: { reset: true },
    });
    const outboundBefore = await (
      await page.request.get("http://127.0.0.1:13379/fixture/writeback")
    ).json();
    const listScan = (await (await page.request.get("/api/recovery")).json())
      .latest_scan.id;
    await page
      .getByRole("button", { name: "Run read-only checks", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await (await page.request.get("/api/recovery")).json()).latest_scan
            .id,
      )
      .not.toBe(listScan);
    await expect(
      page.getByRole("status").filter({ hasText: "Observation finished" }),
    ).toBeVisible({ timeout: 60_000 });
    await page
      .getByRole("button", {
        name: "Review outbound change for Hardcover book 42 · list 92",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Review outbound list changes",
        exact: true,
      }),
    ).toBeFocused();
    await expect(
      page
        .getByText("Desired membership is currently visible;", { exact: false })
        .last(),
    ).toBeVisible();
    await page.screenshot({
      path: evidence + "/outbound-review.png",
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Record outbound evidence", exact: true })
      .click();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Outbound evidence recorded" }),
    ).toBeVisible({ timeout: 30_000 });
    expect(
      await (
        await page.request.get("http://127.0.0.1:13379/fixture/writeback")
      ).json(),
    ).toEqual(outboundBefore);
    expect(
      await (
        await page.request.get("http://127.0.0.1:13379/fixture/recovery-stats")
      ).json(),
    ).toEqual(before);
    expect((await page.request.get("/api/lists")).status()).toBe(423);

    await page.screenshot({ path: evidence + "/desktop.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/lists");
    await expect(
      page.getByRole("heading", { name: "Your restored library is paused" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Before resuming" }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Selected transfers recorded" }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Current inventory recorded" }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Selected publications recorded" }),
    ).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "List baselines recorded" }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "Outbound evidence recorded" }),
    ).toBeVisible();
    await page.getByLabel("Filter observations").selectOption("files");
    await expect(
      page.getByText("Publication journals", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({ path: evidence + "/mobile.png", fullPage: true });
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Sign in", exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    fixture("clear");
  }
});
