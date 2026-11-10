"""Context for the Overseer Media page's sections.

Two, split the way campaigns are: the Overview is for using it (drop a
file, pick what you want made, get it back) and Activity is the system
(jobs per day, the profile mix, every conversion with ffmpeg's own
words). The reads go through ``MediaService`` on the request's session;
a conversion starts through ``jobs.start_conversion``, the same door the
CLI uses.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.core.db import get_async_session
from app.core.formatting import format_bytes, format_clock
from app.services.media import SERVICE_NAME
from app.services.media.schemas import MediaActivity, ProfileSettings
from app.services.media.service import (
    CHARTS,
    FIELDS,
    TRIM_FIELDS,
    TRIMS,
    MediaJob,
    MediaService,
)
from app.services.system.models import ComponentStatus

from .overseer_live import fragments_events
from .overseer_nav import SectionRequest, page_url
from .rendering import fragment, status_cell, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("System", {"activity": "Activity"}),
)

WHOLE = "whole clip"
"""A trim left empty: a profile's, and the job's "Use"."""

PAGE = page_url("services", SERVICE_NAME)
ACTIVITY = f"{PAGE}/activity"
"""Activity: the charts and every conversion. The page itself (``PAGE``) is
the Overview, where a conversion starts and its result lands."""
PARTIALS = "/partials/overseer/media"
RESULTS_TEMPLATE = "pages/overseer/media/_results_table.html"
CHARTS_TEMPLATE = "pages/overseer/media/_activity_charts.html"
RECENT_TEMPLATE = "pages/overseer/media/_recent.html"
ESTIMATE_TEMPLATE = "pages/overseer/media/_estimate.html"
VIEW_TEMPLATE = "pages/overseer/media/_view.html"
# One stream per open section, re-read every couple of seconds and sent
# only when a fragment changed (``overseer_live``): the database is all it
# needs, so it works with no Redis and no worker behind the app.
EVENTS = f"{PARTIALS}/events"
EVENTS_INTERVAL_SECONDS = 2.0
RECENT_EVENT = "media-recent"
CHARTS_EVENT = "media-charts"
RESULTS_EVENT = "media-results"
RECENT = 8
"""Results the Overview's gallery shows; Activity has every one."""
# ponytail: one screen of results, newest first. Paging when a project
# outgrows it; the bucket keeps everything either way.
LIST_SIZE = 50
KIND_ICONS = {
    "gif": "gif",
    "video": "film",
    "image": "photo",
    "jpeg": "photo",
    "thumbnail": "squares-2x2",
    "audio": "musical-note",
}


def kind_icon(kind: str) -> str:
    """The picture beside a choice and on a result with no preview."""
    return KIND_ICONS.get(kind, "photo")


def profile_fields(kind: str, takes: tuple[str, ...]) -> tuple[str, ...]:
    """The inputs a profile of this kind offers. A still has one frame, so
    a profile only for stills has no ``at`` (a seek past it makes nothing)."""
    fields = FIELDS.get(kind, ())
    return tuple(f for f in fields if f != "at") if takes == ("image",) else fields


# The values a setting is picked from, so tuning a profile is choosing, not
# typing. A value a profile already has that is not here is still offered.
_MB = 1_000_000
FIELD_PRESETS: dict[str, tuple[int | float | str, ...]] = {
    "fps": (8, 10, 12, 15, 20, 24, 30),
    "width": (240, 320, 480, 640, 800, 960, 1280, 1920),
    "max_bytes": (1 * _MB, 2 * _MB, 5 * _MB, 8 * _MB, 10 * _MB, 25 * _MB),
    "bitrate": ("64k", "96k", "128k", "192k", "256k", "320k"),
    "crf": (18, 20, 23, 26, 28, 32),
    "at": (0, 0.5, 1, 2, 3, 5, 10),
    "start": (0.5, 1, 2, 3, 5, 10, 15, 30),
    "end": (3, 5, 10, 15, 20, 30, 60),
}
_UNITS = {"fps": " fps", "width": " px", "at": " s in", "start": " s", "end": " s"}
_LABELS = {"at": "frame from", "max_bytes": "max size"}
_CRF_NOTES = {18: "near lossless", 23: "balanced", 28: "small"}


def _choice_id(value: int | float | str) -> str:
    """One spelling per value, so a stored ``1.0`` matches the ``1`` offered."""
    return f"{value:g}" if isinstance(value, int | float) else str(value)


def _choice_label(field: str, value: int | float | str) -> str:
    if field == "max_bytes" and isinstance(value, int | float):
        return format_bytes(value)
    if field == "crf" and isinstance(value, int) and value in _CRF_NOTES:
        return f"{value} - {_CRF_NOTES[value]}"
    return _choice_id(value) + _UNITS.get(field, "")


def field_choices(field: str, settings: dict[str, Any]) -> dict[str, Any]:
    """A setting's ``select`` (the presets, its current value, the empty
    choice) and how it reads when the profile is not being edited."""
    current = settings.get(field)
    blank = WHOLE if field in TRIM_FIELDS else "as shipped"
    values = list(FIELD_PRESETS.get(field, ()))
    if current is not None and _choice_id(current) not in map(_choice_id, values):
        values.append(current)
        if isinstance(current, int | float):
            values.sort()
    return {
        "options": [
            {"id": _choice_id(v), "name": _choice_label(field, v)} for v in values
        ],
        "selected": None if current is None else _choice_id(current),
        "blank": blank,
        "label": _LABELS.get(field, field.replace("_", " ")),
        "shown": blank if current is None else _choice_label(field, current),
    }


_SUMMARY_WORDS = {
    "max_bytes": "under ",
    "crf": "crf ",
    "at": "frame ",
    "start": "from ",
    "end": "to ",
}
"""What a value needs before it in the line under the cards, where it
stands without its label ("under 4.8 MB", not "4.8 MB")."""


def _profile_view(row: ProfileSettings) -> dict[str, Any]:
    """One profile: its form's choices, and the same settings as one line
    ("12 fps · 960 px · under 4.8 MB"), the ones left as shipped unsaid."""
    fields = [
        (field, field_choices(field, row.settings))
        for field in profile_fields(row.kind, row.takes)
    ]
    summary = " · ".join(
        _SUMMARY_WORDS.get(field, "") + choice["shown"]
        for field, choice in fields
        if choice["selected"] is not None
    )
    return row.model_dump() | {"fields": fields, "summary": summary or "As shipped"}


PREVIEW_KINDS = (
    ("image/", "image"),
    ("audio/", "audio"),
    ("video/", "video"),
)
"""What the browser can show in place, by the result's media type."""


def _link(job: MediaJob) -> str | None:
    """The result, for "Open", a preview and a delete: the app's own
    streaming route.

    Not the bucket. A presigned URL names the S3 endpoint the containers
    talk to, and it is signed for that host (SigV4 covers it), so from a
    browser on the host the click goes nowhere — met in practice as "the
    link takes me nowhere". ``/output/<id>`` streams the object through the
    app with the row's own content type, so it works wherever the page
    does.
    """
    if not job.has_result:
        return None
    return f"{PARTIALS}/output/{job.id}"


def preview(job: MediaJob) -> dict[str, str] | None:
    """Where to fetch a preview of the result (``_link``), and which
    element shows it."""
    url = _link(job)
    if url is None or not job.content_type:
        return None
    kind = next(
        (kind for prefix, kind in PREVIEW_KINDS if job.content_type.startswith(prefix)),
        None,
    )
    return None if kind is None else {"kind": kind, "url": url}


def table_row_from(job: MediaJob) -> dict[str, Any]:
    """One job, as the table's row. Pure, so the template is testable with
    a hand-made row and no database. The strings are the service's
    (``MediaService.row``), the same the Flet modal shows."""
    row = MediaService().row(job)
    link = _link(job)
    return {
        "id": job.id,
        "profile": job.profile,
        "status": status_cell(row["status"], row["tone"]),
        "source": row["source"],
        "output": row["output"] or None,
        "preview": preview(job),
        "result": {"label": "Open", "url": link} if link else None,
        "when": row["when"],
        "running": job.status in {"queued", "running"},
        "error": job.error,
    }


async def results_body(db: Any, *, limit: int = LIST_SIZE) -> dict[str, Any]:
    """The table's context: every conversion, newest first."""
    jobs = await MediaService().recent(db, limit=limit)
    return {
        "rows": [table_row_from(job) for job in jobs],
        "partials": PARTIALS,
        "results_event": RESULTS_EVENT,
    }


def render_results(body: dict[str, Any]) -> str:
    """The table, as the stream and the sections all render it."""
    return fragment(RESULTS_TEMPLATE, **body)


def activity_charts(activity: MediaActivity) -> list[dict[str, Any]]:
    """Activity's charts in ``chart_panel``'s data shape: jobs per day,
    the profile mix, and bytes in and out (``MediaService.activity``, the
    numbers the Flet modal draws too)."""
    days, profiles = activity.days, activity.profiles
    names = [p.name for p in profiles]
    return [
        {
            "id": "media-daily",
            "title": CHARTS["daily"],
            "subtitle": f"The last {len(days)} days",
            "kind": "bar",
            "wide": True,
            "data": {
                "labels": [d.label for d in days],
                "series": [
                    {"label": "Done", "values": [d.done for d in days]},
                    {"label": "Failed", "values": [d.failed for d in days]},
                ],
                "points": sum(d.done + d.failed for d in days),
            },
        },
        {
            "id": "media-mix",
            "title": CHARTS["mix"],
            "subtitle": "Jobs per profile",
            "kind": "doughnut",
            "data": {
                "labels": names,
                "series": [{"label": "Jobs", "values": [p.jobs for p in profiles]}],
                "points": len(profiles),
            },
        },
        {
            "id": "media-bytes",
            "title": CHARTS["bytes"],
            "subtitle": "What each profile was given and made",
            "kind": "bar",
            "data": {
                "labels": names,
                "series": [
                    {"label": "In", "values": [p.source_bytes for p in profiles]},
                    {"label": "Out", "values": [p.output_bytes for p in profiles]},
                ],
                "format": "bytes",
                "points": len(profiles),
            },
        },
    ]


async def charts_body(db: Any) -> dict[str, Any]:
    """Activity's figures and charts, as the section renders them and the
    stream re-sends them."""
    service = MediaService()
    stats = await service.stats(db)
    return {
        "figures": [
            {"label": f.label, "value": f.value, "negative": f.tone == "error"}
            for f in service.figures(stats)
        ],
        "charts": activity_charts(await service.activity(db)),
    }


def card_from(job: MediaJob) -> dict[str, Any]:
    """One result in the gallery: what it is, what to do with it, and,
    when it failed, why in plain words (``MediaService.row``)."""
    row = MediaService().row(job)
    state = job.status if job.status in {"done", "failed"} else "working"
    shown = preview(job)
    link = _link(job)
    return {
        "title": row["title"],
        "state": state,
        "meta": " · ".join(part for part in (row["output"], row["when"]) if part),
        "reason": row["reason"],
        "preview": shown,
        "view": f"{PARTIALS}/view/{job.id}" if shown else None,
        "icon": kind_icon(row["kind"]),
        "download": link,
        "delete": f"{PARTIALS}/confirm-delete/{job.id}" if link else None,
        "filename": row["filename"],
        "markdown": row["markdown"],
    }


async def recent_body(db: Any) -> dict[str, Any]:
    """The gallery: the newest results, less the ones deleted, and how many
    there are, failures named, since the gallery shows them too."""
    service = MediaService()
    stats = await service.stats(db)
    jobs = await service.recent(db, limit=RECENT, kept_only=True)
    counts = f"{stats.kept:,} made" + (
        f", {stats.failed:,} failed" if stats.failed else ""
    )
    return {
        "cards": [card_from(job) for job in jobs],
        "made": f"{counts} · {format_bytes(stats.output_bytes)} stored",
        "activity_url": ACTIVITY,
    }


async def overview_body(db: Any) -> dict[str, Any]:
    """The Overview: a drop zone, what to make, an estimate, and what was
    made. A choice is a profile named for its result; "Adjust settings"
    opens that profile's numbers, each picked from ``FIELD_PRESETS``."""
    service = MediaService()
    views = service.profiles()
    return await recent_body(db) | {
        # The page is Media, not its dashboard's "Overview / OK": health is
        # the dot beside the title in the sub-menu.
        "page_titled": True,
        "section_subtitle": None,
        "choices": [
            view.model_dump() | {"icon": kind_icon(view.kind)} for view in views
        ],
        # ``MediaJob.end``: the first seconds, then the last, offered for a
        # choice that trims.
        "trimming": [view.name for view in views if view.kind in TRIMS],
        "whole": WHOLE,
        "trims": [
            {"id": _choice_id(sign * v), "name": f"{word} {_choice_label('end', v)}"}
            for sign, word in ((1, "First"), (-1, "Last"))
            for v in FIELD_PRESETS["end"]
        ],
        "settings": [_profile_view(row) for row in await service.profile_settings(db)],
        "estimate_url": f"{PARTIALS}/estimate",
        "recent_event": RECENT_EVENT,
    }


async def estimate_body(
    db: Any,
    *,
    profile: str,
    size: int,
    duration: float | None,
    end: float | None,
    name: str,
) -> dict[str, str]:
    """The chosen file in a line, and about how big this choice makes it:
    the browser sends what it read off the file, the service guesses."""
    if not size:
        return {"file": "", "estimate": ""}
    guess = await MediaService().estimate(db, profile, size, duration=duration, end=end)
    facts = [name, format_bytes(size), format_clock(duration) if duration else ""]
    return {
        "file": ", ".join(fact for fact in facts if fact),
        "estimate": (
            f"Result: about {format_bytes(guess)}"
            if guess is not None
            else "No estimate until this one has made something"
        ),
    }


def events_url(section: str) -> str:
    """The stream a section connects to."""
    return with_query(EVENTS, section=section)


def events(section: str, max_frames: int | None = None) -> AsyncIterator[str]:
    """A section over SSE: the Overview's gallery as one event; Activity's
    charts and table as two (a table whose "when" moves each tick must not
    redraw the charts)."""

    async def render() -> dict[str, str]:
        async with get_async_session() as db:
            if section == "overview":
                return {
                    RECENT_EVENT: fragment(RECENT_TEMPLATE, **await recent_body(db))
                }
            return {
                CHARTS_EVENT: fragment(CHARTS_TEMPLATE, **await charts_body(db)),
                RESULTS_EVENT: render_results(await results_body(db)),
            }

    return fragments_events(render, EVENTS_INTERVAL_SECONDS, max_frames)


async def _overview(req: SectionRequest) -> dict[str, Any]:
    return await overview_body(req.db) | {"events": events_url("overview")}


async def _activity(req: SectionRequest) -> dict[str, Any]:
    return (
        await charts_body(req.db)
        | await results_body(req.db)
        | {
            "events": events_url("activity"),
            "charts_event": CHARTS_EVENT,
        }
    )


BUILDERS: dict[str, Callable[[SectionRequest], Awaitable[dict[str, Any]]]] = {
    "overview": _overview,
    "activity": _activity,
}


async def section_context(
    section: str, media: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    return {"partials": PARTIALS} | await BUILDERS[section](req)
