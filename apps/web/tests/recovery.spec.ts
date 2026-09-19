import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

test("restored-state operator review replaces navigation and blocks catalog access", async ({
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
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
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
    const evidence = root + "/.local/evidence/recovery-reconcile-ui";
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
