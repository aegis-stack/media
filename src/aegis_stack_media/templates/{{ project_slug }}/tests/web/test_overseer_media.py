"""The Overseer Media page: its sections, its links and its one row.

The page is a plugin page, so this test is about the wiring the framework
reads (``SECTIONS`` and ``section_context``) and the row template the poll
re-renders - not about the HTTP surface, which ``tests/web`` covers for the
in-tree pages.
"""

from __future__ import annotations

from datetime import datetime

from app.components.web_frontend import overseer_media
from app.services.media.models import MediaJob


def test_the_page_has_the_three_sections_a_person_uses() -> None:
    labels = {
        key: label
        for _, group in overseer_media.SECTIONS
        for key, label in group.items()
    }
    assert list(labels) == ["overview", "convert", "results"]
    assert labels["convert"] == "Convert"


def test_results_url_carries_the_job_when_there_is_one() -> None:
    assert overseer_media.results_url() == "/overseer/services/media/results"
    assert overseer_media.results_url(7).endswith("results?job=7")


def test_a_running_job_renders_as_a_row_that_polls_itself() -> None:
    job = MediaJob(
        id=4,
        profile="readme-gif",
        source_key="sha256/aa/bb/" + "0" * 64,
        source_bytes=1024,
        status="running",
        created_at=datetime(2026, 1, 1),
    )
    view = overseer_media.job_view_from(job)
    html = overseer_media.render_job(view)
    assert 'id="media-job-4"' in html
    assert "every 2s" in html
    assert "readme-gif" in html


def test_a_finished_job_renders_without_polling() -> None:
    job = MediaJob(
        id=5,
        profile="png",
        source_key="sha256/aa/bb/" + "0" * 64,
        source_bytes=1024,
        output_bytes=2048,
        status="done",
        created_at=datetime(2026, 1, 1),
    )
    html = overseer_media.render_job(overseer_media.job_view_from(job))
    assert "every 2s" not in html
    assert "2.0 KB" in html or "2 KB" in html
