"""Context for the Overseer Media page's sections.

Three sections, because there are three things a person does with media:
see what this project can make, start one, and find what it made. The
reads go through ``MediaService`` on the request's session; a conversion
starts through ``jobs.start_conversion``, the same door the CLI uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.formatting import format_bytes, format_relative_time
from app.core.storage import get_storage
from app.services.media import SERVICE_NAME, queries
from app.services.media.models import MediaJob
from app.services.media.service import MediaService
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest, page_url
from .rendering import fragment, status_cell, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Convert", {"convert": "Convert"}),
    ("Results", {"results": "Results"}),
)

PAGE = page_url("services", SERVICE_NAME)
PARTIALS = "/partials/overseer/media"
JOB_TEMPLATE = "pages/overseer/media/_job.html"
JOB_PARAM = "job"
# ponytail: one screen of results, newest first. Paging when a project
# outgrows it; the bucket keeps everything either way.
LIST_SIZE = 50


def results_url(job_id: int | None = None) -> str:
    """The Results section, optionally with one job pinned under the table."""
    return (
        with_query(f"{PAGE}/results", **{JOB_PARAM: str(job_id)})
        if job_id
        else f"{PAGE}/results"
    )


def _status(job: MediaJob) -> dict[str, str]:
    """The job's state as the table's badge: colour by what it means."""
    tone = {"done": "ok", "failed": "error", "running": "warn"}.get(job.status, "")
    return status_cell(job.status, tone)


async def _link(job: MediaJob) -> str | None:
    """A time-limited link straight to the object, when the bucket gives one."""
    if job.status != "done" or not job.output_key:
        return None
    return await get_storage().presigned_url(job.output_key)


def job_view_from(job: MediaJob) -> dict[str, Any]:
    """One row, as the job template needs it. Pure, so the template is
    testable with a hand-made row and no database."""
    return {
        "job": job,
        "status": _status(job),
        "running": job.status in {"queued", "running"},
        "output": format_bytes(job.output_bytes) if job.output_bytes else None,
        "source": format_bytes(job.source_bytes),
        "when": format_relative_time(job.created_at),
    }


async def job_view(db: Any, media_job_id: int) -> dict[str, Any] | None:
    """One job, by id; None when the row is gone."""
    job = await queries.job_by_id(db, media_job_id)
    return job_view_from(job) if job is not None else None


def render_job(view: dict[str, Any]) -> str:
    """The one row, re-rendered for the poll that watches it."""
    return fragment(JOB_TEMPLATE, **view)


async def _overview(req: SectionRequest) -> dict[str, Any]:
    service = MediaService()
    stats = await service.stats(req.db)
    used = await queries.profile_counts(req.db)
    return {
        "figures": [
            {"label": "Jobs", "value": f"{stats.jobs:,}"},
            {"label": "Done", "value": f"{stats.done:,}"},
            {
                "label": "Failed",
                "value": f"{stats.failed:,}",
                "negative": stats.failed > 0,
            },
            {"label": "Stored", "value": format_bytes(stats.output_bytes)},
        ],
        "profiles": service.profiles(),
        "used": [{"label": name, "value": f"{count:,}"} for name, count in used],
    }


async def _convert(req: SectionRequest) -> dict[str, Any]:
    raw = req.query.get(JOB_PARAM) or ""
    view = await job_view(req.db, int(raw)) if raw.isdigit() else None
    return {"profiles": MediaService().profiles(), "job": view, "partials": PARTIALS}


async def _results(req: SectionRequest) -> dict[str, Any]:
    jobs = await queries.recent_jobs(req.db, limit=LIST_SIZE)
    links = await asyncio.gather(*(_link(job) for job in jobs))
    raw = req.query.get(JOB_PARAM) or ""
    return {
        "partials": PARTIALS,
        "job": await job_view(req.db, int(raw)) if raw.isdigit() else None,
        "rows": [
            {
                "id": job.id,
                "profile": job.profile,
                "status": _status(job),
                "source": format_bytes(job.source_bytes),
                "output": format_bytes(job.output_bytes) if job.output_bytes else None,
                "result": {"label": "Open", "url": link} if link else None,
                "when": format_relative_time(job.created_at),
                "error": job.error,
            }
            for job, link in zip(jobs, links, strict=True)
        ],
    }


BUILDERS: dict[str, Callable[[SectionRequest], Awaitable[dict[str, Any]]]] = {
    "overview": _overview,
    "convert": _convert,
    "results": _results,
}


async def section_context(
    section: str, media: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    return {"partials": PARTIALS} | await BUILDERS[section](req)
