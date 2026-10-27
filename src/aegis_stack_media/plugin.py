"""PluginSpec for ``aegis-stack-media``.

Media conversion as a service: the ffmpeg verbs a project actually uses
(GIF from a video, resize, extract audio, a thumbnail at a timestamp),
each one named by a *profile* rather than by flags, with the source and
the result both in the project's object store. Every result is a row
with its profile, its source key and a link, so nothing ends up named
``final_v2_actual.gif`` on a desktop.

Design notes:

- ``required_components=["database", "storage"]`` — every result is a row
  and the bytes are the point. The store is content-addressed, so the same
  input uploaded twice costs one object, and a result survives the
  container it was made in.
- ``recommended_components=["worker"]`` — with a worker, a conversion
  runs on the plugin's own ``media`` queue in its own ``worker-media``
  process, so a three-minute transcode never holds a slot a request
  needs. Without one, ``jobs.start_conversion`` runs it in-process.
- ``worker_queues=["media"]`` — one process per queue. Its concurrency
  is the number of ffmpeg runs at once, which is a CPU decision, not a
  request-latency one.
- ``migrations`` — one table, ``media.media_job``, in the plugin's own
  Postgres schema (unqualified on SQLite, which has no schemas).
- ffmpeg itself is a pip dependency (``imageio-ffmpeg`` ships a static
  build), not an apt line: the plugin installs into any stack without
  the project's Dockerfile changing, and the same binary is present on a
  laptop, in the worker container and on a VPS.
- The agent surface (``tools.py``) is deliberately absent from 0.1.0: a
  plugin's tool cannot yet declare its expected effect to the project's
  ``tests/core/test_tools.py`` bookkeeping, nor be granted to the seeded
  agent. Tracked as a framework issue, not shipped broken here.
"""

from typing import Any

from aegis.core.file_manifest import FileManifest
from aegis.core.migration_spec import MigrationSpec
from aegis.core.plugins.spec import (
    HealthCheckWiring,
    OverseerPageWiring,
    PartCategory,
    PluginKind,
    PluginSpec,
    PluginWiring,
    ReadmeWiring,
    RouterWiring,
)

try:  # aegis-stack >= 0.17.0 (framework #1868)
    from aegis.core.plugins.spec import AgentToolWiring as _AgentToolWiring
except ImportError:  # pragma: no cover - older CLI, refused by aegis_version
    _AgentToolWiring = None


def _agent_tools() -> list[Any]:
    """The tool grant, where the framework can carry it.

    Guarded rather than imported at module top: an older ``aegis`` must be
    able to load this spec, or ``aegis_version`` never gets to explain the
    version it needs — it would be an ImportError from discovery instead.
    """
    if _AgentToolWiring is None:
        return []
    return [_AgentToolWiring("media", effect="writes")]


HEALTH_LABEL = "media"
"""What the health check reports under, the Overseer entry it is the page
of, and the folder its page templates live in. One spelling, because a
mismatch is a dead link rather than an error."""

OVERSEER_FILES = [
    "app/components/web_frontend/overseer_media.py",
    "app/components/web_frontend/routes/partials/overseer_media.py",
    "app/components/web_frontend/templates/pages/overseer/media",
    "tests/web/test_overseer_media.py",
]
"""The page's files, written only on stacks with the htmx frontend:
elsewhere they would import a frontend that is not there."""


def _htmx(opts: dict) -> bool:
    """The htmx frontend is present: where the plugin's page can land."""
    return bool(opts.get("include_htmx"))


def get_spec() -> PluginSpec:
    """Return the plugin spec."""
    return PluginSpec(
        name="media",
        kind=PluginKind.SERVICE,
        description=(
            "Media conversion jobs: ffmpeg verbs, profiles, results in the bucket"
        ),
        long_description=(
            "Turn a video into a README GIF that fits under five megabytes, "
            "resize an image, pull a thumbnail at a timestamp, extract audio. "
            "A profile names the result you want; the source and the result "
            "both live in the project's bucket, so the same page works from a "
            "laptop or a phone."
        ),
        category=PartCategory.APP,
        health_name=HEALTH_LABEL,
        version="0.1.0",
        verified=False,
        # 0.17.0 carries ``AgentToolWiring`` (framework #1868), which the
        # tool grant below needs to exist at all; 0.16.1 is the floor for
        # everything else (``overseer_pages``, gated ``extras``), so a tool
        # declaration on an older CLI is the version that rules it out, not
        # an ImportError.
        aegis_version=">=0.17.0",
        # The verb people type in this project's CLI, decoupled from the
        # install identifier (``media`` here, but the two may differ).
        cli_name="media",
        # The bytes need somewhere to live and each result is a row; the
        # work needs a worker to run on when the stack has one.
        required_components=["database", "storage"],
        recommended_components=["worker"],
        worker_queues=["media"],
        # A static ffmpeg build, so no Dockerfile apt line and no
        # "works on my laptop" divergence. The floor is 0.5 (the API this
        # uses - ``get_ffmpeg_exe`` - has not changed since); the ceiling
        # stays under 1.0 so a major release is a decision, not a surprise.
        # ``alembic`` because this plugin ships a migration and a
        # storage-only stack does not pull it in.
        pyproject_deps=["imageio-ffmpeg>=0.5,<1", "alembic>=1.13"],
        migrations=[
            MigrationSpec(
                service_name="media",
                description="Media conversion job store",
                # Proof it ran: the startup hook stamps instead of replaying
                # DDL on a database that already has this.
                stamp_signature=("table", "media.media_job"),
                schema="media",
            ),
        ],
        files=FileManifest(
            primary=[
                "app/services/media",
                "app/components/worker/queues/media.py",
                "app/cli/media.py",
                "tests/services/test_media_convert.py",
                "tests/services/test_media_jobs.py",
                "tests/services/test_media_layout.py",
                "tests/services/test_media_profiles.py",
                "tests/services/test_media_queries.py",
                "tests/services/test_media_service.py",
                "tests/services/test_media_tools.py",
            ],
            extras={"include_htmx": OVERSEER_FILES},
        ),
        wiring=PluginWiring(
            # One tool, and the effect it has: declaring it here is what grants
            # it to the chat agent and the MCP server. Its module is
            # app/services/media/tools.py, found by convention.
            agent_tools=_agent_tools(),
            routers=[
                # The page's own verbs (upload, start, poll). Its own prefix,
                # and the Overseer gate on the router, since it is not mounted
                # under the pages router that applies it.
                RouterWiring(
                    module="app.components.web_frontend.routes.partials.overseer_media",
                    alias="media_overseer_router",
                    tags=["overseer"],
                    when=_htmx,
                ),
            ],
            health_checks=[
                HealthCheckWiring(
                    module="app.services.media.health",
                    symbol="media_health",
                    label=HEALTH_LABEL,
                ),
            ],
            overseer_pages=[
                OverseerPageWiring(
                    name=HEALTH_LABEL,
                    module="app.components.web_frontend.overseer_media",
                    folder="media",
                    when=_htmx,
                ),
            ],
        ),
        readme=ReadmeWiring(
            reach="`media` CLI, and Overseer > Media for the page",
            cli_groups=["media"],
            setup_notes=[
                "ffmpeg ships with the plugin (imageio-ffmpeg); nothing to install.",
            ],
            first_steps=[
                "`<project> media profiles` lists the conversion profiles.",
                "Overseer > Media > Convert turns an upload into a link.",
            ],
        ),
    )
