"""Shapes the media service hands out: profiles, stats, and a job's state.

``FIGURES`` (frozen, ``extra="forbid"``) on each, so a field added in one
place cannot arrive as an unexpected key in another.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.core.figures import FIGURES


class ProfileView(BaseModel):
    """One conversion profile, as the page and the CLI list it."""

    model_config = FIGURES

    name: str
    description: str
    kind: str
    title: str
    takes: tuple[str, ...]
    """The files it is offered for: ``video``, ``image``, ``audio``."""


class MediaStats(BaseModel):
    """What the service has done, as figures - never rows."""

    model_config = FIGURES

    jobs: int
    done: int
    failed: int
    kept: int = 0
    """Finished results still stored: done, less the ones deleted."""
    source_bytes: int
    output_bytes: int
    last_finished_at: str | None = None


class Figure(BaseModel):
    """One headline number as every frontend shows it; ``tone`` is ``error``
    when it is bad news, ``ok`` when it is good."""

    model_config = FIGURES

    label: str
    value: str
    tone: str = ""


class DayCount(BaseModel):
    """One day's jobs, labelled as every chart of them reads it."""

    model_config = FIGURES

    label: str
    done: int
    failed: int


class ProfileTotal(BaseModel):
    """One profile's jobs and what went in and came out of them."""

    model_config = FIGURES

    name: str
    jobs: int
    source_bytes: int
    output_bytes: int


class MediaActivity(BaseModel):
    """What the charts draw: jobs per day, oldest first, and per profile,
    most used first."""

    model_config = FIGURES

    days: list[DayCount]
    profiles: list[ProfileTotal]


class ProfileSettings(ProfileView):
    """One profile as this project has it: shipped, then its saved edits,
    for the page's settings form."""

    settings: dict[str, Any]
    """The numbers it runs with, by ``FIELDS`` name."""


class ConversionResult(BaseModel):
    """A job's state as figures, never its row: what the agent's tool
    queued, and how a run came out for the CLI and the worker."""

    model_config = FIGURES

    id: int | None
    status: str
    profile: str
    output_key: str | None = None
    output_bytes: int | None = None
    error: str | None = None
