import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const bootstrap = await page.request.post("/api/auth/bootstrap", {
    headers: { Origin: "http://127.0.0.1:8001" },
    data: {
      username: "reader",
      display_name: "Reader",
      password: "browser test password",
    },
  });
  const login =
    bootstrap.status() === 201
      ? bootstrap
      : await page.request.post("/api/auth/login", {
          headers: { Origin: "http://127.0.0.1:8001" },
          data: { username: "reader", password: "browser test password" },
        });
  expect(login.ok()).toBeTruthy();
  const auth = await login.json();
  await page.request.put("/api/setup/onboarding", {
    headers: {
      Origin: "http://127.0.0.1:8001",
      "X-CSRF-Token": auth.csrf_token,
    },
    data: { status: "completed", step: 0, skipped: [] },
  });
});

const listId = "00000000-0000-4000-8000-000000000001";

for (const existing of [false, true]) {
  test(`community list adds to For You (${existing ? "hidden" : "new"})`, async ({
    page,
  }, info) => {
    let follows = 0;
    let hidden = [`personal:${listId}`, "popular"];
    const order = ["popular", `personal:${listId}`];
    await page.route("**/api/discovery/layout", async (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON();
        expect(body.order).toEqual(order);
        hidden = body.hidden;
      }
      await route.fulfill({ json: { hidden, order } });
    });
    await page.route("**/api/discovery/lists/123?*", (route) =>
      route.fulfill({
        json: {
          info: {
            external_id: "123",
            name: "Startup 101",
            description: "A list of startup books",
            count: 35,
            followers: 7,
            covers: [],
            followed_list_id: existing || follows ? listId : null,
            follow_supported: true,
          },
          items: [],
          next_cursor: null,
          warning: null,
        },
      }),
    );
    await page.route("**/api/discovery/lists/123/follow", (route) => {
      follows++;
      return route.fulfill({ json: { list_id: listId } });
    });
    await page.goto("/discover/lists/123");
    await expect(
      page.getByRole("heading", { name: "Startup 101" }),
    ).toBeVisible();
    await page.screenshot({ path: info.outputPath("community-desktop.png") });
    await page
      .getByRole("button", { name: "Add to For You", exact: true })
      .click();
    await expect(
      page.getByRole("link", { name: "On For You", exact: true }),
    ).toBeVisible();
    await expect(page).toHaveURL(/discover\/lists\/123$/);
    expect(follows).toBe(existing ? 0 : 1);
    expect(hidden).toEqual(["popular"]);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: info.outputPath("community-mobile.png") });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}
