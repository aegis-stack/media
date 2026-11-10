"""Media jobs written as rows, for tests that read them back. A job's keys
point into the storage catalog (``stored_object``), so each is catalogued
first, as ``store`` would have."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.database.models import StoredObject
from app.core.db import insert
from app.core.time import utcnow
from app.services.media.models import MediaJob

SOURCE = "sha256/aa/bb/" + "0" * 64
OUTPUT = "sha256/cc/dd/" + "1" * 64


async def add_jobs(db: AsyncSession, *jobs: MediaJob) -> list[MediaJob]:
    """``jobs`` added and flushed, their keys catalogued."""
    keys = {k for job in jobs for k in (job.source_key, job.output_key) if k}
    await db.execute(
        insert(db, StoredObject)
        .values([{"key": k, "bytes": 0, "created_at": utcnow()} for k in keys])
        .on_conflict_do_nothing()
    )
    db.add_all(jobs)
    await db.flush()
    return list(jobs)
