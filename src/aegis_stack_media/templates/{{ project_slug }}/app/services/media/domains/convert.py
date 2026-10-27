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

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import get_storage
from app.core.time import utcnow
from app.services.media import queries
from app.services.media.adapters import ffmpeg, profiles
from app.services.media.models import MediaJob

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
    "thumbnail": (".png", "image/png"),
    "video": (".mp4", "video/mp4"),
}
"""Each kind's output suffix and media type: one table, read by the plan
and by the row that records what was stored."""

Report = Callable[[str], None]


@dataclass(frozen=True)
class Plan:
    """One conversion, as ffmpeg will hear it."""

    pre: tuple[str, ...]
    """Options before ``-i``: a seek belongs here, or it decodes first."""
    options: tuple[str, ...]
    suffix: str
    content_type: str


def _seconds(value: float) -> str:
    """A number of seconds as ffmpeg's own spelling (``1.5``, not ``1.5s``)."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _trim(profile: profiles.Profile, pre: list[str], options: list[str]) -> None:
    """``start``/``end`` as a seek and a duration: a duration because
    ``-to`` after an input seek counts from the seek, not the file."""
    if profile.start is not None:
        pre += ["-ss", _seconds(profile.start)]
    if profile.end is not None and profile.start is not None:
        options += ["-t", _seconds(profile.end - profile.start)]


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
    if profile.kind == "gif":
        w, f = width or profile.width or 960, fps or profile.fps or 12
        options += [
            "-vf",
            f"fps={f},scale={w}:-1:flags=lanczos,"
            "split[a][b];[a]palettegen[p];[b][p]paletteuse",
            "-loop",
            "0",
        ]
    elif profile.kind == "audio":
        options += ["-vn", "-c:a", "libmp3lame", "-b:a", profile.bitrate or "192k"]
    elif profile.kind == "image":
        options += [
            "-vf",
            f"scale={profile.width or 1600}:-1:flags=lanczos",
            "-frames:v",
            "1",
        ]
    elif profile.kind == "thumbnail":
        pre += ["-ss", _seconds(profile.at if profile.at is not None else 1.0)]
        options += [
            "-frames:v",
            "1",
            "-vf",
            f"scale={profile.width or 640}:-1:flags=lanczos",
        ]
    else:  # video
        options += [
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
    _trim(profile, pre, options)
    return Plan(tuple(pre), tuple(options), suffix, content_type)


def source_suffix(name: str | None) -> str:
    """The extension ffmpeg should assume for the input.

    Taken from the name the upload came with; a nameless upload lets
    ffmpeg probe the bytes, which it does on its own.
    """
    return Path(name or "").suffix.lower()


async def convert(
    data: bytes,
    *,
    profile_name: str,
    source_name: str | None,
) -> tuple[bytes, Plan]:
    """Run ``profile_name`` over ``data``; the bytes and the plan that made them.

    A profile with ``max_bytes`` (a GIF's cap) is retried at a smaller
    width and frame rate until it fits or the floor is reached; the
    caller stores whatever the last attempt produced.
    """
    profile = profiles.get(profile_name)
    made = plan(profile)
    output = await _run(made, data, source_name)
    if profile.kind != "gif" or profile.max_bytes is None:
        return output, made
    width, fps = profile.width or 960, profile.fps or 12
    for _ in range(MAX_ATTEMPTS):
        if len(output) <= profile.max_bytes or width <= MIN_WIDTH:
            break
        width = max(MIN_WIDTH, int(width * SHRINK))
        fps = max(MIN_FPS, fps - 2)
        made = plan(profile, width=width, fps=fps)
        output = await _run(made, data, source_name)
    return output, made


async def _run(made: Plan, data: bytes, source_name: str | None) -> bytes:
    return await ffmpeg.convert(
        made.options,
        pre=made.pre,
        source=data,
        source_suffix=source_suffix(source_name),
        output_suffix=made.suffix,
    )


async def submit(
    session: AsyncSession,
    data: bytes,
    *,
    profile_name: str,
    source_name: str | None,
    content_type: str | None = None,
) -> MediaJob:
    """Store the source and record the job, queued, not yet run.

    The profile is resolved here, so an unknown one is refused before
    anything is written to the bucket.
    """
    profiles.get(profile_name)
    key = await get_storage().put(data, content_type=content_type)
    job = MediaJob(
        profile=profile_name,
        source_key=key,
        source_name=source_name,
        source_bytes=len(data),
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
            source, profile_name=job.profile, source_name=job.source_name
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


async def fail(session: AsyncSession, job: MediaJob, message: str) -> MediaJob:
    """Mark the job failed with the reason ffmpeg or the store gave."""
    job.status = "failed"
    job.error = message[:1000]
    job.finished_at = utcnow()
    await session.flush()
    return job
