"""The media service's facade: what the page, the CLI and the jobs call.

Deliberately thin. Every method hands the session it was given to a
function in ``domains.convert`` or ``queries``; this class holds no rules
of its own, so there is one place per behaviour to read and change.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.media import queries
from app.services.media.adapters import profiles
from app.services.media.domains import convert
from app.services.media.models import MediaJob
from app.services.media.schemas import MediaStats, ProfileView


class MediaService:
    """Conversions over the object store, and what the store has produced.

    The only class in this service that holds state, and it holds none:
    a session arrives with each call, because the caller owns the unit of
    work (a request's dependency, a job's one session, a CLI command's).
    """

    async def submit(
        self,
        session: AsyncSession,
        data: bytes,
        *,
        profile_name: str,
        source_name: str | None = None,
        content_type: str | None = None,
    ) -> MediaJob:
        """Store the source and record the job, queued."""
        return await convert.submit(
            session,
            data,
            profile_name=profile_name,
            source_name=source_name,
            content_type=content_type,
        )

    async def run(
        self,
        session: AsyncSession,
        media_job_id: int,
        *,
        report: Callable[[str], None] | None = None,
    ) -> MediaJob:
        """Convert the job's source and record the outcome on its row."""
        return await convert.run(session, media_job_id, report=report)

    async def job(self, session: AsyncSession, media_job_id: int) -> MediaJob | None:
        """One job, by id."""
        return await queries.job_by_id(session, media_job_id)

    async def recent(
        self, session: AsyncSession, *, limit: int = queries.LIST_SIZE
    ) -> list[MediaJob]:
        """The newest jobs first."""
        return await queries.recent_jobs(session, limit=limit)

    async def stats(self, session: AsyncSession) -> MediaStats:
        """The figures the overview shows."""
        jobs, done, failed, source_bytes, output_bytes, last = await queries.totals(
            session
        )
        return MediaStats(
            jobs=jobs,
            done=done,
            failed=failed,
            source_bytes=source_bytes,
            output_bytes=output_bytes,
            last_finished_at=last.isoformat() if last else None,
        )

    def profiles(self) -> list[ProfileView]:
        """The profiles this project offers, by name."""
        return [
            ProfileView(name=name, description=profile.description, kind=profile.kind)
            for name, profile in sorted(profiles.all_profiles().items())
        ]
