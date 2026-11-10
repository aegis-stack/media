"""What the media service has been doing, for every frontend.

The numbers the charts draw and the strings a job's row reads, computed
here once, so the Overseer page and the Flet modal show the same values
and neither formats a size or a time of its own.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import PurePath

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.formatting import format_bytes, format_relative_time
from app.core.time import utcnow
from app.services.media import queries
from app.services.media.adapters import profiles
from app.services.media.domains.convert import KINDS, ONE_FRAME, resolve
from app.services.media.models import MediaJob
from app.services.media.schemas import (
    DayCount,
    Figure,
    MediaActivity,
    MediaStats,
    ProfileTotal,
)

DAYS = 14
"""Days the jobs-per-day chart covers, today last."""
TONES = {"done": "ok", "failed": "error", "running": "warn"}
"""A status's colour, by what it means; a waiting job has none."""
EMPTY_BYTES = 16
"""A source this small held nothing ffmpeg could read, whatever it said."""
REASONS = (
    ("no longer stored", "The original file is gone from storage"),
    ("moov atom not found", "The recording was cut off before it finished saving"),
    ("Invalid data found", "That isn't a video, recording or image"),
    ("does not contain any stream", "There is nothing in that file to use"),
    ("matches no streams", "There is nothing in that file to use"),
    ("timed out", "It took too long and was stopped"),
    # A frame or trim past the end: ffmpeg succeeds and writes nothing.
    ("produced no output", "The file ends before the point asked for"),
)
"""What ffmpeg or the store said, in plain words; first match wins. The
whole output stays on the row for the Activity table."""
UNKNOWN_REASON = "It didn't work. The details are under Activity."
CHARTS = {"daily": "Jobs per day", "mix": "Profile mix", "bytes": "In and out"}
"""Each chart's title, the same on the page and in the modal."""
_SUFFIXES = {content_type: suffix for suffix, content_type in KINDS.values()}
_PICTURES = ("image/",)
"""Results a README can show inline, so they copy as Markdown."""


async def activity(db: AsyncSession, *, days: int = DAYS) -> MediaActivity:
    """Jobs per day (a day with none still there, as zeros) and the
    per-profile totals, in two grouped reads."""
    # ponytail: days are UTC days, as the rows store them; the viewer's own
    # midnight when someone far from UTC reads the chart.
    since = (utcnow() - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    counts = {
        (day, status): count
        for day, status, count in await queries.daily_counts(db, since=since)
    }
    dates = [(since + timedelta(days=n)).date() for n in range(days)]
    return MediaActivity(
        days=[
            DayCount(
                label=f"{day:%b} {day.day}",
                done=counts.get((day.isoformat(), "done"), 0),
                failed=counts.get((day.isoformat(), "failed"), 0),
            )
            for day in dates
        ],
        profiles=[
            ProfileTotal(name=name, jobs=jobs, source_bytes=source, output_bytes=output)
            for name, jobs, source, output in await queries.profile_totals(db)
        ],
    )


async def estimate(
    db: AsyncSession,
    profile_name: str,
    source_bytes: int,
    *,
    duration: float | None = None,
    end: float | None = None,
) -> int | None:
    """About how big the result will be, from what this profile made before.

    A picture is about the size the profile's pictures were; anything else
    is the source, cut to the share of its ``duration`` the trim keeps
    (the job's ``end``, else the saved one), times the profile's own
    out-to-in ratio, held to a GIF's cap. The profile is the one the run
    would use (``resolve``). None before the first result: a number with no
    history behind it would be a guess dressed as one.
    """
    # ponytail: a ratio over every past result, not per source format or
    # length; good to within the "about" the page says.
    done = (await queries.done_totals(db)).get(profile_name)
    if not done or not done[1]:
        return None
    jobs, given, made = done
    profile = await resolve(db, profile_name, end)
    if profile.kind in ONE_FRAME:
        return made // jobs
    guess = int(source_bytes * _share(profile, duration) * made / given)
    return min(guess, profile.max_bytes) if profile.max_bytes else guess


def _share(profile: profiles.Profile, duration: float | None) -> float:
    """How much of a ``duration``-second source the profile's trim keeps."""
    if not duration:
        return 1.0
    start, end = profile.start or 0.0, profile.end
    if end is None:
        kept = duration - start
    else:
        kept = -end if end < 0 else end - start
    return max(0.0, min(1.0, kept / duration))


def reason(job: MediaJob) -> str:
    """Why a job failed, as a person would say it; empty when it did not."""
    if job.status != "failed":
        return ""
    if job.source_bytes < EMPTY_BYTES:
        return f"The file was empty ({format_bytes(job.source_bytes)})"
    error = job.error or ""
    return next((said for found, said in REASONS if found in error), UNKNOWN_REASON)


def _download(job: MediaJob) -> tuple[str, str]:
    """The result's file name, named for its source and profile, and the
    Markdown that shows it (pictures only)."""
    suffix = _SUFFIXES.get(job.content_type or "")
    if job.status != "done" or suffix is None:
        return "", ""
    stem = PurePath(job.source_name or "").stem or f"media-{job.id}"
    filename = f"{stem}-{job.profile}{suffix}"
    picture = (job.content_type or "").startswith(_PICTURES)
    return filename, f"![{stem}]({filename})" if picture else ""


def figures(stats: MediaStats) -> list[Figure]:
    """The headline numbers over the charts."""
    return [
        Figure(label="Jobs", value=f"{stats.jobs:,}"),
        Figure(label="Done", value=f"{stats.done:,}", tone="ok"),
        Figure(
            label="Failed",
            value=f"{stats.failed:,}",
            tone="error" if stats.failed else "",
        ),
        Figure(label="Stored", value=format_bytes(stats.output_bytes)),
    ]


def job_row(job: MediaJob) -> dict[str, str]:
    """One job as display strings; empty where there is nothing yet."""
    shipped = profiles.all_profiles().get(job.profile)
    filename, markdown = _download(job)
    return {
        "id": str(job.id),
        "profile": job.profile,
        "title": (shipped.title if shipped else "") or job.profile,
        "kind": shipped.kind if shipped else "",
        "status": job.status,
        "tone": TONES.get(job.status, ""),
        "source": format_bytes(job.source_bytes),
        "output": format_bytes(job.output_bytes) if job.output_bytes else "",
        "when": format_relative_time(job.created_at),
        "error": job.error or "",
        "reason": reason(job),
        "filename": filename,
        "markdown": markdown,
    }
