"""The reads: one statement each, and counts that do not drift.

Everything the service asks the database lives in ``queries.py``, so these
tests are the whole read surface: a new screen does not get to write its
own SELECT.
"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.media import queries
from app.services.media.models import MediaJob


async def _job(db: AsyncSession, **fields) -> MediaJob:
    body = {
        "profile": "png",
        "source_key": "sha256/aa/bb/" + "0" * 64,
        "source_bytes": 100,
        **fields,
    }
    job = MediaJob(**body)
    db.add(job)
    await db.flush()
    return job


@pytest.mark.asyncio
async def test_an_empty_store_says_zero_rather_than_failing(
    async_db_session: AsyncSession,
) -> None:
    jobs, done, failed, source_bytes, output_bytes, last = await queries.totals(
        async_db_session
    )
    assert (jobs, done, failed, source_bytes, output_bytes, last) == (
        0,
        0,
        0,
        0,
        0,
        None,
    )


@pytest.mark.asyncio
async def test_totals_count_each_state_and_sum_both_sides(
    async_db_session: AsyncSession,
) -> None:
    await _job(async_db_session, status="done", source_bytes=10, output_bytes=4)
    await _job(async_db_session, status="failed", source_bytes=20)
    await _job(async_db_session, status="queued", source_bytes=30)
    jobs, done, failed, source_bytes, output_bytes, _ = await queries.totals(
        async_db_session
    )
    assert (jobs, done, failed, source_bytes, output_bytes) == (3, 1, 1, 60, 4)


@pytest.mark.asyncio
async def test_recent_jobs_are_newest_first_and_filter_by_status(
    async_db_session: AsyncSession,
) -> None:
    first = await _job(async_db_session, status="failed")
    second = await _job(async_db_session, status="done")
    order = [job.id for job in await queries.recent_jobs(async_db_session)]
    assert order == [second.id, first.id]
    only_done = await queries.recent_jobs(async_db_session, status="done")
    assert [job.id for job in only_done] == [second.id]


@pytest.mark.asyncio
async def test_profile_counts_group_by_profile(
    async_db_session: AsyncSession,
) -> None:
    await _job(async_db_session, profile="readme-gif")
    await _job(async_db_session, profile="readme-gif")
    await _job(async_db_session, profile="mp3")
    counts = dict(await queries.profile_counts(async_db_session))
    assert counts["readme-gif"] == 2
    assert counts["mp3"] == 1


@pytest.mark.asyncio
async def test_a_job_is_found_by_id_and_a_missing_one_is_none(
    async_db_session: AsyncSession,
) -> None:
    job = await _job(async_db_session)
    assert (await queries.job_by_id(async_db_session, job.id or 0)) is job
    assert await queries.job_by_id(async_db_session, (job.id or 0) + 1000) is None
