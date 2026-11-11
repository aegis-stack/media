"""Applying a profile: running its recipe, and the row that remembers it.

``convert`` runs the recipe (``recipe.plan``) through the adapter, honours
a size cap by shrinking and re-running rather than hoping, and returns
what came out.

The row is written by ``submit`` (before anything runs) and completed by
``run``/``fail`` (after); nothing here commits. The caller that
opened the session owns the transaction, as every service function does.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
import tempfile

from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.database.models import StoredObject
from app.components.database.stored import release, store
from app.core.storage import get_storage
from app.core.time import utcnow
from app.services.media import queries
from app.services.media.adapters import ffmpeg, profiles, webp
from app.services.media.domains.recipe import Plan, plan, source_suffix, window
from app.services.media.models import MediaJob, MediaProfile

MAX_ATTEMPTS = 4
"""How many times a capped GIF is shrunk before its size is reported as is:
four halvings of the pixel count, which is enough for any real source."""

SHRINK = 0.75
MIN_WIDTH = 160
"""Below this a GIF is not a GIF of anything: the last attempt is kept and
its size is shown, rather than a thumbnail pretending to be the result."""

MIN_FPS = 8


Report = Callable[[str], None]


SETTINGS = frozenset(MediaProfile.model_fields) - {"name", "updated_at"}
"""The columns of ``media_profile`` a project edits: one per setting."""


def merged(shipped: profiles.Profile, change: MediaProfile | None) -> dict[str, object]:
    """The shipped profile with this project's edits over it, as the
    fields ``profiles.Profile`` validates: an unset column keeps the
    shipped value, and one the profile does not use is not a setting of it
    (a row saved before its kind changed)."""
    settings = shipped.model_dump(exclude_none=True)
    if change is not None:
        used = SETTINGS - profiles.unused(shipped.kind, shipped.takes)
        settings |= change.model_dump(exclude_none=True, include=set(used))
    return settings


async def resolve(
    session: AsyncSession, name: str, end: float | None = None
) -> profiles.Profile:
    """The profile as a job runs it: shipped, then the project's saved
    settings, then the job's own ``end`` (``MediaJob.end``) for its trim."""
    settings = merged(profiles.get(name), await queries.profile_override(session, name))
    return profiles.checked(settings, end)


async def effective(session: AsyncSession, job: MediaJob) -> profiles.Profile:
    """The profile as this job runs it (``resolve``)."""
    return await resolve(session, job.profile, job.end)


async def convert(
    data: bytes,
    *,
    profile: profiles.Profile,
    source_name: str | None,
) -> tuple[bytes, Plan]:
    """Run ``profile`` over ``data``; the bytes and the plan that made them.

    A profile with ``max_bytes`` (a GIF's cap) is retried at a smaller
    width and frame rate until it fits or the floor is reached; the
    caller stores whatever the last attempt produced.

    An animated WebP goes in as its frames (``webp.frames``), which live
    as long as the attempts do. Audio has none to take: it fails at once
    there, rather than after every frame is written.
    """
    with tempfile.TemporaryDirectory(prefix="aegis-media-frames-") as work:
        listing = None
        if profile.kind != "audio":
            listing = await asyncio.to_thread(
                webp.frames, data, Path(work), **window(profile)
            )
        if listing is None:
            return await _attempts(data, profile, source_name, ())
        # The frames are the window: the plan seeks nothing.
        return await _attempts(
            listing, profile, "frames.ffconcat", webp.CONCAT, seek=False
        )


async def _attempts(
    data: bytes,
    profile: profiles.Profile,
    source_name: str | None,
    before: tuple[str, ...],
    *,
    seek: bool = True,
) -> tuple[bytes, Plan]:
    """``convert``'s runs: ``before`` are input options ahead of the plan's."""
    made = plan(profile, seek=seek)
    output = await _run(made, data, source_name, before)
    if profile.kind != "gif" or profile.max_bytes is None:
        return output, made
    width, fps = profile.width or 960, profile.fps or 12
    for _ in range(MAX_ATTEMPTS):
        if len(output) <= profile.max_bytes or width <= MIN_WIDTH:
            break
        # A GIF's size goes with its area: aim under the cap from the
        # overshoot, and never by less than SHRINK.
        aim = 0.9 * (profile.max_bytes / len(output)) ** 0.5
        width = max(MIN_WIDTH, int(width * min(SHRINK, aim)))
        fps = max(MIN_FPS, fps - 2)
        made = plan(profile, width=width, fps=fps, seek=seek)
        output = await _run(made, data, source_name, before)
    return output, made


async def _run(
    made: Plan, data: bytes, source_name: str | None, before: tuple[str, ...]
) -> bytes:
    return await ffmpeg.convert(
        made.options,
        pre=(*before, *made.pre),
        reads=made.reads,
        source=data,
        source_suffix=source_suffix(source_name),
        output_suffix=made.suffix,
    )


def _check(profile_name: str, end: float | None) -> None:
    """Refuse a job that could never run, before anything is stored: an
    unknown profile (``UnknownProfileError``), or a trim the profile
    cannot take: built as ``resolve`` builds it, less the saved settings,
    which were checked when saved."""
    profiles.checked(merged(profiles.get(profile_name), None), end)


async def submit(
    session: AsyncSession,
    data: bytes,
    *,
    profile_name: str,
    source_name: str | None,
    content_type: str | None = None,
    end: float | None = None,
) -> MediaJob:
    """Store the source and record the job, queued, not yet run.

    Checked here (``_check``), so nothing is written to the bucket for a
    job that could never run.
    """
    _check(profile_name, end)
    key = await store(session, data, content_type=content_type)
    return await _queue(
        session,
        key,
        profile_name=profile_name,
        source_name=source_name,
        source_bytes=len(data),
        end=end,
    )


async def submit_key(
    session: AsyncSession,
    key: str,
    *,
    profile_name: str,
    source_name: str | None = None,
    end: float | None = None,
) -> MediaJob:
    """Record a job for an object already in the bucket, queued, not run.

    The agent's way in: it names a stored source rather than uploading
    bytes. One another part put there without the catalog is catalogued
    here. Checked first (``_check``), and ``LookupError`` for a key the
    store lacks, so no row exists for a job that could never run.
    """
    _check(profile_name, end)
    catalogued = await session.get(StoredObject, key)
    if catalogued is None:
        data = await get_storage().get(key)
        if data is None:
            raise LookupError(f"nothing is stored under {key}")
        return await submit(
            session, data, profile_name=profile_name, source_name=source_name, end=end
        )
    return await _queue(
        session,
        key,
        profile_name=profile_name,
        source_name=source_name,
        source_bytes=catalogued.bytes,
        end=end,
    )


async def _queue(
    session: AsyncSession,
    key: str,
    *,
    profile_name: str,
    source_name: str | None,
    source_bytes: int,
    end: float | None,
) -> MediaJob:
    """The job's row, queued, for a source already catalogued."""
    job = MediaJob(
        profile=profile_name,
        source_key=key,
        source_name=source_name,
        source_bytes=source_bytes,
        end=end,
        status="queued",
    )
    session.add(job)
    await session.flush()
    return job


async def run(
    session: AsyncSession,
    media_job_id: int,
    *,
    report: Report | None = None,
) -> MediaJob:
    """Convert the job's source and record the result on the row.

    Failure is a recorded outcome, not an exception: the row is how the
    page and the CLI find out what happened, and a conversion that could
    not finish must not look the same as one still running.
    """
    job = await queries.job_by_id(session, media_job_id)
    if job is None:
        raise LookupError(f"no media job {media_job_id}")
    if report:
        report(f"Converting with {job.profile}...")
    job.status = "running"
    source = await get_storage().get(job.source_key)
    if source is None:
        return await fail(session, job, "the source object is no longer stored")
    try:
        output, made = await convert(
            source,
            profile=await effective(session, job),
            source_name=job.source_name,
        )
    except (ffmpeg.FfmpegError, ValueError) as exc:
        return await fail(session, job, str(exc))
    job.output_key = await store(session, output, content_type=made.content_type)
    job.output_bytes = len(output)
    job.content_type = made.content_type
    job.status = "done"
    job.finished_at = utcnow()
    await session.flush()
    return job


async def delete_result(session: AsyncSession, media_job_id: int) -> MediaJob:
    """Delete a job's result and keep the job: Activity is the history.

    The object is released (``stored``). The row is changed first, so the
    job is not its own holder.
    """
    job = await queries.job_by_id(session, media_job_id)
    if job is None or not job.output_key:
        raise LookupError(f"media job {media_job_id} has no result to delete")
    key, job.output_key = job.output_key, None
    await session.flush()
    await release(session, key)
    return job


async def fail(session: AsyncSession, job: MediaJob, message: str) -> MediaJob:
    """Mark the job failed with the reason ffmpeg or the store gave."""
    job.status = "failed"
    job.error = message[:1000]
    job.finished_at = utcnow()
    await session.flush()
    return job
