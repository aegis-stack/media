"""Profiles are data: the file loads, and a mistake in it is refused by name.

A profile is the plugin's public surface for "what can this project make",
so the checks here are about the file a project edits, not about ffmpeg.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.media.adapters import profiles


def test_the_shipped_profiles_load_and_readme_gif_is_capped() -> None:
    found = profiles.all_profiles()
    assert {"readme-gif", "mp3", "png", "thumb"} <= set(found)
    readme = found["readme-gif"]
    assert readme.kind == "gif"
    assert readme.max_bytes == 5_000_000
    assert readme.fps and readme.width


def test_a_profile_the_project_does_not_have_is_named_in_the_error() -> None:
    with pytest.raises(profiles.UnknownProfileError) as caught:
        profiles.get("no-such-profile")
    assert "readme-gif" in str(caught.value)


@pytest.mark.parametrize(
    ("body", "said"),
    [
        # ``extra="forbid"``: an ignored key is a GIF twice the cap, found late.
        ("kind: gif\n  max_byte: 5000000", "'still', max_byte"),
        # A trim on a still makes the same frame as without one.
        ("kind: image\n  end: -5", "'still', image takes no end"),
        ("kind: thumbnail\n  start: 1\n  end: 5", "thumbnail takes no start, end"),
        # A picture has one frame: there is no second to seek to.
        ("kind: thumbnail\n  takes: [image]\n  at: 1", "thumbnail takes no at"),
    ],
)
def test_a_mistake_in_the_file_is_refused_by_name(
    tmp_path: Path, body: str, said: str
) -> None:
    bad = tmp_path / "profiles.yml"
    bad.write_text(f"still:\n  {body}\n")
    with pytest.raises(ValueError, match=said):
        profiles.read(bad)


def test_one_list_of_kinds() -> None:
    """The type, the settings table and the recipe's suffixes name the same
    kinds: one missing from ``FIELDS`` would crash the check, not refuse."""
    from typing import get_args

    from app.services.media.domains.recipe import KINDS

    assert set(get_args(profiles.Kind)) == set(profiles.FIELDS) == set(KINDS)


def test_a_file_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "profiles.yml"
    bad.write_text("- just\n- a list\n")
    with pytest.raises(ValueError):
        profiles.read(bad)
