"""The agent's way in: one conversion it composes, a job back.

The tool starts the conversion and returns figures about it — an id, its
status, its profile — never the row, and never waiting: ffmpeg outlives the
request that asked for it, so the work belongs to ``run_conversion`` on the
queue. A profile the stack does not have is refused with the list of the
ones it does, because an agent should not have to guess.
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_async_session
from app.core.tools import register_tool
from app.services.media import jobs
from app.services.media.adapters import profiles
from app.services.media.service import MediaService


async def media(source: str, profile: str) -> dict[str, Any]:
    """Queue a conversion of a stored object, and say what was queued.

    ``source`` is a storage key the bucket already holds (what every
    completed upload, and every earlier job's result, is addressed by).
    """
    known = ", ".join(sorted(profiles.all_profiles()))
    try:
        profiles.get(profile)
    except profiles.UnknownProfileError:
        raise ValueError(
            f"unknown profile {profile!r}; this stack has: {known}"
        ) from None

    async with get_async_session() as session:
        job = await MediaService().submit_key(
            session, source, profile_name=profile, source_name=source
        )
        handle = await jobs.start_conversion(job.id)
        queued = {"id": job.id, "status": job.status, "profile": job.profile}
        await session.commit()
    return {**queued, "queued": bool(handle)}


register_tool(
    "media",
    media,
    description=(
        "Convert a stored object with one of the stack's media profiles "
        "(gif, audio, image, thumbnail, video); returns the job's id and status"
    ),
    effect="writes",
)
