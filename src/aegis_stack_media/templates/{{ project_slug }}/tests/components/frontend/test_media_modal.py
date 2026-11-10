"""The Flet media modal: the same figures, charts and rows as the Overseer's
Media page (``MediaService.activity`` and ``MediaService.row``)."""

from datetime import datetime

import flet as ft

from app.components.frontend.dashboard.modals import media_modal
from app.services.media.models import MediaJob
from app.services.media.schemas import (
    DayCount,
    MediaActivity,
    MediaStats,
    ProfileTotal,
    ProfileView,
)
from tests.components.frontend._tree import texts, walk

STATS = MediaStats(jobs=3, done=2, failed=1, source_bytes=300, output_bytes=50)
ACTIVITY = MediaActivity(
    days=[
        DayCount(label="Oct 29", done=1, failed=0),
        DayCount(label="Oct 30", done=1, failed=1),
    ],
    profiles=[ProfileTotal(name="png", jobs=2, source_bytes=200, output_bytes=40)],
)
JOB = MediaJob(
    id=7,
    profile="readme-gif",
    source_key="sha256/aa/bb/" + "0" * 64,
    source_bytes=1024,
    status="failed",
    error="ffmpeg exited 1",
    created_at=datetime(2026, 1, 1),
)


def test_it_has_a_tab_for_each_thing_the_page_has() -> None:
    tabs = media_modal.media_tabs(STATS, ACTIVITY, [JOB], [])
    assert [tab.text for tab in tabs.tabs] == ["Overview", "Results", "Profiles"]


def test_the_overview_leads_with_figures_and_charts_its_days() -> None:
    tab = media_modal.overview_tab(STATS, ACTIVITY)
    shown = texts(tab)
    for figure in ("Jobs", "Done", "Failed", "Stored"):
        assert figure in shown
    assert "Jobs per day" in shown and "Profile mix" in shown and "In and out" in shown
    daily = next(n for n in walk(tab) if isinstance(n, ft.BarChart))
    assert [axis.label.value for axis in daily.bottom_axis.labels] == [
        "Oct 29",
        "Oct 30",
    ]


def test_results_show_each_job_and_a_failure_opens_to_its_error() -> None:
    tab = media_modal.results_tab([JOB])
    shown = " ".join(texts(tab))
    assert "readme-gif" in shown and "failed" in shown and "1.0 KB" in shown
    assert "ffmpeg exited 1" not in shown, "the error belongs in the row's detail"


def test_nothing_converted_says_so() -> None:
    assert any("Nothing converted" in t for t in texts(media_modal.results_tab([])))


def test_profiles_list_what_the_project_can_make() -> None:
    profiles = [
        ProfileView(
            name="mp3",
            title="MP3",
            description="Audio for the web",
            kind="audio",
            takes=("video", "audio"),
        )
    ]
    shown = texts(media_modal.profiles_tab(profiles))
    assert "mp3" in shown and "Audio for the web" in shown
