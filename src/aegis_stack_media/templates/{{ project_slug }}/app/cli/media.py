"""Media CLI: the profiles this project offers, and converting a file.

Not an API client: a conversion is the service's own business, and the
plugin ships no JSON route. ``media convert --wait`` runs it here and
prints the link; without ``--wait`` the queue takes it (the worker when
the stack has one) and ``media results`` follows it.

Commands are ``async def`` with plain ``await``: the project's CLI harness
owns the event loop (``app.cli.main``), so nothing here calls
``asyncio.run``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.table import Table
import typer

from app.core.db import get_async_session
from app.core.formatting import format_bytes, format_relative_time
from app.core.storage import get_storage
from app.services.media import queries
from app.services.media.adapters.profiles import UnknownProfileError
from app.services.media.jobs import run_conversion, start_conversion
from app.services.media.service import MediaService

app = typer.Typer(
    name="media",
    help="Media conversions: profiles, convert a file, list results.",
    no_args_is_help=True,
)
console = Console()


@app.command("profiles")
def profiles() -> None:
    """List the conversion profiles this project offers."""
    table = Table(title="Media profiles", show_lines=False)
    table.add_column("Profile", style="cyan", no_wrap=True)
    table.add_column("Kind")
    table.add_column("What it makes")
    for view in MediaService().profiles():
        table.add_row(view.name, view.kind, view.description)
    console.print(table)


@app.command("convert")
async def convert(
    path: Annotated[Path, typer.Argument(help="The file to convert")],
    profile: Annotated[str, typer.Option("--profile", "-p", help="A profile name")],
    wait: Annotated[
        bool, typer.Option("--wait", help="Run it here and print the result")
    ] = False,
) -> None:
    """Store a file and convert it with a profile."""
    if not path.is_file():
        console.print(f"[red]No such file:[/red] {path}")
        raise typer.Exit(1)
    data = path.read_bytes()
    try:
        async with get_async_session() as session:
            job = await MediaService().submit(
                session,
                data,
                profile_name=profile,
                source_name=path.name,
            )
            await session.commit()
            media_job_id = int(job.id or 0)
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    console.print(
        f"Stored {format_bytes(len(data))} as job [bold]{media_job_id}[/bold]."
    )
    if wait:
        result = await run_conversion(media_job_id)
        if result["status"] != "done":
            console.print(f"[red]{result['error']}[/red]")
            raise typer.Exit(1)
        await _print_link(str(result["output_key"]), result["output_bytes"] or 0)
        return
    await start_conversion(media_job_id)
    console.print(f"Queued with [bold]{profile}[/bold]; `media results` follows it.")


async def _print_link(key: str, size: int) -> None:
    """The result's key, its size and, when the bucket gives one, its link."""
    url = await get_storage().presigned_url(key)
    console.print(f"Done: {format_bytes(size)} at [bold]{key}[/bold]")
    if url:
        console.print(url)


@app.command("results")
async def results(
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many")] = 20,
) -> None:
    """The newest conversions and what became of them."""
    async with get_async_session() as session:
        jobs = await queries.recent_jobs(session, limit=limit)
    table = Table(title="Media results")
    table.add_column("Id", justify="right")
    table.add_column("Profile")
    table.add_column("Status")
    table.add_column("In", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("When")
    for job in jobs:
        table.add_row(
            str(job.id),
            job.profile,
            job.status,
            format_bytes(job.source_bytes),
            format_bytes(job.output_bytes) if job.output_bytes else "-",
            format_relative_time(job.created_at),
        )
    console.print(table)
