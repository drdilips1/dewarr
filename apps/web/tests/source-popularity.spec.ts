import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

test("source popularity persists as an ordered preference without rewriting saved searches", async ({
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
  await page.goto(`/books/${work.id}?tab=sources`);
  const sources = page.getByRole("region", { name: "Book download sources" });
  const mam = sources.getByRole("row", {
    name: "Harbor & Roads — Complete Stories",
    exact: true,
  });
  const refresh = async () => {
    const response = page.waitForResponse(
      (value) =>
        value.url().endsWith(`/api/catalog/works/${work.id}/source-searches`) &&
        value.request().method() === "POST",
    );
    await sources
      .getByRole("button", { name: "Refresh source results", exact: true })
      .click();
    const accepted = await response;
    expect(accepted.status()).toBe(202);
    const receipt = await accepted.json();
    await expect(
      sources.getByRole("button", {
        name: "Refresh source results",
        exact: true,
      }),
    ).toBeEnabled({ timeout: 30_000 });
    return receipt;
  };
  await expect(mam).toBeVisible();
  await expect(
    sources.getByRole("button", {
      name: "Refresh source results",
      exact: true,
    }),
  ).toBeEnabled({ timeout: 30_000 });
  await sources
    .getByRole("combobox", { name: "Download profile", exact: true })
    .selectOption("");
  await sources.getByText("Download profile settings", { exact: true }).click();
  await sources.getByText("Edit profile", { exact: true }).click();
  await sources
    .getByLabel("Profile name", { exact: true })
    .fill("Popularity within each source");
  await sources
    .getByRole("checkbox", { name: "Prefer popular releases", exact: true })
    .check();
  const order = sources.getByRole("group", {
    name: "Ranking priorities",
    exact: true,
  });
  const priority = order.getByRole("button", {
    name: "Reorder popularity in Ranking priorities",
    exact: true,
  });
  await priority.focus();
  await page.keyboard.press("ArrowUp");
  await expect(order.locator("li").nth(1)).toContainText("Source");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
  const savedResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/acquisition/profiles") &&
      response.request().method() === "POST",
  );
  await sources
    .getByRole("button", { name: "Create profile", exact: true })
    .click();
  const saved = await savedResponse;
  expect(saved.status()).toBe(201);
  const profile = await saved.json();
  await expect(
    sources.getByRole("combobox", { name: "Download profile", exact: true }),
  ).toHaveValue(profile.id);
  expect(profile.preferences.criteria).toEqual([
    "format",
    "source",
    "popularity",
    "seeders",
  ]);
  await refresh();
  await mam.getByRole("button", { name: /^Details for/ }).click();
  const details = page.getByRole("dialog", { name: "Release details" });
  await details.getByText("Why this ranking?", { exact: true }).click();
  await expect(details).toContainText(
    "MAM reports 321 completed downloads; compared only within MAM",
  );
  await expect(details.locator(".release-facts")).toContainText("321");
  await details.screenshot({
    path: testInfo.outputPath("popularity-evidence.png"),
  });
  await page.reload();
  await expect(
    sources.getByRole("combobox", { name: "Download profile", exact: true }),
  ).toHaveValue(profile.id);
  await sources.getByText("Download profile settings", { exact: true }).click();
  await sources.getByText("Edit profile", { exact: true }).click();
  const popularity = sources.locator(".setting-inline-option");
  // Use the innermost details (the outer customization details also contains it).
  await popularity.last().screenshot({
    path: testInfo.outputPath("popularity-settings-desktop.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await popularity.last().screenshot({
    path: testInfo.outputPath("popularity-settings-mobile.png"),
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await sources
    .getByRole("checkbox", { name: "Prefer popular releases", exact: true })
    .uncheck();
  const changedResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/acquisition/profiles/${profile.id}`) &&
      response.request().method() === "PUT",
  );
  await sources
    .getByRole("button", { name: "Save profile", exact: true })
    .click();
  expect((await changedResponse).status()).toBe(200);
  const latest = await (
    await page.request.get(
      `/api/catalog/works/${work.id}/source-searches/latest`,
    )
  ).json();
  expect(latest.profile.preferences.criteria).toContain("popularity");
  const receipt = await refresh();
  const refreshed = await (
    await page.request.get(
      `/api/catalog/works/${work.id}/source-searches/latest`,
    )
  ).json();
  expect(refreshed.id).toBe(receipt.id);
  expect(refreshed.profile.preferences.criteria).toEqual([
    "format",
    "source",
    "seeders",
  ]);
  expect(errors).toEqual([]);
});
