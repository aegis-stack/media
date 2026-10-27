"""Media health: the binary is there, and the store answers.

A health row of its own rather than a bare "OK": the failure this service
actually has is ffmpeg missing from an image, and the row says so instead
of leaving it to the first person who uploads a video.
"""

from __future__ import annotations

from app.core.db import get_async_session
from app.services.media import SERVICE_NAME, queries
from app.services.media.adapters import ffmpeg
from app.services.system.models import ComponentStatus, ComponentStatusType


async def media_health() -> ComponentStatus:
    """Return health of the media service."""
    try:
        ffmpeg.binary()
    except ffmpeg.FfmpegError as exc:
        return ComponentStatus(
            name=SERVICE_NAME,
            status=ComponentStatusType.UNHEALTHY,
            message=str(exc),
            metadata={"subtitle": "Media"},
        )
    try:
        async with get_async_session() as session:
            jobs, done, failed, source_bytes, output_bytes, last = await queries.totals(
                session
            )
        return ComponentStatus(
            name=SERVICE_NAME,
            status=ComponentStatusType.HEALTHY,
            message="OK",
            metadata={
                "subtitle": "Media",
                "version": ffmpeg.version(),
                "jobs": jobs,
                "done": done,
                "failed": failed,
                "source_bytes": source_bytes,
                "output_bytes": output_bytes,
                "last_finished_at": last.isoformat() if last else None,
            },
        )
    except Exception as exc:  # noqa: BLE001 - a health check reports, never raises
        return ComponentStatus(
            name=SERVICE_NAME,
            status=ComponentStatusType.UNHEALTHY,
            message=f"media health check failed: {exc}",
            metadata={"subtitle": "Media", "version": ffmpeg.version()},
        )
