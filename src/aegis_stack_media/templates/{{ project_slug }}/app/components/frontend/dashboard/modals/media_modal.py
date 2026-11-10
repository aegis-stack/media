"""Media service detail modal: what the conversions did, and what they cost.

The health card answers "is it alive"; this answers "what has it done",
in the Overseer Media page's terms: an Overview of figures and charts,
the Results, and the Profiles. The numbers and a job's strings are the
service's (``MediaService.activity`` and ``MediaService.row``), so the two
frontends cannot disagree. The Overseer page is where you upload and
convert; this modal is the read-only view from the dashboard, read once
when it opens.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls import SectionCard
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.cards.card_utils import get_status_detail
from app.components.frontend.dashboard.modals.base_detail_popup import BaseDetailPopup
from app.components.frontend.dashboard.modals.modal_sections import (
    BarChartCard,
    BarSeries,
    ChartColors,
    EmptyStatePlaceholder,
    MetricCard,
    PieChartCard,
)
from app.components.frontend.dashboard.modals.table_tab import TableTab
from app.components.frontend.theme import AegisTheme as Theme
from app.core.db import get_async_session
from app.core.formatting import format_bytes
from app.services.media import SERVICE_NAME
from app.services.media.schemas import MediaActivity, MediaStats, ProfileView
from app.services.media.service import CHARTS, MediaJob, MediaService
from app.services.system.models import ComponentStatus
from app.services.system.ui import (
    get_component_subtitle,
    get_component_title,
    registry_key,
)

RECENT_LIMIT = 25
"""Rows the Results tab shows. The Overseer page is the place for the rest."""

_TONE_COLORS = {
    "ok": Theme.Colors.SUCCESS,
    "error": Theme.Colors.ERROR,
    "warn": Theme.Colors.WARNING,
}


def _chart(title: str, chart: ft.Control) -> ft.Control:
    return SectionCard(title, chart, body_padding=Theme.Spacing.MD)


def overview_tab(stats: MediaStats, activity: MediaActivity) -> ft.Control:
    """Figures across the top, then jobs per day, the profile mix, and
    what each profile was given and made."""
    days, profiles = activity.days, activity.profiles
    figures = ft.Row(
        [
            MetricCard(f.label, f.value, _TONE_COLORS.get(f.tone, Theme.Colors.INFO))
            for f in MediaService().figures(stats)
        ],
        alignment=ft.MainAxisAlignment.SPACE_AROUND,
    )
    daily = BarChartCard(
        x_labels=[d.label for d in days],
        series=[
            BarSeries("Done", ChartColors.TEAL, [float(d.done) for d in days]),
            BarSeries("Failed", ChartColors.ERROR, [float(d.failed) for d in days]),
        ],
    )
    sizes: ft.Control = (
        BarChartCard(
            x_labels=[p.name for p in profiles],
            series=[
                BarSeries(
                    "In", ChartColors.TEAL, [float(p.source_bytes) for p in profiles]
                ),
                BarSeries(
                    "Out", ChartColors.BLUE, [float(p.output_bytes) for p in profiles]
                ),
            ],
            value_format=lambda v: format_bytes(int(v)),
        )
        if profiles
        else EmptyStatePlaceholder(message="Nothing converted yet")
    )
    mix = PieChartCard(
        CHARTS["mix"],
        [{"value": p.jobs, "label": f"{p.name} ({p.jobs:,})"} for p in profiles],
    )
    return ft.Container(
        ft.Column(
            [
                figures,
                _chart(CHARTS["daily"], daily),
                ft.Row(
                    [
                        ft.Container(mix, expand=1),
                        ft.Container(_chart(CHARTS["bytes"], sizes), expand=2),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=Theme.Spacing.MD,
                ),
            ],
            spacing=Theme.Spacing.LG,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=ft.padding.all(Theme.Spacing.MD),
        expand=True,
    )


def _detail(row: dict[str, str]) -> ft.Control:
    """What a row opens to: a failure's output, whole."""
    return ft.Text(
        row["error"] or "Finished without errors.",
        size=12,
        font_family="monospace",
        selectable=True,
    )


def results_tab(jobs: list[MediaJob]) -> ft.Control:
    """The newest conversions; a row opens to what went wrong, if anything."""
    service = MediaService()
    return TableTab(
        [service.row(job) for job in jobs],
        [
            ("Id", "id", 50),
            ("Profile", "profile", None),
            ("Status", "status", 90),
            ("In", "source", 90),
            ("Out", "output", 90),
            ("When", "when", 130),
        ],
        empty="Nothing converted yet. Start one on the Overseer's Media page.",
        color_of=lambda row, key: _TONE_COLORS.get(row["tone"])
        if key == "status"
        else None,
        detail=_detail,
    )


def profiles_tab(profiles: list[ProfileView]) -> ft.Control:
    """What this project can make, named for the result."""
    return TableTab(
        [p.model_dump() for p in profiles],
        [
            ("Profile", "name", 140),
            ("Kind", "kind", 90),
            ("What it makes", "description", None),
        ],
        empty="No profiles: add one to app/services/media/adapters/profiles.yml",
    )


def media_tabs(
    stats: MediaStats,
    activity: MediaActivity,
    jobs: list[MediaJob],
    profiles: list[ProfileView],
) -> PulseTabs:
    return PulseTabs(
        tabs=[
            ft.Tab(text="Overview", content=overview_tab(stats, activity)),
            ft.Tab(text="Results", content=results_tab(jobs)),
            ft.Tab(text="Profiles", content=profiles_tab(profiles)),
        ],
    )


class MediaPanel(ft.Container):
    """The tabs, built once the service has answered."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(expand=True)
        self.page = page
        self.content = ft.Text("Loading…", size=13)
        page.run_task(self._load)

    async def _load(self) -> None:
        service = MediaService()
        async with get_async_session() as db:
            stats = await service.stats(db)
            activity = await service.activity(db)
            jobs = await service.recent(db, limit=RECENT_LIMIT)
        self.content = media_tabs(stats, activity, jobs, service.profiles())
        self.page.update()


class MediaDetailDialog(BaseDetailPopup):
    """Detail modal for the media service."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title(registry_key("services", SERVICE_NAME)),
            subtitle_text=get_component_subtitle(
                registry_key("services", SERVICE_NAME), component_data.metadata
            ),
            sections=[MediaPanel(page)],
            scrollable=False,
            width=1000,
            height=700,
            status_detail=get_status_detail(component_data),
        )
