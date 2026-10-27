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

from app.services.media.models import MediaJob

LIST_SIZE = 200
"""Rows the results list carries. The table is a log a person reads, and a
screen of the newest is what they act on; paging is a later concern."""


async def job_by_id(db: AsyncSession, media_job_id: int) -> MediaJob | None:
    """One job, or None when the row is gone."""
    return (await db.exec(select(MediaJob).where(MediaJob.id == media_job_id))).first()


async def recent_jobs(
    db: AsyncSession, *, limit: int = LIST_SIZE, status: str | None = None
) -> list[MediaJob]:
    """The newest jobs first, optionally only those in one state."""
    stmt = select(MediaJob).order_by(MediaJob.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(MediaJob.status == status)
    return list((await db.exec(stmt)).all())


async def totals(
    db: AsyncSession,
) -> tuple[int, int, int, int, int, datetime | None]:
    """Jobs, done, failed, bytes in, bytes out and the last finish, in one
    statement: four aggregates over the same rows is one scan, not four
    round trips."""
    row = (
        await db.exec(
            select(
                func.count(MediaJob.id),
                func.sum(case((MediaJob.status == "done", 1), else_=0)),
                func.sum(case((MediaJob.status == "failed", 1), else_=0)),
                func.sum(MediaJob.source_bytes),
                func.sum(MediaJob.output_bytes),
                func.max(MediaJob.finished_at),
            )
        )
    ).one()
    total, done, failed, source_bytes, output_bytes, last = row
    return (
        int(total or 0),
        int(done or 0),
        int(failed or 0),
        int(source_bytes or 0),
        int(output_bytes or 0),
        last,
    )


async def profile_counts(db: AsyncSession) -> list[tuple[str, int]]:
    """How many jobs each profile has run, biggest first: one grouped
    query, so the overview says what this project actually uses media
    for."""
    rows = await db.exec(
        select(MediaJob.profile, func.count(MediaJob.id))
        .group_by(MediaJob.profile)
        .order_by(func.count(MediaJob.id).desc(), MediaJob.profile)
    )
    return [(str(profile), int(count)) for profile, count in rows.all()]
