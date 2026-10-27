"""Actions for the Overseer Media page: start a conversion, watch one.

Mounted by the plugin's ``RouterWiring`` rather than ``routes/pages.py``,
so the router carries the Overseer gate itself. A conversion starts
through ``jobs.start_conversion``, the same door the CLI uses, so the page
never knows whether a worker is doing the work.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_media
from app.components.web_frontend.overseer_access import overseer_gate
from app.components.web_frontend.rendering import go_to, toast_response
from app.core.db import get_async_db
from app.services.media.adapters.profiles import UnknownProfileError
from app.services.media.jobs import start_conversion
from app.services.media.service import MediaService

router = APIRouter(
    prefix=overseer_media.PARTIALS,
    dependencies=[Depends(overseer_gate)],
    include_in_schema=False,
)

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
"""What one upload may be. Above this the request is refused with the size
it had, rather than read into memory to find out: a phone video is
tens of megabytes, a container export is not what this page is for."""


@router.post("/convert")
async def start(
    request: Request,
    file: Annotated[UploadFile, File()],
    profile: Annotated[str, Form()],
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Store the upload, record the job, hand it to the queue."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return toast_response(
            f"Too large: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB is the limit here.",
            "error",
        )
    if not data:
        return toast_response("That file was empty.", "error")
    service = MediaService()
    try:
        job = await service.submit(
            db,
            data,
            profile_name=profile,
            source_name=file.filename,
            content_type=file.content_type,
        )
    except UnknownProfileError as exc:
        return toast_response(str(exc), "error")
    await db.commit()
    if job.id is None:
        raise HTTPException(status_code=500, detail="the job was not recorded")
    await start_conversion(job.id)
    return go_to(
        overseer_media.results_url(job.id),
        f"Converting with {job.profile}",
        "#overseer-main",
    )


@router.get("/jobs/{media_job_id}", response_class=HTMLResponse)
async def job_row(
    media_job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """One job, re-rendered for the poll that watches it."""
    view = await overseer_media.job_view(db, media_job_id)
    if view is None:
        raise HTTPException(status_code=404, detail="No such conversion.")
    return HTMLResponse(overseer_media.render_job(view))
