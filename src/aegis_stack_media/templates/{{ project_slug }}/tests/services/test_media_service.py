"""The facade and the domain, end to end over a store and one real conversion.

A submit stores the bytes and records the job; a run converts and records
what came back; a source that has gone is a failed job with a reason, not
an exception the page has to catch.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import FilesystemStorage, get_storage, set_storage
from app.services.media.service import MediaService

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR42mP4z8CAFTEMLQkA"
    "KP8/wc53yE8AAAAASUVORK5CYII="
)


@pytest.fixture
def store(tmp_path: Path):
    """A filesystem store of its own per test: no bucket, no network."""
    set_storage(FilesystemStorage(tmp_path))
    yield tmp_path
    set_storage(None)


@pytest.mark.asyncio
async def test_submit_stores_the_source_and_queues_a_row(
    async_db_session: AsyncSession, store: Path
) -> None:
    job = await MediaService().submit(
        async_db_session,
        PNG_1PX,
        profile_name="png",
        source_name="pixel.png",
        content_type="image/png",
    )
    assert job.id is not None
    assert job.status == "queued"
    assert job.source_bytes == len(PNG_1PX)
    assert await get_storage().get(job.source_key) == PNG_1PX


@pytest.mark.asyncio
async def test_an_unknown_profile_is_refused_before_anything_is_stored(
    async_db_session: AsyncSession, store: Path
) -> None:
    with pytest.raises(KeyError):
        await MediaService().submit(
            async_db_session, b"x", profile_name="nope", source_name="x.png"
        )
    assert list(Path(store).rglob("*")) == []


@pytest.mark.asyncio
async def test_run_converts_the_source_and_records_the_result(
    async_db_session: AsyncSession, store: Path
) -> None:
    service = MediaService()
    job = await service.submit(
        async_db_session, PNG_1PX, profile_name="png", source_name="pixel.png"
    )
    done = await service.run(async_db_session, job.id or 0)
    assert done.status == "done"
    assert done.output_key and done.output_key != done.source_key
    assert done.content_type == "image/png"
    assert done.output_bytes and done.output_bytes > 0
    assert await get_storage().get(done.output_key or "") is not None


@pytest.mark.asyncio
async def test_a_source_that_has_gone_is_a_failed_job_with_the_reason(
    async_db_session: AsyncSession, store: Path
) -> None:
    service = MediaService()
    job = await service.submit(
        async_db_session,
        b"not really an image",
        profile_name="png",
        source_name="x.png",
    )
    await get_storage().delete(job.source_key)
    failed = await service.run(async_db_session, job.id or 0)
    assert failed.status == "failed"
    assert failed.error and "no longer stored" in failed.error


@pytest.mark.asyncio
async def test_a_conversion_that_ffmpeg_refuses_keeps_its_complaint(
    async_db_session: AsyncSession, store: Path
) -> None:
    service = MediaService()
    job = await service.submit(
        async_db_session,
        b"this is not a video",
        profile_name="mp3",
        source_name="x.mp3",
    )
    failed = await service.run(async_db_session, job.id or 0)
    assert failed.status == "failed"
    assert failed.error and "ffmpeg" in failed.error.lower()
