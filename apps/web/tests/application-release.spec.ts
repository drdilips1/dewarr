import { expect, test } from "@playwright/test";

for (const state of ["update", "current", "offline", "unconfigured"]) {
  test(`sidebar release tracker: ${state}`, async ({ page }) => {
    await page.route("**/api/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path === "/api/auth/me")
        data = {
          user: {
            id: "reader",
            role: "member",
            display_name: "Reader",
            onboarding_status: "complete",
          },
          csrf_token: "test",
        };
      if (path === "/api/setup/onboarding") data = { status: "completed" };
      if (path === "/api/application/release")
        data = {
          installed_version: "v1.9.0",
          installed_url:
            state === "unconfigured"
              ? null
              : "https://github.com/example/books/releases/tag/v1.9.0",
          latest_version: state === "update" ? "v1.10.0" : "v1.9.0",
          release_url: "https://github.com/example/books/releases/tag/v1.10.0",
          update_available: state === "update",
          status:
            state === "offline"
              ? "unavailable"
              : state === "unconfigured"
                ? "unconfigured"
                : "checked",
        };
      return route.fulfill({ json: data });
    });
    await page.goto("/settings");
    const footer = page.getByRole("group", {
      name: "Application version",
    });
    await expect(footer).toBeVisible();
    await expect(footer.getByText("v1.9.0", { exact: true })).toBeVisible();
    if (state === "update") {
      await expect(
        footer.getByRole("link", { name: "Update", exact: true }),
      ).toHaveAttribute(
        "href",
        "https://github.com/example/books/releases/tag/v1.10.0",
      );
      const sidebar = await page.locator(".sidebar").boundingBox();
      const bounds = await footer.boundingBox();
      expect(bounds!.y).toBeGreaterThan(sidebar!.height - 150);
    } else {
      await expect(
        footer.getByRole("link", { name: "Update", exact: true }),
      ).toHaveCount(0);
      await expect(
        footer.getByText(
          state === "current"
            ? "Up to date"
            : state === "offline"
              ? "Update check unavailable"
              : "Release tracking not configured",
        ),
      ).toBeVisible();
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(footer).toBeVisible();
  });
}
