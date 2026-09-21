import { expect, test } from "./fixtures";
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
  await page.goto("/settings#preferences");
  const preferences = page.getByRole("region", {
    name: "Download defaults",
    exact: true,
  });
  await preferences
    .getByRole("checkbox", { name: "Prefer popular releases", exact: true })
    .check();
  const order = preferences.getByRole("group", {
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
  await preferences
    .getByRole("button", { name: "Save download defaults", exact: true })
    .click();
  await expect(
    preferences.getByText("Download defaults saved.", { exact: true }),
  ).toBeVisible();
  await page.goto(`/books/${work.id}?tab=sources`);
  await refresh();
  await mam.getByRole("button", { name: /^Details for/ }).click();
  const details = page.getByRole("dialog", { name: "Release details" });
  await details.getByRole("tab", { name: "Details", exact: true }).click();
  await expect(details.locator(".release-facts")).toContainText("321");
  await details.screenshot({
    path: testInfo.outputPath("popularity-evidence.png"),
  });
  await page.goto("/settings#preferences");
  await expect(
    preferences.getByRole("checkbox", {
      name: "Prefer popular releases",
      exact: true,
    }),
  ).toBeChecked();
  await preferences.screenshot({
    path: testInfo.outputPath("popularity-settings-desktop.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await preferences
    .getByRole("checkbox", { name: "Prefer popular releases", exact: true })
    .uncheck();
  await preferences
    .getByRole("button", { name: "Save download defaults", exact: true })
    .click();
  await expect(
    preferences.getByText("Download defaults saved.", { exact: true }),
  ).toBeVisible();
  const latest = await (
    await page.request.get(
      `/api/catalog/works/${work.id}/source-searches/latest`,
    )
  ).json();
  expect(latest.profile.preferences.criteria).toContain("popularity");
  await page.goto(`/books/${work.id}?tab=sources`);
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
