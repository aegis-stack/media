"""Reads for the media service.

Every statement the service runs lives here: the page, the CLI and the
health check all come through these functions, so an N+1 audit is a read
of one file. No writes and no business logic - a conversion's row is
written by ``domains.convert`` on the session it was handed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.media.models import MediaJob, MediaProfile

LIST_SIZE = 200
"""Rows the results list carries. The table is a log a person reads, and a
screen of the newest is what they act on; paging is a later concern."""


async def job_by_id(db: AsyncSession, media_job_id: int) -> MediaJob | None:
    """One job, or None when the row is gone."""
    return (await db.exec(select(MediaJob).where(MediaJob.id == media_job_id))).first()


async def recent_jobs(
    db: AsyncSession,
    *,
    limit: int = LIST_SIZE,
    status: str | None = None,
    kept_only: bool = False,
) -> list[MediaJob]:
    """The newest jobs first, optionally only those in one state, or
    without the finished ones whose result was deleted (``kept_only``)."""
    stmt = select(MediaJob).order_by(MediaJob.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(MediaJob.status == status)
    if kept_only:
        stmt = stmt.where(
            (MediaJob.status != "done") | MediaJob.output_key.is_not(None)
        )
    return list((await db.exec(stmt)).all())


async def key_in_use(db: AsyncSession, key: str) -> bool:
    """Whether any job still holds this object, as its source or result:
    keys are content hashes, so two jobs can share one."""
    stmt = select(MediaJob.id).where(
        (MediaJob.output_key == key) | (MediaJob.source_key == key)
    )
    return (await db.exec(stmt.limit(1))).first() is not None


async def totals(
    db: AsyncSession,
) -> tuple[int, int, int, int, int, int, datetime | None]:
    """Jobs, done, failed, results kept, bytes in, bytes stored and the
    last finish, in one statement: aggregates over the same rows are one
    scan, not one round trip each. A result deleted is still done, but
    neither kept nor stored."""
    row = (
        await db.exec(
            select(
                func.count(MediaJob.id),
                func.sum(case((MediaJob.status == "done", 1), else_=0)),
                func.sum(case((MediaJob.status == "failed", 1), else_=0)),
                func.sum(case((MediaJob.output_key.is_not(None), 1), else_=0)),
                func.sum(MediaJob.source_bytes),
                func.sum(
                    case(
                        (MediaJob.output_key.is_not(None), MediaJob.output_bytes),
                        else_=0,
                    )
                ),
                func.max(MediaJob.finished_at),
            )
        )
    ).one()
    total, done, failed, kept, source_bytes, output_bytes, last = row
    return (
        int(total or 0),
        int(done or 0),
        int(failed or 0),
        int(kept or 0),
        int(source_bytes or 0),
        int(output_bytes or 0),
        last,
    )


async def profile_overrides(db: AsyncSession) -> dict[str, MediaProfile]:
    """Every profile this project has changed, by profile name.

    One query, not one per profile: the Profiles section shows all of them.
    """
    return {row.name: row for row in (await db.exec(select(MediaProfile))).all()}


async def profile_override(db: AsyncSession, name: str) -> MediaProfile | None:
    """The row for one profile, when this project has changed it."""
    return await db.get(MediaProfile, name)


async def profile_totals(db: AsyncSession) -> list[tuple[str, int, int, int]]:
    """Each profile's jobs, bytes in and bytes out, most used first: one
    grouped query, so the overview says what this project uses media for
    and what each conversion saves."""
    jobs = func.count(MediaJob.id)
    rows = await db.exec(
        select(
            MediaJob.profile,
            jobs,
            func.coalesce(func.sum(MediaJob.source_bytes), 0),
            func.coalesce(func.sum(MediaJob.output_bytes), 0),
        )
        .group_by(MediaJob.profile)
        .order_by(jobs.desc(), MediaJob.profile)
    )
    return [
        (str(profile), int(count), int(source), int(output))
        for profile, count, source, output in rows.all()
    ]


async def daily_counts(
    db: AsyncSession, *, since: datetime
) -> list[tuple[str, str, int]]:
    """Jobs made since ``since``, by day (``YYYY-MM-DD``, UTC) and status:
    one grouped query, the days with none left for the caller to fill."""
    day = func.date(MediaJob.created_at)
    rows = await db.exec(
        select(day, MediaJob.status, func.count(MediaJob.id))
        .where(MediaJob.created_at >= since)
        .group_by(day, MediaJob.status)
    )
    return [(str(d), str(status), int(count)) for d, status, count in rows.all()]


async def done_totals(db: AsyncSession) -> dict[str, tuple[int, int, int]]:
    """Each profile's finished jobs, bytes in and bytes out: what an
    estimate scales from. Failures are left out, or every one would pull
    the ratio towards nothing."""
    rows = await db.exec(
        select(
            MediaJob.profile,
            func.count(MediaJob.id),
            func.coalesce(func.sum(MediaJob.source_bytes), 0),
            func.coalesce(func.sum(MediaJob.output_bytes), 0),
        )
        .where(MediaJob.status == "done")
        .group_by(MediaJob.profile)
    )
    return {
        str(profile): (int(count), int(source), int(output))
        for profile, count, source, output in rows.all()
    }
