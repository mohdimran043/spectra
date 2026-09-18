"""Background task tracking.

``asyncio.create_task`` only holds a *weak* reference to the task it creates, so
a fire-and-forget task with no other reference can be garbage-collected while it
is still running — the work simply stops, with no error anywhere. That is
exactly what a long investigation looks like when it silently produces nothing.

Every background task therefore goes through ``spawn``, which keeps a strong
reference until the task completes and logs any exception that would otherwise
be swallowed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from spectra_config.logging import get_logger

log = get_logger(__name__)

_TASKS: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    """Run ``coro`` in the background, keeping it alive until it finishes."""
    task = asyncio.create_task(coro, name=name)
    _TASKS.add(task)
    task.add_done_callback(_finish)
    return task


def _finish(task: asyncio.Task[Any]) -> None:
    _TASKS.discard(task)
    if task.cancelled():
        log.info("background.cancelled", task=task.get_name())
        return
    error = task.exception()
    if error is not None:
        log.error(
            "background.failed",
            task=task.get_name(),
            error=str(error),
            error_type=type(error).__name__,
        )


def pending() -> int:
    """How many background tasks are currently in flight."""
    return len(_TASKS)


async def drain(timeout: float = 30.0) -> None:
    """Wait for in-flight tasks, used on shutdown so work is not lost."""
    if not _TASKS:
        return
    done, remaining = await asyncio.wait(set(_TASKS), timeout=timeout)
    if remaining:
        log.warning("background.drain_timeout", remaining=len(remaining))
