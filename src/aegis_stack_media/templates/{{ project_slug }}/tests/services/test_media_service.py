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

from app.components.database.models import StoredObject
from app.components.database.stored import purge, store
from app.core.storage import FilesystemStorage, get_storage
from app.services.media.models import MediaJob
from app.services.media.service import MediaService
from tests.services._media import SOURCE, add_jobs

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR42mP4z8CAFTEMLQkA"
    "KP8/wc53yE8AAAAASUVORK5CYII="
)


@pytest.mark.asyncio
async def test_submit_stores_the_source_and_queues_a_row(
    async_db_session: AsyncSession, files: FilesystemStorage
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
    assert await async_db_session.get(StoredObject, job.source_key) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile_name", "end", "refused", "said"),
    [
        ("nope", None, KeyError, "unknown media profile"),
        ("mp4", 0.0, ValueError, "keeps nothing"),
        ("png", -1.0, ValueError, "image takes no end"),
    ],
)
async def test_a_job_that_could_never_run_is_refused_before_anything_is_stored(
    async_db_session: AsyncSession,
    files: FilesystemStorage,
    tmp_path: Path,
    profile_name: str,
    end: float | None,
    refused: type[Exception],
    said: str,
) -> None:
    """An unknown profile, a trim that keeps nothing, or one on a still (one
    frame at the profile's ``at``, which a trim would not change)."""
    with pytest.raises(refused, match=said):
        await MediaService().submit(
            async_db_session,
            b"x",
            profile_name=profile_name,
            source_name="x.mov",
            end=end,
        )
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.queryspy(allow_n_plus_one=True)  # each call is the scenario
@pytest.mark.asyncio
async def test_a_stored_source_is_trimmed_the_same(
    async_db_session: AsyncSession, files: FilesystemStorage
) -> None:
    """The agent's way in names a stored object (a chat attachment, put
    there without the catalog); its trim is the page's, and the job's key
    into the catalog finds a row."""
    key = await files.put(PNG_1PX)
    job = await MediaService().submit_key(
        async_db_session, key, profile_name="mp4", end=-20.0
    )
    assert job.end == -20.0
    assert await async_db_session.get(StoredObject, key) is not None


@pytest.mark.asyncio
async def test_a_catalogued_source_is_not_read_to_queue_it(
    async_db_session: AsyncSession,
    files: FilesystemStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog knows its size: a large video is read once, by the run."""
    key = await store(async_db_session, PNG_1PX)

    async def unread(_key: str) -> bytes:
        raise AssertionError("read to queue it")

    monkeypatch.setattr(files, "get", unread)
    job = await MediaService().submit_key(async_db_session, key, profile_name="mp4")
    assert job.source_bytes == len(PNG_1PX)


@pytest.mark.asyncio
async def test_a_source_the_store_lacks_is_refused(
    async_db_session: AsyncSession, files: FilesystemStorage
) -> None:
    """Refused when asked, not recorded as a job that fails when run."""
    with pytest.raises(LookupError):
        await MediaService().submit_key(async_db_session, SOURCE, profile_name="mp4")


@pytest.mark.asyncio
async def test_run_converts_the_source_and_records_the_result(
    async_db_session: AsyncSession, files: FilesystemStorage
) -> None:
    service = MediaService()
    job = await service.submit(
        async_db_session, PNG_1PX, profile_name="photo-png", source_name="pixel.png"
    )
    done = await service.run(async_db_session, job.id or 0)
    assert done.status == "done"
    assert done.output_key and done.output_key != done.source_key
    assert done.content_type == "image/png"
    assert done.output_bytes and done.output_bytes > 0
    assert await get_storage().get(done.output_key or "") is not None


@pytest.mark.queryspy(allow_n_plus_one=True)  # each call is the scenario
@pytest.mark.asyncio
async def test_deleting_a_result_removes_the_file_and_keeps_the_history(
    async_db_session: AsyncSession, files: FilesystemStorage
) -> None:
    """The picture goes, from the bucket and from Recent; the job stays for
    Activity. Keys are content hashes, so a file another job also made is
    kept until the last one goes, and its row in the storage catalog with
    it."""
    service = MediaService()
    made = []
    for _ in range(2):
        job = await service.submit(
            async_db_session, PNG_1PX, profile_name="photo-png", source_name="p.png"
        )
        made.append(await service.run(async_db_session, job.id or 0))
    first, second = made
    key = first.output_key or ""
    assert key == second.output_key
    before = await service.stats(async_db_session)

    await service.delete_result(async_db_session, first.id or 0)
    assert await get_storage().get(key) is not None, "the other one still uses it"
    assert await async_db_session.get(StoredObject, key) is not None
    await service.delete_result(async_db_session, second.id or 0)
    assert await get_storage().get(key) is not None, "not until the purge"
    await purge(async_db_session)
    assert await get_storage().get(key) is None
    assert await async_db_session.get(StoredObject, key) is None

    kept = await service.recent(async_db_session, kept_only=True)
    assert [j.id for j in kept] == []
    assert len(await service.recent(async_db_session)) == 2
    after = await service.stats(async_db_session)
    assert (after.done, after.kept, after.output_bytes) == (2, 0, 0)
    assert before.kept == 2 and before.output_bytes > 0

    with pytest.raises(LookupError):
        await service.delete_result(async_db_session, first.id or 0)


@pytest.mark.asyncio
async def test_a_source_that_has_gone_is_a_failed_job_with_the_reason(
    async_db_session: AsyncSession, files: FilesystemStorage
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
    async_db_session: AsyncSession, files: FilesystemStorage
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


@pytest.mark.asyncio
async def test_update_profile_saves_an_override_the_settings_then_show(
    async_db_session: AsyncSession,
) -> None:
    service = MediaService()
    await service.update_profile(async_db_session, "web-gif", {"fps": "7", "kind": "x"})
    settings = {
        row.name: row.settings
        for row in await service.profile_settings(async_db_session)
    }
    assert settings["web-gif"]["fps"] == 7


@pytest.mark.asyncio
async def test_a_saved_setting_the_profile_does_not_use_is_not_applied(
    async_db_session: AsyncSession,
) -> None:
    """A row saved before a kind changed (or posted by hand) keeps a column
    the profile does not take: it is not one of its settings, so the job
    and the page still resolve."""
    from app.services.media.domains import convert
    from app.services.media.models import MediaProfile

    async_db_session.add(MediaProfile(name="thumb", end=5.0, width=320))
    await async_db_session.flush()
    profile = await convert.resolve(async_db_session, "thumb")
    assert (profile.end, profile.width) == (None, 320)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "changes", "said"),
    [
        ("web-gif", {"fps": "fast"}, "web-gif: fps"),
        ("web-gif", {"fps": "99"}, "web-gif: fps"),
        ("nope", {"fps": "7"}, "unknown media profile 'nope'"),
        ("thumb", {"end": "5"}, "thumb: thumbnail takes no end"),
    ],
)
async def test_update_profile_refuses_what_does_not_fit(
    async_db_session: AsyncSession, name: str, changes: dict[str, str], said: str
) -> None:
    """One ``ValueError`` for the page's toast, naming the profile and the
    setting; nothing is saved."""
    service = MediaService()
    with pytest.raises(ValueError) as refused:
        await service.update_profile(async_db_session, name, changes)
    assert str(refused.value).startswith(said)
    settings = {
        row.name: row.settings
        for row in await service.profile_settings(async_db_session)
    }
    assert settings["web-gif"]["fps"] != 99


@pytest.mark.queryspy(allow_n_plus_one=True)  # each call is the scenario
@pytest.mark.asyncio
async def test_an_empty_field_goes_back_to_the_shipped_value(
    async_db_session: AsyncSession,
) -> None:
    service = MediaService()
    await service.update_profile(async_db_session, "web-gif", {"fps": "7"})
    await service.update_profile(async_db_session, "web-gif", {"fps": " "})
    settings = {
        row.name: row.settings
        for row in await service.profile_settings(async_db_session)
    }
    assert settings["web-gif"]["fps"] == 15


@pytest.mark.asyncio
async def test_activity_counts_each_day_and_totals_each_profile(
    async_db_session: AsyncSession,
) -> None:
    """Every day drawn, an empty one as zeros; the same numbers both
    frontends chart."""
    from app.core.time import utcnow

    await add_jobs(
        async_db_session,
        *(
            MediaJob(
                profile=profile,
                source_key=SOURCE,
                source_bytes=100,
                output_bytes=output,
                status=status,
                created_at=utcnow(),
            )
            for profile, status, output in [
                ("png", "done", 40),
                ("png", "failed", None),
                ("mp3", "done", 10),
            ]
        ),
    )
    activity = await MediaService().activity(async_db_session, days=3)
    assert len(activity.days) == 3
    assert [(d.done, d.failed) for d in activity.days] == [(0, 0), (0, 0), (2, 1)]
    today = utcnow()
    assert activity.days[-1].label == f"{today:%b} {today.day}"
    assert [
        (p.name, p.jobs, p.source_bytes, p.output_bytes) for p in activity.profiles
    ] == [
        ("png", 2, 200, 40),
        ("mp3", 1, 100, 10),
    ]


def test_a_job_reads_the_same_in_every_frontend() -> None:
    from datetime import datetime

    from app.services.media.models import MediaJob

    job = MediaJob(
        id=3,
        profile="png",
        source_key=SOURCE,
        source_bytes=2048,
        status="failed",
        error="ffmpeg exited 1",
        created_at=datetime(2026, 1, 1),
    )
    row = MediaService().row(job)
    assert row["id"] == "3" and row["status"] == "failed"
    assert row["source"] == "2.0 KB" and row["output"] == ""
    assert row["error"] == "ffmpeg exited 1"


def test_profiles_are_named_for_what_you_get_in_the_files_order() -> None:
    """ "GIF for a README", not ``readme-gif``; the order the file gives."""
    views = MediaService().profiles()
    assert views[0].name == "readme-gif"
    assert views[0].title == "GIF for a README"
    assert views[0].description == "Sharp, under 5 MB"


def test_a_still_is_offered_what_a_still_can_become() -> None:
    """A PNG is not offered a video or its audio. The image thumbnail reads
    frame 0: a still has no second 1, and ffmpeg says so by making nothing."""
    from app.services.media.adapters import profiles
    from app.services.media.domains import recipe

    views = MediaService().profiles()
    takes = {
        kind: [v.name for v in views if kind in v.takes] for kind in ("image", "audio")
    }
    assert takes["image"] == ["photo-jpg", "photo-png", "photo-thumb"]
    assert takes["audio"] == ["mp3"]
    assert recipe.window(profiles.get("photo-thumb")) == {"at": 0.0}


def _failed(source_bytes: int, error: str, profile: str = "web-gif") -> MediaJob:
    from datetime import datetime

    return MediaJob(
        id=1,
        profile=profile,
        source_key=SOURCE,
        source_bytes=source_bytes,
        status="failed",
        error=error,
        created_at=datetime(2026, 1, 1),
    )


def test_a_failure_reads_in_plain_words() -> None:
    """ "The file was empty", not a red ``failed`` beside ``1 B``."""
    service = MediaService()
    assert service.row(_failed(1, "ffmpeg exited 1"))["reason"] == (
        "The file was empty (1 B)"
    )
    moov = "ffmpeg exited 183: moov atom not found"
    assert "cut off" in service.row(_failed(4096, moov))["reason"]
    assert service.row(_failed(4096, "ffmpeg produced no output file"))["reason"] == (
        "The file ends before the point asked for"
    )
    assert service.row(_failed(4096, "something new"))["reason"] == (
        "It didn't work. The details are under Activity."
    )


def test_a_finished_row_names_its_download_and_its_markdown() -> None:
    from datetime import datetime

    job = MediaJob(
        id=9,
        profile="readme-gif",
        source_key=SOURCE,
        source_name="demo-recording.mov",
        source_bytes=4096,
        output_bytes=2048,
        content_type="image/gif",
        status="done",
        created_at=datetime(2026, 1, 1),
    )
    row = MediaService().row(job)
    assert row["title"] == "GIF for a README"
    assert row["filename"] == "demo-recording-readme-gif.gif"
    assert row["markdown"] == "![demo-recording](demo-recording-readme-gif.gif)"


@pytest.mark.queryspy(allow_n_plus_one=True)  # each call is the scenario
@pytest.mark.asyncio
async def test_the_estimate_scales_what_the_profile_made_before(
    async_db_session: AsyncSession,
) -> None:
    """Before any history there is no guess; after, the profile's own
    ratio, the trimmed share, and a GIF's cap as this project saved it."""
    service = MediaService()
    assert await service.estimate(async_db_session, "mp4", 1000) is None
    await add_jobs(
        async_db_session,
        *(
            MediaJob(
                profile=profile,
                source_key=SOURCE,
                source_bytes=100,
                output_bytes=out,
                status="done",
            )
            for profile, out in [("mp4", 40), ("readme-gif", 100), ("png", 300)]
        ),
        MediaJob(profile="mp4", source_key=SOURCE, source_bytes=100, status="failed"),
    )
    assert (
        await service.estimate(async_db_session, "mp4", 1000, duration=40.0, end=20.0)
        == 200
    )
    assert (
        await service.estimate(async_db_session, "mp4", 1000, duration=40.0, end=-10.0)
        == 100
    )
    assert await service.estimate(async_db_session, "readme-gif", 10**8) == 5_000_000
    await service.update_profile(
        async_db_session, "readme-gif", {"max_bytes": "2000000"}
    )
    assert await service.estimate(async_db_session, "readme-gif", 10**8) == 2_000_000
    assert await service.estimate(async_db_session, "png", 10**8) == 300


@pytest.mark.queryspy(allow_n_plus_one=True)  # each call is the scenario
@pytest.mark.asyncio
async def test_a_run_uses_the_saved_settings_and_the_jobs_own_trim(
    async_db_session: AsyncSession,
) -> None:
    """A setting saved under "Adjust settings" is the one ffmpeg hears,
    and "First 5 s" trims this job only."""
    from app.services.media.domains import convert

    service = MediaService()
    await service.update_profile(async_db_session, "web-gif", {"fps": "8"})
    job = _failed(10, "")
    job.end = 5.0
    profile = await convert.effective(async_db_session, job)
    assert profile.fps == 8 and profile.width == 640
    assert (profile.start, profile.end) == (None, 5.0)
