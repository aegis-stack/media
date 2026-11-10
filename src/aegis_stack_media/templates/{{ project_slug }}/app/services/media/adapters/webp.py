"""An animated WebP, made readable for ffmpeg.

ffmpeg reads a still WebP but not an animated one (7.1 nor 8.0: it finds
no picture size). Pillow decodes it a frame at a time; each goes to disk
as a PNG, and an ffconcat list names them with each frame's own duration,
which ffmpeg reads (``CONCAT``). Every colour and the timing are kept, and
one frame is in memory at a time: an APNG of the same frames, Pillow's
other way out, holds them all and took 6.8 GB for a 64 s 1080p clip.

A trim, or the one frame a screenshot wants, is cut here, from the
frames, and the list is the window: ffmpeg's seek into a frame list loses
the timestamps (every frame lands at 0).

ponytail: a PNG per frame costs a save and a read of each (about 6 MB and
90 ms for a noisy 1080p one); raw frames piped to ffmpeg's stdin skip
both, if long noisy clips become the common case.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

CONCAT = ("-f", "concat", "-safe", "0")
"""The input options for the list: ``-safe 0`` because it names absolute
paths, ones ``frames`` wrote itself."""


def durations(data: bytes) -> list[int]:
    """Each frame's milliseconds, from its ``ANMF`` chunk's header (24 bits,
    12 bytes in): known before a pixel is decoded."""
    found: list[int] = []
    offset = 12
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        if data[offset : offset + 4] == b"ANMF":
            found.append(int.from_bytes(data[offset + 20 : offset + 23], "little"))
        offset += 8 + size + (size & 1)
    return found


def animated(data: bytes) -> bool:
    """A ``VP8X`` header with its animation bit: the same test the page
    makes before an upload (``_overview.html``)."""
    head = data[:21]
    return (
        len(head) == 21
        and head[:4] == b"RIFF"
        and head[8:16] == b"WEBPVP8X"
        and (head[20] & 2 > 0)
    )


def _window(
    lengths: list[int], start: float | None, end: float | None, at: float | None
) -> dict[int, int]:
    """The frames to keep, by index, each with the milliseconds it shows:
    ``at`` is a window of one millisecond, so it keeps the frame showing."""
    total = sum(lengths)
    if at is not None:
        lo = min(round(at * 1000), total - 1)
        hi = lo + 1
    elif end is not None and end < 0:
        lo, hi = max(0, total + round(end * 1000)), total
    else:
        lo = round((start or 0) * 1000)
        hi = total if end is None else min(total, round(end * 1000))
    kept: dict[int, int] = {}
    shown = 0
    for index, ms in enumerate(lengths):
        begins, shown = shown, shown + ms
        if shown > lo and begins < hi:
            kept[index] = min(shown, hi) - max(begins, lo)
    return kept


def frames(
    data: bytes,
    directory: Path,
    *,
    start: float | None = None,
    end: float | None = None,
    at: float | None = None,
) -> bytes | None:
    """``data``'s frames written into ``directory``, and the ffconcat list
    naming them, when it is an animated WebP; else None (ffmpeg reads it as
    it is). Only the window is written: ``start``/``end`` (a negative
    ``end`` the last seconds), or the one frame showing ``at``. CPU work:
    the caller runs it off the loop."""
    if not animated(data):
        return None
    kept = _window(durations(data), start, end, at)
    written: list[tuple[Path, int]] = []
    with Image.open(io.BytesIO(data)) as picture:
        # Frames decode in order, each over the one before: every frame up
        # to the last kept is read, only the kept are saved.
        for index in range(max(kept, default=-1) + 1):
            picture.seek(index)
            if index in kept:
                path = directory / f"{index:06d}.png"
                picture.save(path, format="PNG", compress_level=1)
                written.append((path, kept[index]))
    # Each picture's clock is the list's own rate, as an exact fraction: at
    # ffmpeg's default 25 the starts round to 40 ms, and the last frame
    # (whose duration concat drops) lasts one tick of it.
    # ponytail: a WebP of uneven durations rounds to its average rate.
    rate = f"{len(written) * 1000}/{max(1, sum(ms for _, ms in written))}"
    lines = ["ffconcat version 1.0"]
    for path, ms in written:
        lines += [
            f"file '{path}'",
            f"option framerate {rate}",
            f"duration {ms / 1000:g}",
        ]
    return "\n".join(lines).encode()
