"""ffmpeg as a process: which binary, and one run whose bytes come back.

``imageio-ffmpeg`` ships a static build of ffmpeg as a pip dependency, so
the plugin needs no ``apt-get`` line in the project's Dockerfile and the
same binary is present on a laptop, in the worker container and on a
VPS. A system ffmpeg is still honoured when the package is missing.

Every run gets its own temporary directory, so two conversions never see
each other's files, and the result is read back as bytes: the caller
hands the output to the object store, never to a path on a container's
disk that the next deploy discards.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 600
"""Ten minutes: the media queue's own job timeout, so a run that hangs is
killed by this before the worker kills the process."""

STDERR_TAIL = 600
"""How much of ffmpeg's complaint travels back with the error."""


class FfmpegError(RuntimeError):
    """A run that exited non-zero, carrying what ffmpeg said."""


def binary() -> str:
    """The ffmpeg to run: the packaged static build, else the system's."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - missing package or a broken build
        found = shutil.which("ffmpeg")
        if found is None:
            raise FfmpegError(
                "ffmpeg is not available: install the plugin's imageio-ffmpeg "
                "dependency, or put ffmpeg on PATH"
            ) from None
        return found


def version() -> str:
    """The packaged build's version, or an empty string when unknown.

    Read from the distribution rather than by running ``ffmpeg -version``:
    a health check should not spawn a process to say it is alive.
    """
    try:
        from importlib.metadata import version as dist_version

        return dist_version("imageio-ffmpeg")
    except Exception:  # noqa: BLE001 - a system ffmpeg has no metadata
        return ""


async def _reap(process: asyncio.subprocess.Process) -> None:
    """Kill a child that will not finish, and wait until it is really gone.

    A cancelled caller (a worker's job timeout, a shutdown) must not leave an
    orphan: ffmpeg would keep a core busy and read a temp file this call is
    about to delete. Killing and *waiting* is the whole point - ``kill()``
    alone leaves a zombie, and a ``wait`` raced against the event loop's exit
    leaves a live process.
    """
    if process.returncode is not None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        return
    await process.wait()


async def _run(argv: Sequence[str], *, timeout: int) -> None:
    """Run ffmpeg; raise ``FfmpegError`` with its stderr when it fails."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise FfmpegError(f"could not start ffmpeg: {exc}") from None
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        await _reap(process)
        raise FfmpegError(f"ffmpeg exceeded {timeout}s") from None
    except BaseException:
        # A cancelled caller never reaches the ``if`` below: without this the
        # child outlives the task, holds a core, and its temp files vanish.
        await _reap(process)
        raise
    if process.returncode != 0:
        tail = stderr.decode("utf-8", "replace")[-STDERR_TAIL:].strip()
        raise FfmpegError(f"ffmpeg exited {process.returncode}: {tail}")


async def convert(
    args: Sequence[str],
    *,
    source: bytes,
    source_suffix: str,
    output_suffix: str,
    pre: Sequence[str] = (),
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    """Run ffmpeg over ``source`` and return the bytes of the output file.

    ``args`` are the options between the input and the output, and ``pre``
    the ones that must precede ``-i`` (a seek belongs there). The adapter
    owns ``-i``, the paths and ``-y``: those are the process's business,
    not the recipe's.
    """
    with tempfile.TemporaryDirectory(prefix="aegis-media-") as work:
        root = Path(work)
        input_path = root / f"input{source_suffix or '.bin'}"
        output_path = root / f"output{output_suffix}"
        input_path.write_bytes(source)
        await _run(
            [
                binary(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                *pre,
                "-i",
                str(input_path),
                *args,
                str(output_path),
            ],
            timeout=timeout,
        )
        if not output_path.exists():
            raise FfmpegError("ffmpeg produced no output file")
        return output_path.read_bytes()
