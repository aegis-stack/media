"""The media service's facade: what the page, the CLI and the jobs call.

Deliberately thin. Every method hands the session it was given to a
function in ``domains.convert`` or ``queries``; this class holds no rules
of its own, so there is one place per behaviour to read and change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.media import queries
from app.services.media.adapters import profiles
from app.services.media.adapters.profiles import (
    FIELDS,
    TRIM_FIELDS,
    TRIMS,
    UnknownProfileError,
    profile_fields,
)
from app.services.media.domains import activity as recent_activity
from app.services.media.domains import convert
from app.services.media.domains.activity import CHARTS
from app.services.media.models import MediaJob, MediaProfile
from app.services.media.schemas import (
    Figure,
    MediaActivity,
    MediaStats,
    ProfileSettings,
    ProfileView,
)

__all__ = [
    "CHARTS",
    "FIELDS",
    "TRIMS",
    "TRIM_FIELDS",
    "MediaJob",
    "MediaService",
    "UnknownProfileError",
    "profile_fields",
]
"""Callers outside the service take these from here: the job, the error a
profile name can raise, which settings each kind of profile uses, and the
charts' titles."""


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
        end: float | None = None,
    ) -> MediaJob:
        """Store the source and record the job, queued; ``end`` is its trim
        (``MediaJob.end``)."""
        return await convert.submit(
            session,
            data,
            profile_name=profile_name,
            source_name=source_name,
            content_type=content_type,
            end=end,
        )

    async def submit_key(
        self,
        session: AsyncSession,
        key: str,
        *,
        profile_name: str,
        source_name: str | None = None,
        end: float | None = None,
    ) -> MediaJob:
        """Record a job for an object already stored, queued; ``LookupError``
        when nothing is stored under ``key``."""
        return await convert.submit_key(
            session, key, profile_name=profile_name, source_name=source_name, end=end
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
        self,
        session: AsyncSession,
        *,
        limit: int = queries.LIST_SIZE,
        kept_only: bool = False,
    ) -> list[MediaJob]:
        """The newest jobs first; ``kept_only`` leaves out the finished ones
        whose result was deleted."""
        return await queries.recent_jobs(session, limit=limit, kept_only=kept_only)

    async def delete_result(self, session: AsyncSession, media_job_id: int) -> MediaJob:
        """Delete what a job made (the picture, the video), keeping the job
        for the history. ``LookupError`` when there is no result to delete."""
        return await convert.delete_result(session, media_job_id)

    async def stats(self, session: AsyncSession) -> MediaStats:
        """The figures the overview shows."""
        (
            jobs,
            done,
            failed,
            kept,
            source_bytes,
            output_bytes,
            last,
        ) = await queries.totals(session)
        return MediaStats(
            jobs=jobs,
            done=done,
            failed=failed,
            kept=kept,
            source_bytes=source_bytes,
            output_bytes=output_bytes,
            last_finished_at=last.isoformat() if last else None,
        )

    async def activity(
        self, session: AsyncSession, *, days: int = recent_activity.DAYS
    ) -> MediaActivity:
        """Jobs per day and per profile: what every frontend charts."""
        return await recent_activity.activity(session, days=days)

    def figures(self, stats: MediaStats) -> list[Figure]:
        """The headline numbers, the same on every frontend."""
        return recent_activity.figures(stats)

    def row(self, job: MediaJob) -> dict[str, str]:
        """One job as display strings, the same on every frontend."""
        return recent_activity.job_row(job)

    async def estimate(
        self,
        session: AsyncSession,
        profile_name: str,
        source_bytes: int,
        *,
        duration: float | None = None,
        end: float | None = None,
    ) -> int | None:
        """About how big ``profile_name`` makes a source this size and
        length, trimmed by ``end``; None until the profile has made
        something."""
        return await recent_activity.estimate(
            session, profile_name, source_bytes, duration=duration, end=end
        )

    def profiles(self) -> list[ProfileView]:
        """The profiles this project offers, in the order the file gives."""
        return [
            ProfileView(
                name=name,
                title=profile.title or name,
                description=profile.description,
                kind=profile.kind,
                takes=profile.takes,
            )
            for name, profile in profiles.all_profiles().items()
        ]

    async def profile_settings(self, session: AsyncSession) -> list[ProfileSettings]:
        """Every profile as this project has it: shipped defaults, then edits.

        A column the project never touched is absent from the row, so the
        shipped value stands. That keeps ``profiles.yml`` the vocabulary
        (adding a profile is still a data edit) while the tuning lives where
        every other setting lives.
        """
        overrides = await queries.profile_overrides(session)
        shipped = profiles.all_profiles()
        built: list[ProfileSettings] = []
        for view in self.profiles():
            merged = convert.merged(shipped[view.name], overrides.get(view.name))
            built.append(
                ProfileSettings(
                    **view.model_dump(exclude={"description"}),
                    description=str(merged.get("description", "")),
                    settings={
                        field: value
                        for field, value in merged.items()
                        if field not in ProfileView.model_fields
                    },
                )
            )
        return built

    async def update_profile(
        self, session: AsyncSession, name: str, changes: Mapping[str, Any]
    ) -> profiles.Profile:
        """Save one profile's settings as this project wants them.

        Validated against the same model the shipped file is validated
        against, so a range that would fail at load cannot be saved here
        either, and the model turns the form's text into the setting's type.
        An empty form field means "back to the shipped value": the column is
        cleared rather than copied. A key that is not a setting is ignored.
        """
        shipped = profiles.get(name)
        row = await queries.profile_override(session, name) or MediaProfile(name=name)
        edits = {
            field: str(value).strip() or None
            for field, value in changes.items()
            if field in convert.SETTINGS
        }
        settings = convert.merged(shipped, row) | {
            field: getattr(shipped, field) if value is None else value
            for field, value in edits.items()
        }
        try:
            updated = profiles.checked(settings)
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from None

        for field, value in edits.items():
            setattr(row, field, None if value is None else getattr(updated, field))
        row.updated_at = utcnow()
        session.add(row)
        await session.flush()
        return updated
