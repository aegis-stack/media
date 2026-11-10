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
from pathlib import Path
import sys

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.media.adapters import ffmpeg, profiles, webp
from app.services.media.domains import convert

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR42mP4z8CAFTEMLQkA"
    "KP8/wc53yE8AAAAASUVORK5CYII="
)

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg.version(), reason="imageio-ffmpeg is not installed"
)


async def _probe(output: bytes, tmp_path: Path, suffix: str = ".mp4") -> str:
    """What ffmpeg says of a result: its codec, pixel format and length."""
    out = tmp_path / f"out{suffix}"
    out.write_bytes(output)
    probe = await asyncio.create_subprocess_exec(
        ffmpeg.binary(), "-hide_banner", "-i", str(out),
        stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    return (await probe.communicate())[1].decode()


def test_a_gif_plan_is_the_palette_pass_at_the_profiles_numbers() -> None:
    """The palette is made from one read of the source and used on a second
    (``reads``), so frames stream: one read queued a 60 s clip's every
    frame, 1.6 GB, until its palette was done."""
    made = convert.plan(profiles.Profile(kind="gif", fps=12, width=960))
    graph = made.options[made.options.index("-filter_complex") + 1]
    look = "fps=12,scale=960:-1:flags=lanczos"
    assert graph == f"[0:v]{look},palettegen[p];[1:v]{look}[v];[v][p]paletteuse"
    assert made.reads == 2
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


def test_a_screenshot_seeks_to_its_frame_too() -> None:
    made = convert.plan(profiles.Profile(kind="image", at=1.0, width=1600))
    assert made.pre == ("-ss", "1")


def test_one_frame_ignores_the_trim() -> None:
    """A kind with no trim fields (``profiles.FIELDS``) takes one frame:
    a jpeg its first, never the whole clip's worth."""
    made = convert.plan(profiles.Profile(kind="thumbnail", at=2.5, start=1.0, end=5.0))
    assert made.pre == ("-ss", "2.5") and "-t" not in made.options
    assert convert.window(profiles.Profile(kind="jpeg", end=-5.0)) == {"at": 0.0}


def test_the_screenshot_is_shipped_a_second_in() -> None:
    assert profiles.get("png").at == 1


def test_a_smaller_image_is_a_jpeg_that_never_grows() -> None:
    """``min(w,iw)``: a picture narrower than the width is left its size."""
    made = convert.plan(profiles.Profile(kind="jpeg", width=1600))
    assert "scale='min(1600,iw)':-2:flags=lanczos" in made.options
    assert "-q:v" in made.options
    assert (made.suffix, made.content_type) == (".jpg", "image/jpeg")


def test_an_image_with_no_width_keeps_its_size() -> None:
    made = convert.plan(profiles.Profile(kind="image"))
    assert "-vf" not in made.options and made.suffix == ".png"


def test_a_video_is_one_phones_and_feeds_play() -> None:
    """A GIF or a screen recording comes in as RGB: left alone, x264 keeps
    it as 4:4:4, which X, Safari and iOS refuse, and it rejects an odd
    side outright."""
    made = convert.plan(profiles.Profile(kind="video"))
    assert made.options[made.options.index("-pix_fmt") + 1] == "yuv420p"
    assert made.options[made.options.index("-vf") + 1] == (
        "scale='trunc(iw/2)*2':-2:flags=lanczos"
    )


def test_a_video_for_x_is_never_wider_than_x_takes() -> None:
    x = profiles.get("x-video")
    assert (x.kind, x.width) == ("video", 1920)
    made = convert.plan(x)
    assert "scale='trunc(min(1920,iw)/2)*2':-2:flags=lanczos" in made.options


def test_a_trim_becomes_a_seek_and_a_duration() -> None:
    made = convert.plan(profiles.Profile(kind="video", start=5.0, end=12.5))
    assert made.pre == ("-ss", "5")
    assert made.options[made.options.index("-t") + 1] == "7.5"


def test_the_first_seconds_are_a_duration_alone() -> None:
    made = convert.plan(profiles.Profile(kind="video", end=5.0))
    assert made.pre == () and made.options[made.options.index("-t") + 1] == "5"


def test_the_last_seconds_are_a_seek_from_the_end() -> None:
    """A negative ``end`` is ffmpeg's own ``-sseof``: no length needs
    knowing first."""
    made = convert.plan(profiles.Profile(kind="video", start=2.0, end=-20.0))
    assert made.pre == ("-sseof", "-20") and "-t" not in made.options


@pytest.mark.asyncio
async def test_a_jobs_end_replaces_the_profiles_trim(
    async_db_session: AsyncSession,
) -> None:
    """``MediaJob.end`` goes on the profile as it is, sign and all."""
    from app.services.media.models import MediaJob

    job = MediaJob(profile="x-video", source_key="sha256/aa/bb/" + "0" * 64)
    job.end = -5.0
    profile = await convert.effective(async_db_session, job)
    assert (profile.start, profile.end) == (None, -5.0)


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

    async def fake_run(made: convert.Plan, *_: object) -> bytes:
        plans.append(made)
        return b"x" * sizes[len(plans) - 1]

    monkeypatch.setattr(convert, "_run", fake_run)
    output, used = await convert.convert(
        b"video", profile=profiles.get("readme-gif"), source_name="demo.mov"
    )
    assert len(output) <= 5_000_000
    assert len(plans) == 3
    # Aimed by the overshoot (9 MB for 5: 643), at least a quarter off (482).
    assert "scale=482:-1" in " ".join(used.options)
    assert len(output) == 4_000_000


@needs_ffmpeg
@pytest.mark.asyncio
async def test_a_real_conversion_through_the_packaged_ffmpeg() -> None:
    output, made = await convert.convert(
        PNG_1PX, profile=profiles.get("photo-png"), source_name="pixel.png"
    )
    assert output.startswith(b"\x89PNG")
    assert made.content_type == "image/png"


@needs_ffmpeg
@pytest.mark.asyncio
async def test_an_odd_sized_gif_becomes_a_video_that_plays(tmp_path: Path) -> None:
    """The README case: an animated GIF in, an H.264 4:2:0 MP4 out."""
    gif = tmp_path / "in.gif"
    made_gif = await asyncio.create_subprocess_exec(
        ffmpeg.binary(), "-loglevel", "error", "-f", "lavfi",
        "-i", "testsrc=size=33x17:rate=10:duration=0.5", str(gif),
    )  # fmt: skip
    assert await made_gif.wait() == 0
    output, made = await convert.convert(
        gif.read_bytes(), profile=profiles.get("x-video"), source_name="in.gif"
    )
    err = await _probe(output, tmp_path)
    assert made.content_type == "video/mp4"
    assert "h264" in err and "yuv420p" in err and "32x16" in err


def _webp(frames: int, ms: int | None = None) -> bytes:
    """A WebP of ``frames`` frames, ``ms`` each or each 100 ms longer
    than the last."""
    import io

    from PIL import Image

    # Each frame its own colour: the encoder merges identical ones.
    pictures = [Image.new("RGB", (33, 17), (i * 40, 40, 200)) for i in range(frames)]
    buffer = io.BytesIO()
    pictures[0].save(
        buffer,
        format="WEBP",
        save_all=frames > 1,
        append_images=pictures[1:],
        duration=[ms or 100 * (i + 1) for i in range(frames)],
        lossless=True,
    )
    return buffer.getvalue()


def test_an_animated_webp_goes_in_as_its_frames_with_their_timing(
    tmp_path: Path,
) -> None:
    """Why frames and a list, not the WebP: ``webp``'s docstring."""
    listing = webp.frames(_webp(3), tmp_path)
    assert listing is not None
    text = listing.decode()
    assert text.count("file '") == 3 and len(list(tmp_path.glob("*.png"))) == 3
    assert [line for line in text.splitlines() if line.startswith("duration")] == [
        "duration 0.1",
        "duration 0.2",
        "duration 0.3",
    ]
    assert text.count("option framerate 3000/600") == 3, "3 frames in 600 ms"
    assert webp.frames(_webp(1), tmp_path) is None, "ffmpeg reads a still WebP"
    assert webp.frames(PNG_1PX, tmp_path) is None


def test_a_webp_window_is_cut_from_its_frames_not_seeked(tmp_path: Path) -> None:
    """Only the frames asked for are written, the first and last cut to the
    window (why not a seek: ``webp``'s docstring)."""

    def kept(**window: float) -> list[str]:
        for old in tmp_path.glob("*.png"):
            old.unlink()
        listing = webp.frames(_webp(6, ms=100), tmp_path, **window)
        assert listing is not None
        text = listing.decode().splitlines()
        assert len(list(tmp_path.glob("*.png"))) == sum(
            line.startswith("file") for line in text
        )
        return [line.split()[1] for line in text if line.startswith("duration")]

    assert webp.durations(_webp(3)) == [100, 200, 300]
    assert kept(end=-0.3) == ["0.1", "0.1", "0.1"]
    assert kept(end=-0.25) == ["0.05", "0.1", "0.1"]
    assert kept(start=0.15, end=0.45) == ["0.05", "0.1", "0.1", "0.05"]
    assert kept(at=0.25) == ["0.001"], "one frame: the one showing at 0.25 s"
    assert kept(at=9.0) == ["0.001"], "past the end: the last frame"


@needs_ffmpeg
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "length"),
    [
        (profiles.get("x-video"), "00:00:00.60"),  # every frame, the last too
        (profiles.Profile(kind="video", end=-0.3), "00:00:00.30"),
    ],
)
async def test_an_animated_webp_becomes_a_video_that_plays(
    tmp_path: Path, profile: profiles.Profile, length: str
) -> None:
    """The README hero case: a WebP in, an H.264 MP4 of its length out."""
    output, _ = await convert.convert(
        _webp(6, ms=100), profile=profile, source_name="hero.webp"
    )
    err = await _probe(output, tmp_path)
    assert "h264" in err and "yuv420p" in err
    assert f"Duration: {length}" in err


@needs_ffmpeg
@pytest.mark.asyncio
async def test_an_animated_webp_becomes_a_readme_gif(tmp_path: Path) -> None:
    """Both reads of the palette pass come from the frame list."""
    output, _ = await convert.convert(
        _webp(6, ms=100), profile=profiles.get("readme-gif"), source_name="hero.webp"
    )
    assert output.startswith(b"GIF89a")
    assert "Video: gif" in await _probe(output, tmp_path, ".gif")


@pytest.mark.asyncio
async def test_ffmpeg_runs_as_many_threads_as_the_container_has_cpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sized by ``cpus.allowed``, per read and for the encoder and filters:
    ffmpeg's own count is the host's cores."""
    heard: list[str] = []

    async def fake_run(argv: list[str], *, timeout: int) -> None:
        heard.extend(argv)
        Path(argv[-1]).write_bytes(b"out")

    monkeypatch.setattr(ffmpeg.cpus, "allowed", lambda: 1)
    monkeypatch.setattr(ffmpeg, "_run", fake_run)
    monkeypatch.setattr(ffmpeg, "binary", lambda: "ffmpeg")
    await ffmpeg.convert(
        ["-an"], source=b"x", source_suffix=".mov", output_suffix=".gif", reads=2
    )
    assert heard.count("-i") == 2
    assert heard.count("-threads") == 3
    assert heard[heard.index("-filter_threads") + 1] == "1"


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
