"""``media convert``: the page's "First/Last N s" from the command line,
sent as the job's signed ``end`` (5 the first 5 s, -5 the last)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.cli import media
from tests._cli import invoke


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """What ``convert`` hands the service; nothing stored, nothing queued."""
    calls: list[dict[str, Any]] = []

    class Service:
        async def submit(self, session: object, data: bytes, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return SimpleNamespace(id=1)

    async def queued(media_job_id: int) -> None:
        return None

    monkeypatch.setattr(media, "MediaService", Service)
    monkeypatch.setattr(media, "start_conversion", queued)
    return calls


@pytest.mark.parametrize(
    ("flags", "end"), [([], None), (["--first", "5"], 5.0), (["--last", "20"], -20.0)]
)
def test_convert_sends_the_trim_signed(
    tmp_path: Path,
    submitted: list[dict[str, Any]],
    flags: list[str],
    end: float | None,
) -> None:
    clip = tmp_path / "clip.webp"
    clip.write_bytes(b"x")
    result = invoke(["media", "convert", str(clip), "-p", "x-video", *flags])
    assert result.exit_code == 0, result.output
    assert submitted[0]["end"] == end


def test_convert_takes_one_trim(
    tmp_path: Path, submitted: list[dict[str, Any]]
) -> None:
    clip = tmp_path / "clip.webp"
    clip.write_bytes(b"x")
    result = invoke(
        ["media", "convert", str(clip), "-p", "x-video", "--first", "5", "--last", "5"]
    )
    assert result.exit_code != 0 and submitted == []


def test_a_negative_trim_is_refused(
    tmp_path: Path, submitted: list[dict[str, Any]]
) -> None:
    """``--last`` says which end; a negative ``--first`` would say it twice."""
    clip = tmp_path / "clip.webp"
    clip.write_bytes(b"x")
    result = invoke(["media", "convert", str(clip), "-p", "x-video", "--first", "-3"])
    assert result.exit_code != 0 and submitted == []
