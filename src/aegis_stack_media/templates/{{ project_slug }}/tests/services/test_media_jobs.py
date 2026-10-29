"""The job's two doors: the row's own state, and the queue's task name.

A worker task renamed in the queue module and not in ``start_conversion``
is a job that is queued and never runs - the failure mode is silent, so
the name is pinned here rather than discovered in production.
"""

from __future__ import annotations

import pytest

from app.services.media import jobs


@pytest.mark.asyncio
async def test_an_unknown_job_is_a_lookup_error_not_an_empty_result() -> None:
    with pytest.raises(LookupError):
        await jobs.run_conversion(10_000_000)


def test_the_queues_task_is_the_one_dispatch_asks_for() -> None:
    from app.components.worker.queues import media as queue

    assert hasattr(queue, "convert_media_task")
    source = jobs.start_conversion.__module__
    assert source.endswith("media.jobs")


@pytest.mark.asyncio
async def test_start_conversion_hands_the_task_to_this_plugins_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin's queue is its own name, not a framework enum member.

    ``QueueName`` lists the queues the stack ships; asking it for ``MEDIA``
    raised ``AttributeError`` at the first conversion on a fresh 0.17.0
    stack (the dead member was removed with framework #1869), and the job
    sat ``queued`` forever. The enqueue target is pinned here.
    """
    from app.components.worker import pools
    from app.services.media.jobs import QUEUE

    calls: list[tuple[str, str | None]] = []

    async def fake_enqueue(
        task_name: str, queue_type: str | None = None, *args: object, **kwargs: object
    ) -> str:
        calls.append((task_name, queue_type))
        return "handle"

    monkeypatch.setattr(pools, "enqueue_task", fake_enqueue)
    monkeypatch.setattr(pools, "job_id", lambda handle: "job-1")

    assert await jobs.start_conversion(7) == "job-1"
    assert calls == [("convert_media_task", "media")]
    assert QUEUE == "media"
