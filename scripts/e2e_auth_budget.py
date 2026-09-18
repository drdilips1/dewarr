"""Isolate browser scenarios' sign-in budgets without changing application limits."""

import os
from urllib.parse import urlsplit

import psycopg

url = os.environ.get(
    "BOOK_E2E_DATABASE_URL",
    "postgresql+psycopg://book@127.0.0.1:55438/book_search_browser_test",
)
if not urlsplit(url).path.endswith("_browser_test"):
    raise SystemExit("Auth fixture reset requires an isolated _browser_test database")
with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as connection:
    # Keep provider budgets and within-scenario authentication behavior intact.
    connection.execute("DELETE FROM rate_limits WHERE key LIKE 'login:%' OR key LIKE 'ip:%'")
