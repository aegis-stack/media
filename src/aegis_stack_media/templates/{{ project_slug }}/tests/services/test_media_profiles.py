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


def test_a_typo_in_the_yaml_is_refused_with_the_key(tmp_path: Path) -> None:
    """``extra="forbid"``: an ignored key is a GIF twice the cap, found late."""
    bad = tmp_path / "profiles.yml"
    bad.write_text("capped:\n  kind: gif\n  max_byte: 5000000\n")
    with pytest.raises(ValueError) as caught:
        profiles.read(bad)
    assert "max_byte" in str(caught.value)
    assert "capped" in str(caught.value)


def test_a_file_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "profiles.yml"
    bad.write_text("- just\n- a list\n")
    with pytest.raises(ValueError):
        profiles.read(bad)
