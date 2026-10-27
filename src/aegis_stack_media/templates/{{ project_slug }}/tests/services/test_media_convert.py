"""A profile into argv, and one real conversion through the packaged ffmpeg.

The plan is pure, so most of this needs no process. The last test runs
ffmpeg for real on a one-pixel PNG: it is the only way to know the plugin's
static binary, the filter strings and the output suffix agree with each
other, and it takes a fraction of a second.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

import pytest

from app.services.media.adapters import ffmpeg, profiles
from app.services.media.domains import convert

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR42mP4z8CAFTEMLQkA"
    "KP8/wc53yE8AAAAASUVORK5CYII="
)


def test_a_gif_plan_is_the_palette_pass_at_the_profiles_numbers() -> None:
    made = convert.plan(profiles.Profile(kind="gif", fps=12, width=960))
    joined = " ".join(made.options)
    assert "fps=12" in joined
    assert "scale=960:-1" in joined
    assert "palettegen" in joined and "paletteuse" in joined
    assert made.suffix == ".gif"
    assert made.content_type == "image/gif"


def test_audio_drops_the_video_and_names_its_bitrate() -> None:
    made = convert.plan(profiles.Profile(kind="audio", bitrate="128k"))
    assert "-vn" in made.options
    assert made.options[made.options.index("-b:a") + 1] == "128k"
    assert made.suffix == ".mp3"


def test_a_thumbnail_seeks_before_the_input() -> None:
    """``-ss`` after ``-i`` decodes everything before the frame: the whole
    point of a thumbnail is that it does not."""
    made = convert.plan(profiles.Profile(kind="thumbnail", at=2.5, width=640))
    assert made.pre == ("-ss", "2.5")
    assert "-frames:v" in made.options


def test_a_trim_becomes_a_seek_and_a_duration() -> None:
    made = convert.plan(profiles.Profile(kind="video", start=5.0, end=12.5))
    assert made.pre == ("-ss", "5")
    assert made.options[made.options.index("-t") + 1] == "7.5"


def test_the_source_suffix_comes_from_the_name_it_arrived_with() -> None:
    assert convert.source_suffix("Demo.MOV") == ".mov"
    assert convert.source_suffix(None) == ""


@pytest.mark.asyncio
async def test_a_capped_gif_is_retried_smaller_until_it_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap is the profile's promise; the retry is how it is kept."""
    sizes = [9_000_000, 6_000_000, 4_000_000]
    plans: list[convert.Plan] = []

    async def fake_run(made: convert.Plan, data: bytes, name: str | None) -> bytes:
        plans.append(made)
        return b"x" * sizes[len(plans) - 1]

    monkeypatch.setattr(convert, "_run", fake_run)
    output, used = await convert.convert(
        b"video", profile_name="readme-gif", source_name="demo.mov"
    )
    assert len(output) <= 5_000_000
    assert len(plans) == 3
    assert "scale=540:-1" in " ".join(used.options)  # 960 -> 720 -> 540
    assert len(output) == 4_000_000


@pytest.mark.asyncio
async def test_a_real_conversion_through_the_packaged_ffmpeg() -> None:
    if not ffmpeg.version():
        pytest.skip("imageio-ffmpeg is not installed")
    output, made = await convert.convert(
        PNG_1PX, profile_name="png", source_name="pixel.png"
    )
    assert output.startswith(b"\x89PNG")
    assert made.content_type == "image/png"


@pytest.mark.asyncio
async def test_a_cancelled_run_does_not_leave_an_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker's job timeout cancels the task, not the child. An ffmpeg that
    outlives its job keeps a core and reads a temp file already deleted, and
    a queue of those is how a box with an idle event loop runs at 100%."""
    pidfile = tmp_path / "pid"
    fake = tmp_path / "fake-ffmpeg"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import os, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(ffmpeg, "binary", lambda: str(fake))

    task = asyncio.create_task(
        ffmpeg.convert([], source=b"x", source_suffix=".bin", output_suffix=".gif")
    )
    for _ in range(200):
        if pidfile.exists():
            break
        await asyncio.sleep(0.02)
    pid = int(pidfile.read_text())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(200):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.02)
    pytest.fail(f"ffmpeg child {pid} outlived the cancelled conversion")
