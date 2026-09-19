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
    from app.jobs.recovery_tasks import tasks as recovery_tasks

    queue.add_tasks_from(recovery_tasks, namespace="")
    return queue


class RecoveryApp(procrastinate.App):
    def _register_builtin_tasks(self) -> None:
        # Procrastinate 3.9.0 registers history cleanup in every ordinary App.
        # Recovery must preserve that history and permits only explicit recovery tasks.
        # Keep the pinned-version registry/isolation test when upgrading the queue.
        pass


def recovery_queue() -> procrastinate.App:
    from app.jobs.recovery_tasks import tasks as recovery_tasks

    queue = RecoveryApp(
        worker_defaults={"queues": ["recovery"], "concurrency": 1},
        connector=procrastinate.PsycopgConnector(
            conninfo=get_settings().psycopg_url,
            min_size=1,
            max_size=2,
            kwargs={"options": "-csearch_path=public,book_queue"},
        ),
    )
    queue.add_tasks_from(recovery_tasks, namespace="")
    if (
        set(queue.tasks)
        != {
            "recovery.scan",
            "recovery.reconcile",
            "recovery.inventory",
            "recovery.publication",
            "recovery.lists",
            "recovery.outbound",
            "recovery.commands",
        }
        or queue.periodic_registry.periodic_tasks
    ):
        raise RuntimeError("Recovery worker registry contains an unauthorized task")
    return queue


async def enqueue(db: AsyncSession, task_name: str, **kwargs) -> int:
    """Join the caller's psycopg transaction; never commit or open another one."""
    await db.flush()
    connection = await db.connection()
    raw = await connection.get_raw_connection()
    task = get_queue().tasks[task_name]
    return await task.configure(connection=raw.driver_connection).defer_async(**kwargs)
