"""The layout: the spine at the service root, and who defines what.

Behavioural tests cannot see a layout - a conversion works the same
whether its recipe lives in a domain or in the facade - so a later change
that drops a function into whichever file was open passes the rest of the
suite. These assertions are the only place the split is stated.

The claim: the package root is the service's spine (its facade, its
tables, its reads, its entry points, its wiring), converting is a domain,
and what it talks to (ffmpeg, the profiles file) is an adapter.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.services.system.service_parts import PIECES

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "app" / "services" / "media"

SPINE = {
    "service.py",
    "models.py",
    "queries.py",
    "schemas.py",
    "health.py",
    "jobs.py",
}
"""What the service standard puts at a package's root."""

CONVENTIONS = {f"{name}.py" for name, (_, kind) in PIECES.items() if kind == "entry"}

OWNERS = {
    "service.py": {"MediaService"},
    "queries.py": {"job_by_id", "recent_jobs", "totals", "profile_counts"},
    "domains/convert.py": {
        "Plan",
        "plan",
        "convert",
        "submit",
        "run",
        "fail",
        "source_suffix",
    },
    "adapters/ffmpeg.py": {"FfmpegError", "binary", "version", "convert"},
    "adapters/profiles.py": {
        "Profile",
        "UnknownProfileError",
        "read",
        "get",
        "all_profiles",
    },
}
"""Each public callable's one home: a duplicate is a defect, not a copy."""


def _modules(folder: Path) -> set[str]:
    return {
        str(path.relative_to(SERVICE)).replace("\\", "/")
        for path in folder.rglob("*.py")
        if path.name != "__init__.py"
    }


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    } | {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def test_the_root_is_the_spine_and_nothing_else() -> None:
    """A module at the root that is neither the spine nor a convention is a
    part nobody classified: it renders on no page and belongs in a domain."""
    at_root = {path.name for path in SERVICE.glob("*.py") if path.name != "__init__.py"}
    assert at_root <= SPINE | CONVENTIONS
    assert SPINE <= at_root


def test_every_declared_owner_defines_what_it_owns() -> None:
    for relative, names in OWNERS.items():
        defined = _top_level_functions(SERVICE / relative)
        missing = names - defined
        assert not missing, f"{relative} no longer defines {sorted(missing)}"


def test_only_the_entry_points_open_a_session() -> None:
    """The caller owns the unit of work: a service function takes the
    session it is given. The three with no caller - the queue task
    (``jobs``), the health probe and the agent's tool - open their own,
    and everywhere else it is the SQLite lock again."""
    openers = {
        relative
        for relative in _modules(SERVICE)
        if "get_async_session(" in (SERVICE / relative).read_text()
    }
    assert openers <= {"jobs.py", "health.py", "tools.py"}
