import { expect, test } from "@playwright/test";

test("two media rows choose ABS folders and verify before activation", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  const writes: { path: string; body: any }[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let destination: any = null;
  let verified = false;
  let failure = false;
  let automaticEnabled = true;
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (["PUT", "POST"].includes(method))
      writes.push({ path, body: route.request().postDataJSON() });
    let data: unknown = [];
    if (path === "/api/auth/me")
      data = {
        user: {
          id: "user",
          role: "admin",
          display_name: "Reader",
          onboarding_status: "complete",
        },
        csrf_token: "test",
      };
    else if (path === "/api/setup/onboarding") data = { status: "completed" };
    else if (path === "/api/integrations")
      data = [
        {
          id: "abs",
          name: "Audiobookshelf",
          enabled: true,
          status: "connected",
          library_count: 2,
          book_count: 276,
          base_url: "http://library:13378",
          version: "2.36.1",
        },
      ];
    else if (path === "/api/library/libraries")
      data = [
        { id: "lib", name: "Books", accessible: true, granted_user_ids: [] },
      ];
    else if (path === "/api/organization/library-folders")
      data = [
        {
          library_id: "lib",
          library_name: "Books",
          server_name: "Audiobookshelf",
          ebooks_allowed: true,
          folders: ["/data/ebooks", "/data/audio"],
        },
        {
          library_id: "audio-only",
          library_name: "Audio only",
          server_name: "Audiobookshelf",
          ebooks_allowed: false,
          folders: ["/recordings"],
        },
      ];
    else if (path === "/api/organization/destinations")
      data = destination
        ? [{ ...destination, publication_available: verified }]
        : [];
    else if (path === "/api/downloaders")
      data = [
        {
          id: "qbit",
          name: "qBittorrent",
          enabled: true,
          status: "connected",
          mappings_current: true,
          generation: 1,
        },
      ];
    else if (path.endsWith("/automatic-import")) {
      if (method === "PUT")
        automaticEnabled = route.request().postDataJSON().enabled;
      data = {
        enabled: automaticEnabled,
        ready: verified,
        can_enable: verified,
        generation: 1,
        message: automaticEnabled
          ? "Completed downloads import automatically"
          : "Automatic import is off",
      };
    } else if (path.startsWith("/api/acquisition/preferences/"))
      data = {
        effective: verified ? { ebook_destination_id: "dest" } : {},
        inherited: {},
        overrides: {},
        inherited_origins: {},
        revision: "one",
      };
    else if (path === "/api/organization/library-folders/ebook") {
      const body = route.request().postDataJSON();
      destination = {
        id: "dest",
        root_key: "library-ebook",
        medium: "ebook",
        enabled: true,
        mode: "hardlink",
        revision: "revision",
        ...body,
      };
      data = destination;
    } else if (path.endsWith("/setup-probe"))
      data = { id: "probe", status: "queued" };
    else if (path === "/api/activity")
      data = [
        {
          id: "probe",
          status: failure ? "failed" : "completed",
          message: failure
            ? "Downloads and library must share a filesystem"
            : "Verified",
        },
      ];
    else if (path.endsWith("/activate")) {
      verified = true;
      data = { ...destination, publication_available: true };
    }
    return route.fulfill({ json: data });
  });
  await page.goto("/settings#storage");
  await expect(page).toHaveURL(/#libraries$/);
  await expect(page.getByText("Library access", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("link", { name: "Saved profiles", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Choose ebooks folder" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Choose audiobooks folder" }),
  ).toBeVisible();
  await expect(
    page.getByText("Default libraries & download routes"),
  ).toHaveCount(0);
  await expect(page.getByText("Server setup instructions")).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("folders-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Choose ebooks folder" }).click();
  const dialog = page.getByRole("dialog", { name: "Choose ebooks folder" });
  await expect(dialog.getByText("/recordings", { exact: true })).toHaveCount(0);
  const defaultFolder = dialog.getByRole("radio", {
    name: "Books: /data/ebooks",
    exact: true,
  });
  await expect(defaultFolder).toBeChecked();
  await expect(dialog.getByLabel("Book Search folder path")).toHaveCount(0);
  await expect(dialog.getByText("Audio only", { exact: true })).toHaveCount(0);
  await dialog.getByRole("radio", { name: "Other path", exact: true }).check();
  await dialog.getByLabel("Book Search folder path").fill("/custom/ebooks");
  await defaultFolder.check();
  await expect(dialog.getByLabel("Book Search folder path")).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: "Use this folder" }),
  ).toBeEnabled();
  await dialog.screenshot({
    path: testInfo.outputPath("folder-picker-desktop.png"),
  });
  failure = true;
  await dialog.getByRole("button", { name: "Use this folder" }).click();
  await expect(
    dialog.getByText("Downloads and library must share a filesystem"),
  ).toBeVisible();
  expect(writes.some((w) => w.path.endsWith("/activate"))).toBe(false);
  failure = false;
  await dialog.getByRole("button", { name: "Use this folder" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("Hardlinks verified")).toBeVisible();
  expect(writes.filter((w) => w.path.endsWith("/ebook"))[1].body).toMatchObject(
    {
      destination_id: "dest",
      expected_revision: "revision",
      backend_path: "/data/ebooks",
      local_path: "/data/ebooks",
    },
  );
  expect(writes.find((w) => w.path.endsWith("/activate"))?.body.automatic).toBe(
    true,
  );
  await page
    .getByRole("button", { name: "Disable automatic import", exact: true })
    .click();
  await expect(
    page.getByText("Automatic import is off", { exact: true }),
  ).toBeVisible();
  expect(
    writes.find((w) => w.path.endsWith("/automatic-import"))?.body.enabled,
  ).toBe(false);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: testInfo.outputPath("folders-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Change ebooks folder" }).click();
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("checkbox", { name: "Auto-organize downloads" }),
  ).not.toBeChecked();
  await dialog.getByRole("radio", { name: "Other path", exact: true }).check();
  await expect(dialog.getByLabel("Book Search folder path")).toHaveValue(
    "/data/ebooks",
  );
  await dialog.screenshot({
    path: testInfo.outputPath("folder-picker-mobile.png"),
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Change ebooks folder" }),
  ).toBeFocused();
  expect(errors).toEqual([]);
});

test("resuming folder setup shows both media choices", async ({ page }) => {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path === "/api/auth/me")
      data = {
        user: {
          id: "reader",
          role: "admin",
          display_name: "Reader",
          onboarding_status: "deferred",
        },
        csrf_token: "test",
      };
    if (path === "/api/setup/onboarding")
      data = { status: "deferred", step: 4, skipped: [] };
    if (path === "/api/setup/readiness")
      data = { libraries: [], sources: [], downloaders: [] };
    if (path.startsWith("/api/acquisition/preferences/"))
      data = {
        effective: {},
        overrides: {},
        inherited: {},
        inherited_origins: {},
      };
    return route.fulfill({ json: data });
  });
  await page.goto("/onboarding");
  await expect(
    page.getByRole("heading", { name: "Library folders", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Choose ebooks folder" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Choose audiobooks folder" }),
  ).toBeVisible();
});
