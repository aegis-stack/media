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
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import (
    dialog,
    form_fields,
    form_number,
    fragment,
    go_to,
    toast_response,
)
from app.core.db import get_async_db
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
    end: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Store the upload, record the job, hand it to the queue. ``end`` is
    the job's trim (``MediaJob.end``); the whole clip sends it empty, so it
    is read as text, not as a float."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return toast_response(
            f"Too large: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB is the limit here.",
            "error",
        )
    if not data:
        return toast_response("That file was empty.", "error")
    try:
        job = await MediaService().submit(
            db,
            data,
            profile_name=profile,
            source_name=file.filename,
            content_type=file.content_type,
            end=form_number(end, "end", float),
        )
    except ValueError as exc:
        return toast_response(str(exc), "error")
    await db.commit()
    if job.id is None:
        raise HTTPException(status_code=500, detail="the job was not recorded")
    await start_conversion(job.id)
    return go_to(overseer_media.PAGE, "Making it", "#overseer-main")


@router.post("/profiles/{name}")
async def save_profile(
    name: str,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Save one profile's settings as this project's (``media_profile``).

    The form is dynamic (which inputs exist depends on the kind), so the
    body is read field by field and the service decides what the profile
    does not take: an unknown key is ignored, an empty one clears.
    """
    try:
        await MediaService().update_profile(db, name, await form_fields(request))
    except ValueError as exc:
        return toast_response(str(exc), "error")
    await db.commit()
    return go_to(overseer_media.PAGE, f"Saved {name}", "#overseer-main")


@router.get("/estimate")
async def estimate(
    profile: str = "",
    size: str = "",
    duration: str = "",
    end: str = "",
    name: str = "",
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """About how big the chosen file comes out, and its line in the drop
    zone, from what the browser read off it. Strings in, because the
    form sends an empty field before a file is chosen."""
    try:
        body = await overseer_media.estimate_body(
            db,
            profile=profile,
            size=form_number(size, "size") or 0,
            duration=form_number(duration, "duration", float),
            end=form_number(end, "end", float),
            name=name,
        )
    except ValueError:
        body = {"file": name, "estimate": ""}
    return HTMLResponse(fragment(overseer_media.ESTIMATE_TEMPLATE, **body))


@router.get("/events")
async def events(section: str = "overview") -> Response:
    """A section kept live over SSE while it is open (``overseer_media.events``)."""
    return event_stream(overseer_media.events(section))


@router.get("/view/{media_job_id}")
async def view(
    media_job_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> HTMLResponse:
    """One result, larger, for the dialog: a gallery preview's click."""
    job = await MediaService().job(db, media_job_id)
    card = overseer_media.card_from(job) if job is not None else None
    if card is None or card["view"] is None:
        raise HTTPException(status_code=404, detail="Nothing to show for that one.")
    return HTMLResponse(fragment(overseer_media.VIEW_TEMPLATE, c=card))


@router.get("/confirm-delete/{media_job_id}", response_class=HTMLResponse)
async def confirm_delete(
    request: Request,
    media_job_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """The confirmation; its button sends the DELETE below."""
    job = await MediaService().job(db, media_job_id)
    card = overseer_media.card_from(job) if job is not None else None
    if card is None or card["delete"] is None:
        raise HTTPException(status_code=404, detail="Nothing to delete for that one.")
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=f"Delete this {card['title']}?",
        body=(
            f"{card['filename']} will be removed from storage once nothing "
            "else uses the same file. Its line under Activity stays. This "
            "cannot be undone."
        ),
        url=card["download"],
        label="Delete",
        method="delete",
        done="Deleted",
    )


@router.delete("/output/{media_job_id}", status_code=204)
async def delete_output(
    media_job_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Delete the result; the job stays for Activity."""
    try:
        await MediaService().delete_result(db, media_job_id)
    except LookupError:
        raise HTTPException(
            status_code=404, detail="Nothing to delete for that one."
        ) from None
    await db.commit()
    return Response(status_code=204)


@router.get("/output/{media_job_id}")
async def output(
    media_job_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """The result itself, streamed to the browser.

    Not a redirect to the bucket: a presigned URL names the S3 endpoint
    the containers use, which the browser cannot reach. One ownership
    check (the row must exist and be done), then the bytes.
    """
    from app.core.storage import get_storage

    job = await MediaService().job(db, media_job_id)
    if job is None or not job.has_result or job.output_key is None:
        raise HTTPException(status_code=404, detail="No result for that conversion.")
    data = await get_storage().get(job.output_key)
    return Response(
        content=data,
        media_type=job.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": "inline",
            # The result never changes: the key is its content hash.
            "Cache-Control": "private, max-age=3600",
        },
    )
