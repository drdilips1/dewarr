import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("individual indexer priorities load explicitly and retain saved choices through outages", async ({
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
  const works = await (
    await page.request.get("/api/catalog/works?q=The%20Synthetic%20Archive")
  ).json();
  const work = works.items.find(
    (item: { title: string }) => item.title === "The Synthetic Archive",
  );
  let calls = 0;
  let mode = "normal";
  // Keep the real API/auth/adapter request, extending its public result to
  // exercise duplicate names and unsupported capability presentation.
  await page.route("**/api/sources/prowlarr/indexers", async (route) => {
    calls++;
    if (mode === "outage") {
      await route.fulfill({
        status: 503,
        json: { detail: "Synthetic indexer outage" },
      });
      return;
    }
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const rows = await response.json();
    const base = rows.find((value: { id: number }) => value.id === 7);
    expect(base).toBeTruthy();
    const available = {
      ...base,
      name: "Shared indexer name",
      protocol: "torrent",
      enabled: true,
      supports_search: true,
      excluded: false,
      native_mam: false,
    };
    await route.fulfill({
      response,
      json: [
        ...(mode === "missing" ? [] : [{ ...available, id: 7 }]),
        { ...available, id: 8 },
        { ...available, id: 9, protocol: "nzb", name: "Usenet fixture" },
        {
          ...available,
          id: 31,
          excluded: true,
          native_mam: true,
          name: "Native MAM duplicate",
        },
        { ...available, id: 32, enabled: false, name: "Disabled fixture" },
        {
          ...available,
          id: 33,
          supports_search: false,
          name: "No search fixture",
        },
        {
          ...available,
          id: 34,
          categories: [2000],
          name: "Movie-only fixture",
        },
      ],
    });
  });
  await page.goto(`/books/${work.id}?tab=sources`);
  const sources = page.getByRole("region", { name: "Book download sources" });
  await expect(
    sources.getByRole("button", {
      name: "Refresh source results",
      exact: true,
    }),
  ).toBeEnabled({ timeout: 30_000 });
  await sources
    .getByRole("combobox", { name: "Download profile", exact: true })
    .selectOption("");
  await sources
    .getByText("Customize download preferences", { exact: true })
    .click();
  const editor = sources.getByRole("region", {
    name: "Source preference editor",
  });
  await editor
    .getByText("Individual Prowlarr priorities", { exact: true })
    .click();
  expect(calls).toBe(0);
  const load = editor.getByRole("button", {
    name: "Load Prowlarr indexers",
    exact: true,
  });
  await load.click();
  const picker = editor.getByRole("combobox", {
    name: "Indexer to prioritize",
    exact: true,
  });
  await expect(picker).toBeEnabled();
  expect(calls).toBe(1);
  for (const id of [9, 31, 32, 33, 34])
    await expect(
      picker.locator(`option[value="prowlarr:${id}"]`),
    ).toHaveJSProperty("disabled", true);
  await picker.selectOption("prowlarr:7");
  await editor
    .getByRole("button", { name: "Add indexer priority", exact: true })
    .click();
  await expect(picker.locator('option[value="prowlarr:7"]')).toHaveJSProperty(
    "disabled",
    true,
  );
  await picker.selectOption("prowlarr:8");
  await editor
    .getByRole("button", { name: "Add indexer priority", exact: true })
    .click();
  const rows = editor
    .getByRole("group", { name: "Source preference", exact: true })
    .locator("li > span");
  await expect(rows).toHaveText([
    "MAM",
    "Shared indexer name · Prowlarr #7",
    "Shared indexer name · Prowlarr #8",
    "Prowlarr (fallback)",
  ]);
  await editor
    .getByRole("button", {
      name: "Move Shared indexer name · Prowlarr #8 up in Source preference",
      exact: true,
    })
    .click();
  await sources
    .getByLabel("Profile name", { exact: true })
    .fill("Individual tracker priorities");
  const saving = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/acquisition/profiles") &&
      response.request().method() === "POST",
  );
  await sources
    .getByRole("button", { name: "Create profile", exact: true })
    .click();
  const response = await saving;
  expect(response.status()).toBe(201);
  const profile = await response.json();
  expect(profile.preferences.source_order).toEqual([
    "mam",
    "prowlarr:8",
    "prowlarr:7",
    "prowlarr",
  ]);
  await expect(
    sources.getByRole("combobox", { name: "Download profile", exact: true }),
  ).toHaveValue(profile.id);
  const refreshing = page.waitForResponse(
    (value) =>
      value.url().endsWith(`/api/catalog/works/${work.id}/source-searches`) &&
      value.request().method() === "POST",
  );
  await sources
    .getByRole("button", { name: "Refresh source results", exact: true })
    .click();
  const search = await refreshing;
  expect(search.status()).toBe(202);
  expect((await search.json()).profile.preferences.source_order).toEqual(
    profile.preferences.source_order,
  );
  await expect(
    sources.getByRole("button", {
      name: "Refresh source results",
      exact: true,
    }),
  ).toBeEnabled({ timeout: 30_000 });
  await page.reload();
  await expect(
    sources.getByRole("combobox", { name: "Download profile", exact: true }),
  ).toHaveValue(profile.id);
  await sources
    .getByText("Customize download preferences", { exact: true })
    .click();
  await expect(rows).toHaveText([
    "MAM",
    "Prowlarr indexer #8",
    "Prowlarr indexer #7",
    "Prowlarr (fallback)",
  ]);
  expect(calls).toBe(1);
  await editor
    .getByText("Individual Prowlarr priorities", { exact: true })
    .click();
  mode = "missing";
  await load.click();
  await expect(
    editor.getByText(
      /Prowlarr indexer #7: Not in the last loaded indexer list/,
    ),
  ).toBeVisible();
  await expect(rows).toHaveCount(4);
  mode = "outage";
  await load.click();
  await expect(
    editor.getByText("Synthetic indexer outage", { exact: true }),
  ).toBeVisible();
  await expect(picker).toBeDisabled();
  await expect(rows).toHaveCount(4);
  await editor.screenshot({
    path: testInfo.outputPath("indexer-priorities-desktop.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await editor.screenshot({
    path: testInfo.outputPath("indexer-priorities-mobile.png"),
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  for (const name of [
    "Shared indexer name · Prowlarr #8",
    "Prowlarr indexer #7",
    "Prowlarr (fallback)",
  ]) {
    await editor
      .getByRole("button", {
        name: `Remove ${name} from Source preference`,
        exact: true,
      })
      .click();
  }
  await expect(
    editor.getByRole("button", {
      name: "Remove MAM from Source preference",
      exact: true,
    }),
  ).toBeDisabled();
  // Unsaved ordering changes must not alter persisted profile or search snapshots.
  const saved = (
    await (await page.request.get("/api/acquisition/profiles")).json()
  ).find((value: { id: string }) => value.id === profile.id);
  expect(saved.preferences.source_order).toEqual(
    profile.preferences.source_order,
  );
  await sources
    .getByRole("button", {
      name: "Use inherited Source preference",
      exact: true,
    })
    .click();
  await expect(rows).toHaveText(["MAM", "Prowlarr (fallback)"]);
  expect(errors).toEqual([]);
});
