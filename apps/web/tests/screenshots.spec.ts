import { expect, test } from "./fixtures";
import { resolve } from "node:path";

test("capture documentation screenshots", async ({ page }) => {
  test.skip(
    process.env.DEWARR_SCREENSHOTS !== "1",
    "Documentation capture is opt-in",
  );
  const origin = "http://127.0.0.1:8001";
  await page.goto("/");
  await expect(page.getByLabel("Setup token")).toHaveCount(0);
  await page.getByLabel("Your name", { exact: true }).fill("Reader");
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser test password");
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/auth/bootstrap") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Create administrator", exact: true })
    .click();
  const response = await created;
  expect(response.status()).toBe(201);
  const auth = await response.json();
  expect(auth.user.role).toBe("admin");
  expect(
    (await (await page.request.get("/api/auth/setup")).json()).needs_setup,
  ).toBe(false);
  const duplicate = await page.request.post("/api/auth/bootstrap", {
    headers: { Origin: origin },
    data: {
      username: "another-admin",
      display_name: "Another reader",
      password: "another long password",
    },
  });
  expect(duplicate.status()).toBe(409);
  await page.request.put("/api/setup/onboarding", {
    headers: { Origin: origin, "X-CSRF-Token": auth.csrf_token },
    data: { status: "completed", step: 0, skipped: [] },
  });
  const routes = [
    ["for-you", "/discover"],
    ["browse", "/discover?view=browse"],
    ["collections", "/discover?view=collections"],
    ["awards", "/discover?view=awards"],
    ["reading-accounts", "/settings#reading"],
    ["download-preferences", "/settings#preferences"],
    ["library-settings", "/settings#libraries"],
  ];
  for (const [name, route] of routes) {
    await page.goto(route);
    await expect(page.locator(".sidebar .brand")).toHaveText("Dewarr");
    await expect(page.locator(".sidebar .brand img")).toHaveJSProperty(
      "complete",
      true,
    );
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: resolve("../../docs/images", `${name}.png`),
    });
  }
});
