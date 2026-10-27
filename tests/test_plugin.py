"""The plugin's spec: what ``aegis add media`` promises, pinned.

These run in the plugin repository, against the installed ``aegis-stack``.
The template's own tests run inside a generated project; this file guards
the declaration those tests cannot see - the components the plugin needs,
the queue it ships, the migration it owns, and the files removal walks.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from aegis.core.plugins.spec import PluginKind, PluginSpec

from aegis_stack_media.plugin import get_spec

try:  # the wiring, and the field it travels in (aegis-stack #1868)
    from aegis.core.plugins.spec import AgentToolWiring  # noqa: F401

    HAS_AGENT_TOOLS = True
except ImportError:  # pragma: no cover - a framework that predates the grant
    HAS_AGENT_TOOLS = False

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
TEMPLATES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "aegis_stack_media"
    / "templates"
    / "{{ project_slug }}"
)


def test_get_spec_returns_pluginspec() -> None:
    spec = get_spec()
    assert isinstance(spec, PluginSpec)
    assert spec.name == "media"
    assert spec.kind == PluginKind.SERVICE
    assert spec.verified is False


def test_entry_point_is_what_aegis_and_the_directory_look_for() -> None:
    """``aegis add`` discovers the plugin through the ``aegis.plugins`` entry
    point, and the plugin directory on aegis-stack.io verifies a package by
    reading the same entry point out of the wheel. A rename here breaks both."""
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    entry_points = project["entry-points"]["aegis.plugins"]
    assert entry_points["media"] == "aegis_stack_media.plugin:get_spec"
    assert "aegis-stack-plugin" in project["keywords"]
    assert project["urls"]["Aegis Plugin"].endswith("aegis-stack-media")


def test_the_bytes_need_a_store_and_the_work_prefers_a_worker() -> None:
    """Storage is not optional: a conversion whose result has nowhere to
    live is a process that read a file for nothing."""
    spec = get_spec()
    assert "storage" in spec.required_components
    assert "worker" in spec.recommended_components


def test_the_plugin_owns_its_queue_and_its_table() -> None:
    spec = get_spec()
    assert spec.worker_queues == ["media"]
    assert len(spec.migrations) == 1
    migration = spec.migrations[0]
    assert migration.service_name == "media"
    assert migration.schema == "media"


def test_ffmpeg_is_a_pip_dependency_not_an_apt_line() -> None:
    """The plugin installs into any stack without editing its Dockerfile."""
    spec = get_spec()
    joined = " ".join(spec.pyproject_deps)
    assert "imageio-ffmpeg" in joined
    assert all("ffmpeg " not in dep or "imageio" in dep for dep in spec.pyproject_deps)


@pytest.mark.skipif(
    not HAS_AGENT_TOOLS,
    reason="framework predates agent_tools (aegis-stack #1868)",
)
def test_the_agent_surface_declares_its_effect() -> None:
    """The tool ships, and the spec says what it does: declaring it is what
    grants it to the chat agent and the MCP server, and what lets the
    generated project's ``test_tools.py`` accept it (framework #1868)."""
    tool = TEMPLATES / "app" / "services" / "media" / "tools.py"
    assert tool.exists()
    assert 'register_tool(' in tool.read_text()

    declared = {entry.name: entry.effect for entry in get_spec().wiring.agent_tools}
    assert declared == {"media": "writes"}


@pytest.mark.parametrize(
    "path",
    [
        "app/services/media/service.py",
        "app/services/media/models.py.jinja",
        "app/services/media/queries.py",
        "app/services/media/adapters/ffmpeg.py",
        "app/services/media/adapters/profiles.yml",
        "app/services/media/domains/convert.py",
        "app/services/media/jobs.py.jinja",
        "app/services/media/health.py",
        "app/components/worker/queues/media.py.jinja",
        "app/components/web_frontend/overseer_media.py",
        "app/components/web_frontend/routes/partials/overseer_media.py",
        "app/cli/media.py",
    ],
)
def test_every_file_the_spec_claims_is_really_there(path: str) -> None:
    assert (TEMPLATES / path).exists(), f"missing template: {path}"


def test_every_rendered_path_is_declared_for_removal() -> None:
    """``aegis remove`` walks ``FileManifest``: a rendered path missing from
    it stays behind forever."""
    spec = get_spec()
    owned = list(spec.files.primary)
    for extra in spec.files.extras.values():
        owned.extend(extra)
    for path in ("app/services/media", "app/components/worker/queues/media.py"):
        assert path in owned


def test_the_page_is_an_htmx_page_only() -> None:
    """Its module imports a frontend that non-htmx stacks do not have, so
    every page file is in the ``include_htmx`` extras."""
    spec = get_spec()
    assert (
        "app/components/web_frontend/overseer_media.py"
        in spec.files.extras["include_htmx"]
    )
    page = spec.wiring.overseer_pages[0]
    assert page.name == "media"
    assert page.folder == "media"


def test_the_cli_verb_and_its_module_agree() -> None:
    """``cli_name`` names both the verb and the module the project imports;
    a rename in one place is a verb that lists and cannot run."""
    spec = get_spec()
    assert spec.cli_name == "media"
    assert (TEMPLATES / "app" / "cli" / "media.py").exists()


def test_the_queue_module_has_all_three_backends() -> None:
    """The file is one jinja template with a branch per backend: a missing
    branch is a stack where every conversion is queued to nothing."""
    source = (
        TEMPLATES / "app" / "components" / "worker" / "queues" / "media.py.jinja"
    ).read_text()
    for branch in ('worker_backend == "taskiq"', 'worker_backend == "dramatiq"'):
        assert branch in source
    assert source.count("convert_media_task") >= 3


def test_the_readme_section_names_what_a_project_gets() -> None:
    readme = get_spec().readme
    assert readme.cli_groups == ["media"]
    assert any("media profiles" in step for step in readme.first_steps)
