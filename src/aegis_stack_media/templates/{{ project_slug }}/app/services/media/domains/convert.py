"""Applying a profile: the argv it becomes, and the row that remembers it.

Two functions, one per half of a conversion. ``plan`` is pure - a profile
and its overrides into the ffmpeg options, with no process and no bytes -
so the recipe is testable without a binary. ``convert`` runs it through
the adapter, honours a size cap by shrinking and re-running rather than
hoping, and returns what came out.

The row is written by ``submit`` (before anything runs) and completed by
``finish``/``fail`` (after); nothing here commits. The caller that
opened the session owns the transaction, as every service function does.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import tempfile

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import get_storage
from app.core.time import utcnow
from app.services.media import queries
from app.services.media.adapters import ffmpeg, profiles, webp
from app.services.media.models import MediaJob, MediaProfile

MAX_ATTEMPTS = 4
"""How many times a capped GIF is shrunk before its size is reported as is:
four halvings of the pixel count, which is enough for any real source."""

SHRINK = 0.75
MIN_WIDTH = 160
"""Below this a GIF is not a GIF of anything: the last attempt is kept and
its size is shown, rather than a thumbnail pretending to be the result."""

MIN_FPS = 8

KINDS: dict[str, tuple[str, str]] = {
    "gif": (".gif", "image/gif"),
    "audio": (".mp3", "audio/mpeg"),
    "image": (".png", "image/png"),
    "jpeg": (".jpg", "image/jpeg"),
    "thumbnail": (".png", "image/png"),
    "video": (".mp4", "video/mp4"),
}
"""Each kind's output suffix and media type: one table, read by the plan
and by the row that records what was stored."""

ONE_FRAME = frozenset(k for k, fields in profiles.FIELDS.items() if "at" in fields)
"""Kinds whose result is one frame of the source, picked by ``at``: their
size is the profile's, not the source's."""

Report = Callable[[str], None]


@dataclass(frozen=True)
class Plan:
    """One conversion, as ffmpeg will hear it."""

    pre: tuple[str, ...]
    """Options before ``-i``: a seek belongs here, or it decodes first."""
    options: tuple[str, ...]
    suffix: str
    content_type: str
    reads: int = 1
    """How many times the source is an input (``ffmpeg.convert``)."""


def _seconds(value: float) -> str:
    """A number of seconds as ffmpeg's own spelling (``1.5``, not ``1.5s``)."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def window(profile: profiles.Profile) -> dict[str, float | None]:
    """What of the source a profile reads: its trim, or for a kind without
    one the frame ``at`` picks. A thumbnail's is a second in, past a fade
    from black; any other's the first."""
    if profile.kind in profiles.TRIMS:
        return {"start": profile.start, "end": profile.end}
    if profile.at is not None:
        return {"at": profile.at}
    return {"at": 1.0 if profile.kind == "thumbnail" else 0.0}


def _cut(profile: profiles.Profile, pre: list[str], options: list[str]) -> None:
    """The ``window`` as seeks: the trim as a seek and a duration (``-to``
    after an input seek counts from the seek, not the file), a negative
    ``end`` as a seek from the end that needs no length known."""
    cut = window(profile)
    at, start, end = cut.get("at"), cut.get("start"), cut.get("end")
    if end is not None and end < 0:
        pre += ["-sseof", _seconds(end)]
        return
    if at or start:
        pre += ["-ss", _seconds(at or start or 0.0)]
    if end is not None:
        options += ["-t", _seconds(end - (start or 0.0))]


def plan(
    profile: profiles.Profile,
    *,
    width: int | None = None,
    fps: int | None = None,
) -> Plan:
    """The profile as argv. ``width``/``fps`` override the profile's own,
    which is how a capped GIF is retried smaller."""
    suffix, content_type = KINDS[profile.kind]
    pre: list[str] = []
    options: list[str] = []
    reads = 1
    if profile.kind == "gif":
        w, f = width or profile.width or 960, fps or profile.fps or 12
        look = f"fps={f},scale={w}:-1:flags=lanczos"
        # The palette from one read, used on a second, so the frames
        # stream: one read queued a 60 s clip's every frame (1.6 GB) until
        # the palette was done.
        options += [
            "-filter_complex",
            f"[0:v]{look},palettegen[p];[1:v]{look}[v];[v][p]paletteuse",
            "-an",
            "-loop",
            "0",
        ]
        reads = 2
    elif profile.kind == "audio":
        options += ["-vn", "-c:a", "libmp3lame", "-b:a", profile.bitrate or "192k"]
    elif profile.kind in ONE_FRAME:
        if w := profile.width or (640 if profile.kind == "thumbnail" else None):
            options += ["-vf", f"scale={w}:-1:flags=lanczos"]
        options += ["-frames:v", "1"]
    elif profile.kind == "jpeg":
        options += [
            "-vf",
            f"scale='min({profile.width or 1600},iw)':-2:flags=lanczos",
            "-frames:v",
            "1",
            "-q:v",
            "3",
        ]
    else:  # video
        # 4:2:0 and even sides, or phones and feeds refuse an RGB source
        # (a GIF, a screen recording); a width never grows the picture.
        w = f"min({profile.width},iw)" if profile.width else "iw"
        options += [
            "-vf",
            f"scale='trunc({w}/2)*2':-2:flags=lanczos",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            str(profile.crf if profile.crf is not None else 23),
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
    _cut(profile, pre, options)
    return Plan(tuple(pre), tuple(options), suffix, content_type, reads)


def source_suffix(name: str | None) -> str:
    """The extension ffmpeg should assume for the input.

    Taken from the name the upload came with; a nameless upload lets
    ffmpeg probe the bytes, which it does on its own.
    """
    return Path(name or "").suffix.lower()


SETTINGS = frozenset(MediaProfile.model_fields) - {"name", "updated_at"}
"""The columns of ``media_profile`` a project edits: one per setting."""


def merged(shipped: profiles.Profile, change: MediaProfile | None) -> dict[str, object]:
    """The shipped profile with this project's edits over it, as the
    fields ``profiles.Profile`` validates: an unset column keeps the
    shipped value."""
    settings = shipped.model_dump(exclude_none=True)
    if change is not None:
        settings |= change.model_dump(exclude_none=True, include=set(SETTINGS))
    return settings


async def resolve(
    session: AsyncSession, name: str, end: float | None = None
) -> profiles.Profile:
    """The profile as a job runs it: shipped, then the project's saved
    settings, then the job's own ``end`` (``MediaJob.end``) for its trim."""
    settings = merged(profiles.get(name), await queries.profile_override(session, name))
    if end is not None:
        settings |= {"start": None, "end": end}
    return profiles.Profile.model_validate(settings)


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
        whole = profile.model_copy(update={"start": None, "end": None, "at": 0.0})
        return await _attempts(listing, whole, "frames.ffconcat", webp.CONCAT)


async def _attempts(
    data: bytes,
    profile: profiles.Profile,
    source_name: str | None,
    before: tuple[str, ...],
) -> tuple[bytes, Plan]:
    """``convert``'s runs: ``before`` are input options ahead of the plan's."""
    made = plan(profile)
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
        made = plan(profile, width=width, fps=fps)
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
    """Refuse a job that could never run: an unknown profile
    (``UnknownProfileError``), or an ``end`` that keeps nothing."""
    profiles.get(profile_name)
    if end == 0:
        raise ValueError("end: 0 seconds keeps nothing")


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
    key = await get_storage().put(data, content_type=content_type)
    return await submit_key(
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
    source_bytes: int | None = None,
    end: float | None = None,
) -> MediaJob:
    """Record a job for an object already in the bucket, queued, not run.

    The agent's way in: it names a stored source rather than uploading
    bytes. Checked first (``_check``), so no row exists for a job that
    could never run.
    """
    _check(profile_name, end)
    job = MediaJob(
        profile=profile_name,
        source_key=key,
        source_name=source_name,
        source_bytes=source_bytes or 0,
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
    job.output_key = await get_storage().put(output, content_type=made.content_type)
    job.output_bytes = len(output)
    job.content_type = made.content_type
    job.status = "done"
    job.finished_at = utcnow()
    await session.flush()
    return job


async def delete_result(session: AsyncSession, media_job_id: int) -> MediaJob:
    """Delete a job's result and keep the job: Activity is the history.

    The object goes from the store only when no other job holds it (keys
    are content hashes: the same file made twice is one object). The row
    is changed first, so a store that fails leaves an unused object, never
    a row pointing at nothing.
    """
    job = await queries.job_by_id(session, media_job_id)
    if job is None or not job.output_key:
        raise LookupError(f"media job {media_job_id} has no result to delete")
    key, job.output_key = job.output_key, None
    await session.flush()
    if not await queries.key_in_use(session, key):
        await get_storage().delete(key)
    return job


async def fail(session: AsyncSession, job: MediaJob, message: str) -> MediaJob:
    """Mark the job failed with the reason ffmpeg or the store gave."""
    job.status = "failed"
    job.error = message[:1000]
    job.finished_at = utcnow()
    await session.flush()
    return job
