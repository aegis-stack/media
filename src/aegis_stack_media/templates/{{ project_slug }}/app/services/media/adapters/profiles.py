"""Profiles as data: the recipes a project offers, read from ``profiles.yml``.

A profile names the result you want ("README GIF, 12 fps, 960 px, under
5 MB"), not a list of flags. The YAML holds the few numbers that vary;
the conversion domain turns the kind and its numbers into argv, so a
project can add a profile without writing Python and a new ffmpeg option
has one home.

``extra="forbid"`` on the model is deliberate: a typo in the YAML
(``max_byte``) is refused at load with the key named, rather than
silently ignored and found later as a GIF twice the cap.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
import yaml

PROFILES_FILE = Path(__file__).with_name("profiles.yml")

Kind = Literal["gif", "audio", "image", "jpeg", "thumbnail", "video"]
Source = Literal["video", "image", "audio"]

TRIM_FIELDS: tuple[str, ...] = ("start", "end")
"""Empty means the whole clip."""
FIELDS: dict[str, tuple[str, ...]] = {
    "gif": ("fps", "width", "max_bytes", *TRIM_FIELDS),
    "audio": ("bitrate", *TRIM_FIELDS),
    "image": ("at", "width"),
    "jpeg": ("width",),
    "thumbnail": ("at", "width"),
    "video": ("crf", "width", *TRIM_FIELDS),
}
"""The settings each kind uses, so a gif offers no crf and an mp3 no width.
A kind without the trim makes one frame: the one ``at`` picks, or the first."""
TRIMS = frozenset(kind for kind, fields in FIELDS.items() if "end" in fields)


class UnknownProfileError(KeyError, ValueError):
    """A profile name the project does not have: a lookup that missed, and
    a bad value a form or a tool says back as it is."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


def fault(exc: ValidationError) -> str:
    """The first thing a profile's settings got wrong, field first."""
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"]) or "(profile)"
    return f"{where}: {first['msg']}"


class Profile(BaseModel):
    """One conversion recipe: what kind, and the numbers that vary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Kind
    title: str = ""
    """What you get, as the picker offers it ("GIF for a README")."""
    description: str = ""
    takes: tuple[Source, ...] = ("video",)
    """The files it is offered for, by the first half of their media type."""
    # gif
    fps: int | None = Field(default=None, gt=0, le=60)
    width: int | None = Field(default=None, gt=0)
    max_bytes: int | None = Field(default=None, gt=0)
    # audio
    bitrate: str | None = None
    # image, thumbnail: the frame, seconds in
    at: float | None = Field(default=None, ge=0.0)
    # video
    crf: int | None = Field(default=None, ge=0, le=51)
    # every kind with a length; a negative ``end`` is the last that many
    # seconds (``MediaJob.end``), and ``start`` goes unused
    start: float | None = Field(default=None, ge=0.0)
    end: float | None = None


def read(path: Path | None = None) -> dict[str, Profile]:
    """Every profile in ``path`` (the shipped file by default).

    Raises ``ValueError`` naming the file and the offending key: a bad
    profile is a configuration mistake the reader can fix, not a crash.
    """
    source = path or PROFILES_FILE
    try:
        raw = yaml.safe_load(source.read_text()) or {}
    except OSError as exc:
        raise ValueError(f"could not read media profiles: {exc}") from None
    if not isinstance(raw, dict):
        raise ValueError(f"{source.name} must be a mapping of profile names")
    found: dict[str, Profile] = {}
    for name, body in raw.items():
        try:
            found[str(name)] = Profile.model_validate(body or {})
        except ValidationError as exc:
            raise ValueError(f"{source.name}: profile {name!r}, {fault(exc)}") from None
    return found


@lru_cache(maxsize=1)
def all_profiles() -> dict[str, Profile]:
    """The project's profiles, read once per process.

    Cached because the file ships with the code: a project that wants to
    change a profile edits it and restarts, the same as any setting.
    """
    return read()


def get(name: str) -> Profile:
    """The profile called ``name``; ``UnknownProfileError`` when there is none."""
    try:
        return all_profiles()[name]
    except KeyError:
        known = ", ".join(sorted(all_profiles())) or "none"
        raise UnknownProfileError(
            f"unknown media profile {name!r} (have: {known})"
        ) from None
