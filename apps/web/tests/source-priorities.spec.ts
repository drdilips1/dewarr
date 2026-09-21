import { expect, test } from "./fixtures";
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
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeVisible();
  await page.goto("/library?view=saved");
  await expect(page.getByRole("heading", { name: "My Library" })).toBeVisible();
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
  await page.goto("/settings#preferences");
  const sources = page.getByRole("region", {
    name: "Download defaults",
    exact: true,
  });
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
    .getByRole("list", { name: "Source preference", exact: true })
    .locator("li > span");
  await expect(rows).toHaveText([
    "MAM",
    "Shared indexer name · Prowlarr #7",
    "Shared indexer name · Prowlarr #8",
    "Prowlarr (fallback)",
  ]);
  await editor
    .getByRole("button", {
      name: "Reorder prowlarr:8 in Source preference",
      exact: true,
    })
    .press("ArrowUp");
  await sources
    .getByRole("button", { name: "Save download defaults", exact: true })
    .click();
  await expect(
    sources.getByText("Download defaults saved.", { exact: true }),
  ).toBeVisible();
  const savedDefaults = await (
    await page.request.get("/api/acquisition/preferences/personal")
  ).json();
  expect(savedDefaults.effective.source_order).toEqual([
    "mam",
    "prowlarr:8",
    "prowlarr:7",
    "prowlarr",
  ]);
  await page.reload();
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
  const saved = await (
    await page.request.get("/api/acquisition/preferences/personal")
  ).json();
  expect(saved.effective.source_order).toEqual(
    savedDefaults.effective.source_order,
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
