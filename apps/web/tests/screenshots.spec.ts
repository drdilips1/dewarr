import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test("capture documentation screenshots", async ({ page }) => {
  test.skip(
    process.env.DEWARR_SCREENSHOTS !== "1",
    "Documentation capture is opt-in",
  );
  const origin = "http://127.0.0.1:8001";
  const response = await page.request.post("/api/auth/bootstrap", {
    headers: { Origin: origin },
    data: {
      username: "reader",
      display_name: "Reader",
      password: "browser test password",
      bootstrap_token: "browser-test-bootstrap-token",
    },
  });
  expect(response.ok()).toBeTruthy();
  const auth = await response.json();
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
    ["downloads", "/requests"],
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
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/discover");
  await page.waitForTimeout(2000);
  await page.screenshot({ path: resolve("../../docs/images/mobile.png") });
});
