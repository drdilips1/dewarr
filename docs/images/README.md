# UI screenshots

Captured from the actual Dewarr frontend with an isolated browser-test account and the bundled discovery catalog. Book covers and provider names belong to their respective owners. These are UI examples, not evidence of a connected production library or completed downloads.

To refresh them, start the disposable PostgreSQL browser-test database described in `../DEVELOPMENT.md`, then run:

```sh
npm --prefix apps/web run build
cd apps/web
DEWARR_SCREENSHOTS=1 npx playwright test screenshots.spec.ts --timeout=90000
```

The browser-test server resets only its dedicated `_browser_test` database. Never point it at your installation database.
