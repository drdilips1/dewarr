import os
import subprocess
from urllib.parse import urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

TEST_DATABASE = os.environ.get("BOOK_TEST_DATABASE_URL")
os.environ["BOOK_ENV_FILE"] = ""
if TEST_DATABASE:
    if not urlsplit(TEST_DATABASE).path.endswith("_test"):
        raise RuntimeError(
            "Integration tests require an isolated database whose name ends in _test"
        )
    os.environ["BOOK_DATABASE_URL"] = TEST_DATABASE
os.environ["BOOK_SECRET_KEY"] = Fernet.generate_key().decode()
os.environ["BOOK_PUBLIC_URL"] = "http://testserver"
os.environ["BOOK_COOKIE_SECURE"] = "false"


@pytest.fixture(scope="session")
def migrated_database():
    if not TEST_DATABASE:
        pytest.skip("Set BOOK_TEST_DATABASE_URL to an isolated PostgreSQL database")
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True)


@pytest.fixture
async def database(migrated_database):
    from app.db.models import Base
    from app.db.session import get_engine, session_factory
    from app.jobs.queue import get_queue

    tables = ", ".join(f'public."{name}"' for name in Base.metadata.tables)
    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                f"TRUNCATE {tables}, book_queue.procrastinate_jobs, "
                "book_queue.procrastinate_workers RESTART IDENTITY CASCADE"
            )
        )
    async with get_queue().open_async():
        yield session_factory()
    await get_engine().dispose()
    get_engine.cache_clear()
    get_queue.cache_clear()


@pytest.fixture
async def client(database):
    from app.main import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as client:
        yield client


@pytest.fixture
async def admin(client):
    response = await client.post(
        "/api/auth/bootstrap",
        json={
            "username": "admin",
            "password": "a long test password",
            "display_name": "Test admin",
        },
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()["user"]
