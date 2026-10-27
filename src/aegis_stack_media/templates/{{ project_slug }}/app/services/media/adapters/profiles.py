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

Kind = Literal["gif", "audio", "image", "thumbnail", "video"]


class UnknownProfileError(KeyError):
    """A profile name the project does not have."""


class Profile(BaseModel):
    """One conversion recipe: what kind, and the numbers that vary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Kind
    description: str = ""
    # gif
    fps: int | None = Field(default=None, gt=0, le=60)
    width: int | None = Field(default=None, gt=0)
    max_bytes: int | None = Field(default=None, gt=0)
    # audio
    bitrate: str | None = None
    # thumbnail
    at: float | None = Field(default=None, ge=0.0)
    # video
    crf: int | None = Field(default=None, ge=0, le=51)
    # every kind
    start: float | None = Field(default=None, ge=0.0)
    end: float | None = Field(default=None, ge=0.0)


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
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first["loc"]) or "(profile)"
            raise ValueError(
                f"{source.name}: profile {name!r}, {where}: {first['msg']}"
            ) from None
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
