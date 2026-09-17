from functools import lru_cache

import procrastinate
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

tasks = procrastinate.Blueprint()


@lru_cache
def get_queue() -> procrastinate.App:
    # Register task definitions before building the queue's task registry.
    from app.jobs import tasks as _tasks  # noqa: F401

    queue = procrastinate.App(
        connector=procrastinate.PsycopgConnector(
            conninfo=get_settings().psycopg_url,
            min_size=1,
            max_size=4,
            kwargs={"options": "-csearch_path=public,book_queue"},
        )
    )
    queue.add_tasks_from(tasks, namespace="")
    return queue


async def enqueue(db: AsyncSession, task_name: str, **kwargs) -> int:
    """Join the caller's psycopg transaction; never commit or open another one."""
    await db.flush()
    connection = await db.connection()
    raw = await connection.get_raw_connection()
    task = get_queue().tasks[task_name]
    return await task.configure(connection=raw.driver_connection).defer_async(**kwargs)
