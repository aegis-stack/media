"""The Overseer Media page: one page to make things, one for the system.

The page is a plugin page, so this test is about the wiring the framework
reads (``SECTIONS`` and ``section_context``) and the fragments the streams
re-render - not about the HTTP surface, which ``tests/web`` covers for the
in-tree pages.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import contextlib
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_media
from app.services.media.models import MediaJob
from tests.web.overseer import sent_events, sign_in, status_with


def _body(jobs: list[MediaJob]) -> dict:
    """The table's context without a database: rows built from real jobs."""
    return {
        "rows": [overseer_media.table_row_from(job) for job in jobs],
        "partials": overseer_media.PARTIALS,
        "results_event": overseer_media.RESULTS_EVENT,
    }


def test_the_page_is_one_place_to_make_and_one_for_the_system() -> None:
    """Convert, Profiles and Results are the Overview now; the charts and
    the jobs table are system information, under Activity."""
    labels = {
        key: label
        for _, group in overseer_media.SECTIONS
        for key, label in group.items()
    }
    assert list(labels) == ["overview", "activity"]
    assert overseer_media.PAGE == "/overseer/services/media"


def test_a_running_job_is_marked_watching() -> None:
    job = MediaJob(
        id=4,
        profile="readme-gif",
        source_key="sha256/aa/bb/" + "0" * 64,
        source_bytes=1024,
        status="running",
        created_at=datetime(2026, 1, 1),
    )
    html = overseer_media.render_results(_body([job]))
    assert "readme-gif" in html
    assert "watching" in html


def test_a_finished_job_shows_its_output_size() -> None:
    job = MediaJob(
        id=5,
        profile="png",
        source_key="sha256/aa/bb/" + "0" * 64,
        source_bytes=1024,
        output_bytes=2048,
        status="done",
        created_at=datetime(2026, 1, 1),
    )
    html = overseer_media.render_results(_body([job]))
    assert "2.0 KB" in html or "2 KB" in html


def test_a_finished_result_points_at_the_apps_own_preview() -> None:
    """The picture comes from the app, not the bucket.

    A presigned link names the S3 endpoint the containers use
    (``http://seaweedfs:8333``), which the browser cannot reach, so the row
    previews through ``/partials/overseer/media/output/<id>``.
    """
    job = MediaJob(
        id=5,
        profile="readme-gif",
        source_key="sha256/aa/bb/" + "0" * 64,
        output_key="sha256/cc/dd/" + "1" * 64,
        source_bytes=1024,
        output_bytes=4096,
        content_type="image/gif",
        status="done",
        created_at=datetime(2026, 1, 1),
    )

    view = overseer_media.preview(job)

    assert view == {
        "kind": "image",
        "url": "/partials/overseer/media/output/5",
    }
    assert "h-12" in overseer_media.render_results(_body([job]))


def test_a_result_a_browser_cannot_show_gets_no_preview() -> None:
    """A zip is a link, not a broken image."""
    job = MediaJob(
        id=6,
        profile="png",
        source_key="sha256/aa/bb/" + "0" * 64,
        output_key="sha256/cc/dd/" + "1" * 64,
        source_bytes=1024,
        output_bytes=4096,
        content_type="application/zip",
        status="done",
        created_at=datetime(2026, 1, 1),
    )

    assert overseer_media.preview(job) is None


def test_a_job_still_running_has_nothing_to_show_yet() -> None:
    job = MediaJob(
        id=7,
        profile="web-gif",
        source_key="sha256/aa/bb/" + "0" * 64,
        source_bytes=1024,
        status="running",
        created_at=datetime(2026, 1, 1),
    )

    assert overseer_media.preview(job) is None


def test_a_failed_row_keeps_the_error_out_of_the_row() -> None:
    """The error is the row's detail, not a red line under every failure.

    Three failed conversions turned the table into a wall of ffmpeg output.
    ``data_table(detail=...)`` is the framework's expandable row (the same
    one the scheduler's history uses): the row keeps its cells, and the
    command's whole output is one click away in a ``pre`` block.
    """
    error = (
        "ffmpeg exited 183: moov atom not found\nError opening input file /tmp/x.mp4"
    )
    job = MediaJob(
        id=3,
        profile="web-gif",
        source_key="sha256/aa/bb/" + "0" * 64,
        source_bytes=1,
        status="failed",
        error=error,
        created_at=datetime(2026, 1, 1),
    )
    html = overseer_media.render_results(_body([job]))
    row, _, detail = html.partition("data-detail")
    assert "moov atom not found" not in row, "the row is a row, not a log"
    assert 'class="code-block"' in detail
    assert "moov atom not found" in detail


def _render(name: str, **context: object) -> str:
    from app.components.web_frontend.rendering import templates

    return templates.env.get_template(f"pages/overseer/media/{name}").render(context)


def _job(**fields: object) -> MediaJob:
    base: dict[str, object] = {
        "id": 8,
        "profile": "readme-gif",
        "source_key": "sha256/aa/bb/" + "0" * 64,
        "source_name": "demo.mov",
        "source_bytes": 4096,
        "status": "done",
        "created_at": datetime(2026, 1, 1),
    }
    return MediaJob(**(base | fields))


@pytest.mark.asyncio
async def test_the_overview_offers_results_not_profile_names(
    async_db_session: AsyncSession,
) -> None:
    """ "GIF for a README" with its format on a second line, picked by a
    radio; one filled submit; the chosen one's settings read as a line
    under the cards, opened in place by "Change"; the file shown once
    chosen."""
    import re

    body = await overseer_media.overview_body(async_db_session)
    html = _render("_overview.html", **body, events="/e", partials="/p")
    make, _, rest = html.partition("</form>")
    assert "GIF for a README" in make and "Sharp, under 5 MB" in make
    assert re.findall(r'type="radio" name="profile" value="([\w-]+)"', make)[:2] == [
        "readme-gif",
        "web-gif",
    ]
    assert ">Whole clip</option>" in make and ">First 5 s</option>" in make
    assert re.search(r'<option value="-20"\s*>Last 20 s</option>', make)
    # Offered only for a choice that trims: a screenshot takes one frame.
    assert "mp4" in body["trimming"] and "png" not in body["trimming"]
    assert "trimming.includes(pick)" in make
    assert 'data-takes="video"' in make and 'data-takes="image"' in make
    assert body["page_titled"] and body["section_subtitle"] is None
    assert '<img :src="preview"' in make and '<video :src="preview"' in make
    # A GIF moves: offered what a video is, and shown as the picture it is.
    assert "file.type === 'image/gif' || animated" in make
    assert "'VP8X'" in make, "an animated WebP moves too"
    assert overseer_media.profile_fields("video", ("video",)) == (
        "crf",
        "width",
        "start",
        "end",
    )

    buttons = re.findall(r"<button[^>]*>", make)
    assert all(b.count(" type=") == 1 for b in buttons), buttons
    own = [b for b in buttons if 'type="submit"' in b and " form=" not in b]
    assert len(own) == 1 and "bg-aegis-teal " in own[0], "one filled Make it"

    assert "12 fps · 960 px · under 4.8 MB" in make and ">Change</button>" in make
    assert "Adjust settings" not in html
    # The settings sit under the cards but post through their own form,
    # so the make form never sends a profile's ``end`` as the job's trim.
    assert re.findall(
        r'<select name="(\w+)" form="media-profile-readme-gif"', make
    ) == [
        "fps",
        "width",
        "max_bytes",
        "start",
        "end",
    ]
    assert '<form id="media-profile-readme-gif"' in rest


def test_a_failure_says_why_and_offers_another_go() -> None:
    """ "The file was empty", not a red ``failed`` beside ``1 B``."""
    card = overseer_media.card_from(
        _job(profile="web-gif", status="failed", source_bytes=1, error="x")
    )
    html = _render("_recent.html", cards=[card], made="", activity_url="/a")
    assert "GIF for chat or a post" in html
    assert "The file was empty (1 B)" in html
    assert "Try another file" in html and ">failed<" not in html


def test_a_result_is_downloaded_or_copied_into_a_readme() -> None:
    card = overseer_media.card_from(
        _job(
            output_key="sha256/cc/dd/" + "1" * 64,
            output_bytes=2048,
            content_type="image/gif",
        )
    )
    html = _render("_recent.html", cards=[card], made="", activity_url="/a")
    assert 'download="demo-readme-gif.gif"' in html
    assert 'data-copy="![demo](demo-readme-gif.gif)"' in html
    assert '<img src="/partials/overseer/media/output/8"' in html


@pytest.mark.asyncio
async def test_the_count_names_the_failures_the_gallery_shows(
    async_db_session: AsyncSession,
) -> None:
    """ "4 made" above a grid with two failures in it reads as "which 4?";
    a result deleted is not in the grid, so not in the count either."""
    kept = {"output_bytes": 1024, "output_key": "sha256/cc/dd/" + "1" * 64}
    for fields in (kept, kept, {"output_bytes": 9}, {"status": "failed"}):
        async_db_session.add(_job(id=None, **fields))
    await async_db_session.flush()
    body = await overseer_media.recent_body(async_db_session)
    assert body["made"] == "2 made, 1 failed · 2.0 KB stored"
    assert len(body["cards"]) == 3


@pytest.mark.asyncio
async def test_the_estimate_waits_for_a_file_and_for_history(
    async_db_session: AsyncSession,
) -> None:
    async def ask(size: int, end: float | None = None) -> dict[str, str]:
        return await overseer_media.estimate_body(
            async_db_session,
            profile="mp4",
            size=size,
            duration=40.0,
            end=end,
            name="demo.mov",
        )

    assert await ask(0) == {"file": "", "estimate": ""}
    assert (await ask(1000))["estimate"].startswith("No estimate")
    async_db_session.add(_job(profile="mp4", source_bytes=1000, output_bytes=500))
    await async_db_session.flush()
    answer = await ask(10_000, end=10.0)
    assert answer["file"] == "demo.mov, 9.8 KB, 00:40"
    assert answer["estimate"] == "Result: about 1.2 KB"


@pytest.mark.asyncio
async def test_each_section_streams_rather_than_polls(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Overview's gallery is one event; Activity's charts and table are
    two, so a table whose "when" moves each tick does not redraw the
    charts."""

    @contextlib.asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield async_db_session

    monkeypatch.setattr(overseer_media, "get_async_session", session)

    async def names(section: str) -> list[str]:
        frames = await sent_events(overseer_media.events(section, max_frames=1))
        return sorted(frame.split("\n", 1)[0] for frame in frames)

    assert await names("overview") == [f"event: {overseer_media.RECENT_EVENT}"]
    assert await names("activity") == [
        f"event: {overseer_media.CHARTS_EVENT}",
        f"event: {overseer_media.RESULTS_EVENT}",
    ]


@pytest.mark.asyncio
async def test_activity_charts_the_jobs_over_one_stream(
    async_db_session: AsyncSession,
) -> None:
    import re

    from markupsafe import escape

    async_db_session.add(_job(profile="png", output_bytes=40))
    await async_db_session.flush()
    body = (
        await overseer_media.charts_body(async_db_session)
        | await overseer_media.results_body(async_db_session)
        | {
            "events": overseer_media.events_url("activity"),
            "charts_event": overseer_media.CHARTS_EVENT,
        }
    )
    html = _render("_activity.html", **body)
    for chart in ("media-daily", "media-mix", "media-bytes"):
        assert f'data-chart-data="chart-{chart}-data"' in html, chart
    assert f'sse-connect="{escape(body["events"])}"' in html
    assert not re.search(r"hx-trigger|every \d", html), "a section still polls"


def test_the_whole_clip_is_an_empty_end_not_a_422(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Whole clip" is the select's blank option, so the form posts
    ``end=""``: a missing number, not a malformed one."""
    sign_in(app, monkeypatch, status_with())
    with TestClient(app) as client:
        response = client.post(
            f"{overseer_media.PARTIALS}/convert",
            data={"profile": "no-such-profile", "end": ""},
            files={"file": ("shot.png", b"png", "image/png")},
        )
    assert response.status_code == 200, response.text
    assert "no-such-profile" in response.headers.get("HX-Trigger", "")


def test_a_still_is_not_offered_settings_that_need_a_length() -> None:
    """A picture has one frame: no "at" to seek to, no start or end."""
    assert overseer_media.profile_fields("thumbnail", ("image",)) == ("width",)


def test_a_frame_is_picked_by_when_and_one_frame_has_no_trim() -> None:
    """ "Frame from 1 s in", not "at 1"; a single frame has nothing to trim."""
    assert overseer_media.profile_fields("thumbnail", ("video",)) == ("at", "width")
    assert overseer_media.profile_fields("image", ("video",)) == ("at", "width")
    assert overseer_media.profile_fields("gif", ("video",))[-2:] == ("start", "end")
    choice = overseer_media.field_choices("at", {"at": 1.0})
    assert (choice["label"], choice["shown"]) == ("frame from", "1 s in")


def test_a_result_opens_larger_in_the_one_dialog() -> None:
    """A preview is a button: the result, full size, in ``#dialog-body``,
    with the same Download and Copy markdown as its card."""
    card = overseer_media.card_from(
        _job(
            output_key="sha256/cc/dd/" + "1" * 64,
            output_bytes=2048,
            content_type="image/gif",
        )
    )
    assert card["view"] == "/partials/overseer/media/view/8"
    gallery = _render("_recent.html", cards=[card], made="", activity_url="/a")
    assert (
        'hx-get="/partials/overseer/media/view/8" hx-target="#dialog-body"' in gallery
    )
    view = _render("_view.html", c=card)
    assert (
        "data-snug" in view and '<img src="/partials/overseer/media/output/8"' in view
    )
    assert 'download="demo-readme-gif.gif"' in view and "Copy markdown" in view


def test_a_result_still_being_made_does_not_open() -> None:
    assert overseer_media.card_from(_job(status="running"))["view"] is None


def test_viewing_a_result_that_is_not_there_is_404(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with())
    with TestClient(app) as client:
        response = client.get(f"{overseer_media.PARTIALS}/view/999999")
    assert response.status_code == 404


def test_a_finished_result_can_be_deleted_and_asks_first() -> None:
    """Delete sits with Download and Copy markdown, on the card and opened
    larger; it opens the confirmation in the dialog, not a request."""
    card = overseer_media.card_from(
        _job(
            output_key="sha256/cc/dd/" + "1" * 64,
            output_bytes=9,
            content_type="image/png",
        )
    )
    assert card["delete"] == "/partials/overseer/media/confirm-delete/8"
    for html in (
        _render("_recent.html", cards=[card], made="", activity_url="/a"),
        _render("_view.html", c=card),
    ):
        assert (
            'hx-get="/partials/overseer/media/confirm-delete/8" hx-target="#dialog-body"'
            in html
        )
    assert overseer_media.card_from(_job(status="failed", error="x"))["delete"] is None


def test_deleting_a_result_that_is_not_there_is_404(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with())
    with TestClient(app) as client:
        assert (
            client.delete(f"{overseer_media.PARTIALS}/output/999999").status_code == 404
        )
        assert (
            client.get(f"{overseer_media.PARTIALS}/confirm-delete/999999").status_code
            == 404
        )


def test_every_icon_the_page_draws_is_in_the_stacks_sprite() -> None:
    """The symbols are the stack's (``icons.html``): a name it lacks draws
    nothing, on a core older than the page."""
    import re

    from app.components.web_frontend.rendering import templates

    loader = templates.env.loader
    assert loader is not None

    def source(name: str) -> str:
        return loader.get_source(templates.env, name)[0]

    pages = "".join(
        source(name)
        for name in loader.list_templates()
        if name.startswith("pages/overseer/media/")
    )
    drawn = set(re.findall(r'icon\("([a-z0-9-]+)"', pages))
    drawn |= set(overseer_media.KIND_ICONS.values())
    sprite = source("components/macros/icons.html")
    assert {name for name in drawn if f'id="i-{name}"' not in sprite} == set()
