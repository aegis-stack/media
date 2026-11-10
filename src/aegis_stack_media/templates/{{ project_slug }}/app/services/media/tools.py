"""The agent's way in: one conversion it composes, a job back.

The tool starts the conversion and returns figures about it — an id, its
status, its profile — never the row, and never waiting: ffmpeg outlives the
request that asked for it, so the work belongs to ``run_conversion`` on the
queue. A profile the stack does not have is refused (``Refused``) with the
list of the ones it does, because an agent should not have to guess.
"""

from __future__ import annotations

from app.core.db import get_async_session
from app.core.tools import Refused, register_tool
from app.services.media import jobs
from app.services.media.schemas import ConversionResult
from app.services.media.service import MediaService, UnknownProfileError


async def media(source: str, profile: str) -> ConversionResult | Refused:
    """Queue a conversion of a stored object, and say what was queued.

    ``source`` is a storage key the bucket already holds (what every
    completed upload, and every earlier job's result, is addressed by).
    """
    async with get_async_session() as session:
        try:
            job = await MediaService().submit_key(
                session, source, profile_name=profile, source_name=source
            )
        except UnknownProfileError as exc:
            return Refused(error=str(exc))
        queued = ConversionResult.model_validate(job, from_attributes=True)
        await session.commit()
    # After the commit, so the worker finds the row it is handed.
    await jobs.start_conversion(queued.id)
    return queued


register_tool(
    "media",
    media,
    description=(
        "Convert a stored object with one of the stack's media profiles "
        "(gif, audio, image, thumbnail, video); returns the job's id and status"
    ),
    effect="writes",
)
