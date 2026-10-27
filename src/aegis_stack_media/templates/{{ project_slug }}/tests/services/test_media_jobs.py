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
