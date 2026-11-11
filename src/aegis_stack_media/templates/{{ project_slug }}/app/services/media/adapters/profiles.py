"""Profiles as data: the recipes a project offers, read from ``profiles.yml``.

A profile names the result you want ("README GIF, 12 fps, 960 px, under
5 MB"), not a list of flags. The YAML holds the few numbers that vary;
the recipe (``domains/recipe.py``) turns the kind and its numbers into
argv, so a
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

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
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
"""The settings each kind uses, so a gif offers no crf and an mp3 no width;
any other is refused by name (``Profile``). A kind without the trim makes
one frame: the one ``at`` picks, or the first. A profile only for stills
has no ``at`` either (``profile_fields``): a picture has no second to seek to."""
TRIMS = frozenset(kind for kind, fields in FIELDS.items() if "end" in fields)
ONE_FRAME = frozenset(kind for kind, fields in FIELDS.items() if "at" in fields)
"""Kinds that pick their frame with ``at``: one picture, whatever the
clip's length."""
_SETTINGS = frozenset(field for fields in FIELDS.values() for field in fields)


def profile_fields(kind: str, takes: tuple[str, ...]) -> tuple[str, ...]:
    """The settings a profile uses (``FIELDS``), for the files it takes."""
    used = FIELDS.get(kind, ())
    return tuple(f for f in used if f != "at") if takes == ("image",) else used


def unused(kind: str, takes: tuple[str, ...]) -> frozenset[str]:
    """The settings a profile does not take: refused on it, and not read
    from a project's saved settings for it."""
    return _SETTINGS - set(profile_fields(kind, takes))


class UnknownProfileError(KeyError, ValueError):
    """A profile name the project does not have: a lookup that missed, and
    a bad value a form or a tool says back as it is."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


def _fault(exc: ValidationError) -> str:
    """The first thing a profile's settings got wrong, field first; a rule
    across fields (``Profile``'s own) says only what it raised."""
    first = exc.errors()[0]
    said = str(first.get("ctx", {}).get("error") or first["msg"])
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {said}" if where else said


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

    @model_validator(mode="after")
    def _fits_its_kind(self) -> Profile:
        """A setting the profile does not use (``profile_fields``) is refused, not
        ignored."""
        extra = unused(self.kind, self.takes)
        named = [
            f
            for f in type(self).model_fields
            if f in extra and getattr(self, f) is not None
        ]
        if named:
            raise ValueError(f"{self.kind} takes no {', '.join(named)}")
        if self.end == 0:
            raise ValueError("end: 0 seconds keeps nothing")
        return self


def checked(settings: dict[str, object], end: float | None = None) -> Profile:
    """``settings`` as a profile, with one job's own ``end`` (``MediaJob.end``)
    in place of its trim when given. ``ValueError`` says what does not fit."""
    if end is not None:
        settings = {**settings, "start": None, "end": end}
    try:
        return Profile.model_validate(settings)
    except ValidationError as exc:
        raise ValueError(_fault(exc)) from None


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
            found[str(name)] = checked(body or {})
        except ValueError as exc:
            raise ValueError(f"{source.name}: profile {name!r}, {exc}") from None
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
