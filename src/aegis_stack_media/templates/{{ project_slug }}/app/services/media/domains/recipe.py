"""A profile as ffmpeg hears it: pure, with no process and no bytes.

``plan`` turns a profile (and a retry's smaller width or frame rate) into
the ffmpeg options, so the recipe is testable without a binary;
``convert`` runs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.media.adapters import profiles

KINDS: dict[str, tuple[str, str]] = {
    "gif": (".gif", "image/gif"),
    "audio": (".mp3", "audio/mpeg"),
    "image": (".png", "image/png"),
    "jpeg": (".jpg", "image/jpeg"),
    "thumbnail": (".png", "image/png"),
    "video": (".mp4", "video/mp4"),
}
"""Each kind's output suffix and media type: one table, read by the plan
and by the row that records what was stored."""


@dataclass(frozen=True)
class Plan:
    """One conversion, as ffmpeg will hear it."""

    pre: tuple[str, ...]
    """Options before ``-i``: a seek belongs here, or it decodes first."""
    options: tuple[str, ...]
    suffix: str
    content_type: str
    reads: int = 1
    """How many times the source is an input (``ffmpeg.convert``)."""


def _seconds(value: float) -> str:
    """A number of seconds as ffmpeg's own spelling (``1.5``, not ``1.5s``)."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def window(profile: profiles.Profile) -> dict[str, float | None]:
    """What of the source a profile reads: its trim, or for a kind without
    one the frame ``at`` picks. A thumbnail's is a second in, past a fade
    from black, unless it is of a still (``profiles.profile_fields``); any other's
    the first."""
    if profile.kind in profiles.TRIMS:
        return {"start": profile.start, "end": profile.end}
    if profile.at is not None:
        return {"at": profile.at}
    seeks = "at" in profiles.profile_fields(profile.kind, profile.takes)
    return {"at": 1.0 if profile.kind == "thumbnail" and seeks else 0.0}


def _cut(profile: profiles.Profile, pre: list[str], options: list[str]) -> None:
    """The ``window`` as seeks: the trim as a seek and a duration (``-to``
    after an input seek counts from the seek, not the file), a negative
    ``end`` as a seek from the end that needs no length known."""
    cut = window(profile)
    at, start, end = cut.get("at"), cut.get("start"), cut.get("end")
    if end is not None and end < 0:
        pre += ["-sseof", _seconds(end)]
        return
    if at or start:
        pre += ["-ss", _seconds(at or start or 0.0)]
    if end is not None:
        options += ["-t", _seconds(end - (start or 0.0))]


def plan(
    profile: profiles.Profile,
    *,
    width: int | None = None,
    fps: int | None = None,
    seek: bool = True,
) -> Plan:
    """The profile as argv. ``width``/``fps`` override the profile's own,
    which is how a capped GIF is retried smaller; ``seek=False`` reads the
    whole input (its frames are already the window)."""
    suffix, content_type = KINDS[profile.kind]
    pre: list[str] = []
    options: list[str] = []
    reads = 1
    if profile.kind == "gif":
        w, f = width or profile.width or 960, fps or profile.fps or 12
        look = f"fps={f},scale={w}:-1:flags=lanczos"
        # The palette from one read, used on a second, so the frames
        # stream: one read queued a 60 s clip's every frame (1.6 GB) until
        # the palette was done.
        options += [
            "-filter_complex",
            f"[0:v]{look},palettegen[p];[1:v]{look}[v];[v][p]paletteuse",
            "-an",
            "-loop",
            "0",
        ]
        reads = 2
    elif profile.kind == "audio":
        options += ["-vn", "-c:a", "libmp3lame", "-b:a", profile.bitrate or "192k"]
    elif profile.kind in profiles.ONE_FRAME:
        if w := profile.width or (640 if profile.kind == "thumbnail" else None):
            options += ["-vf", f"scale={w}:-1:flags=lanczos"]
        options += ["-frames:v", "1"]
    elif profile.kind == "jpeg":
        options += [
            "-vf",
            f"scale='min({profile.width or 1600},iw)':-2:flags=lanczos",
            "-frames:v",
            "1",
            "-q:v",
            "3",
        ]
    else:  # video
        # 4:2:0 and even sides, or phones and feeds refuse an RGB source
        # (a GIF, a screen recording); a width never grows the picture.
        w = f"min({profile.width},iw)" if profile.width else "iw"
        options += [
            "-vf",
            f"scale='trunc({w}/2)*2':-2:flags=lanczos",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            str(profile.crf if profile.crf is not None else 23),
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
    if seek:
        _cut(profile, pre, options)
    return Plan(tuple(pre), tuple(options), suffix, content_type, reads)


def source_suffix(name: str | None) -> str:
    """The extension ffmpeg should assume for the input.

    Taken from the name the upload came with; a nameless upload lets
    ffmpeg probe the bytes, which it does on its own.
    """
    return Path(name or "").suffix.lower()
