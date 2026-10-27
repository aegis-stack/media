"""Shapes the media service hands out: profiles, stats, and a job's state.

Frozen and ``extra="forbid"`` where an agent or a template reads them, so
a field added in one place cannot arrive as an unexpected key in another.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProfileView(BaseModel):
    """One conversion profile, as the page and the CLI list it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    kind: str


class MediaStats(BaseModel):
    """What the service has done, as figures - never rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    jobs: int
    done: int
    failed: int
    source_bytes: int
    output_bytes: int
    last_finished_at: str | None = None
