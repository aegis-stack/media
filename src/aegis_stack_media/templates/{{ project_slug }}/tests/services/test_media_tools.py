"""The agent's door: one tool, a job back, a refusal it can act on.

An agent composes a conversion it cannot see the outcome of, so the tool
must answer with figures (an id, a status, a profile) and hand the work to
the queue: holding the request open for ffmpeg is how a chat turn times
out. A profile the stack does not have is refused with the ones it does —
guessing is exactly what a model does when a refusal is vague.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.tools import get_tool, native_write_tool_names
from app.services.media import jobs, tools


def test_the_tool_is_granted_as_a_write() -> None:
    registered = get_tool("media")

    assert registered is not None
    assert registered.effect == "writes"
    assert "media" in native_write_tool_names()


@pytest.mark.asyncio
async def test_an_unknown_profile_is_refused_with_the_known_ones() -> None:
    with pytest.raises(ValueError) as refused:
        await tools.media(source="sha256/aa/aa", profile="teapot")

    said = str(refused.value)
    assert "teapot" in said
    assert "gif" in said  # the stack's profiles, listed for the caller


@pytest.mark.asyncio
async def test_a_known_profile_queues_and_returns_figures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[int] = []

    async def fake_start(media_job_id: int) -> str:
        sent.append(media_job_id)
        return "handle"

    monkeypatch.setattr(jobs, "start_conversion", fake_start)

    result: dict[str, Any] = await tools.media(
        source="sha256/aa/aa", profile="web-gif"
    )

    assert set(result) >= {"id", "status", "profile"}
    assert result["profile"] == "web-gif"
    assert result["status"] == "queued"
    assert sent == [result["id"]]
