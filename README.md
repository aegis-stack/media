# aegis-stack-media

Media conversion jobs for an [Aegis Stack](https://aegis-stack.io) project:
the ffmpeg verbs you actually use, named by *profile* instead of by flags,
with the source and the result both in the project's object store.

```bash
aegis add media        # in an Aegis Stack project
media profiles         # what this project can make
media convert demo.mov --profile readme-gif
media convert hero.webp --profile x-video --last 20
```

Every conversion is a row - the profile, the source key, the result key,
its size, and what became of it - so nothing ends up named
`final_v2_actual.gif` on a desktop, and the page works the same from a
laptop or a phone.

## What it brings

| Piece | What it is |
|---|---|
| `app/services/media/` | The service: facade (`service.py`), reads (`queries.py`), one table (`media.media_job`), the converting domain, and adapters for ffmpeg and the profiles file. |
| `app/components/worker/queues/media.py` | The plugin's own queue: one conversion at a time, in its own `worker-media` container (1G), one branch per worker backend (arq, TaskIQ, Dramatiq). Without a worker, the job runs in-process. |
| `app/components/web_frontend/overseer_media.py` | Overseer > Media: the Overview (drop a file, pick what to make, keep the whole clip or its first or last seconds, see what was made) and Activity (the charts and every conversion). htmx stacks only. |
| `app/cli/media.py` | `media profiles`, `media convert` (`--first N`, `--last N`, `--wait`), `media results`. |
| `app/services/media/adapters/profiles.yml` | The profiles, as data. Add one and it appears in the page, the picker and the CLI. |

ffmpeg arrives as a pip dependency (`imageio-ffmpeg` ships a static build),
so no `apt-get` line, no "works on my laptop" divergence, and the same
binary on a VPS.

## Profiles

A profile is the result you want, not a list of flags:

```yaml
readme-gif:
  description: README demo GIF - 12 fps, 960 px wide, under 5 MB
  kind: gif
  fps: 12
  width: 960
  max_bytes: 5000000
```

`kind` is one of `gif`, `audio`, `image`, `jpeg`, `thumbnail`, `video`. A
`gif` with `max_bytes` is retried at a smaller width and frame rate until
it fits, so the cap is a promise the job keeps rather than a hope. A
`video` is H.264 in 4:2:0, which phones and feeds play (`x-video` is one
for X). A typo in the file is refused by name at load, not silently
ignored.

A source can be a video, a recording, an image, a GIF or an animated
WebP (which ffmpeg cannot read: Pillow decodes it frame by frame).

## Requirements

- an Aegis Stack project (0.20.0 or newer) with the **storage** component;
  `aegis add media` installs the **database** component if the project has
  none, because every result is a row.
- a **worker** is recommended and not required: with one, conversions run
  on the media queue in their own container; without one they run in the
  web process.

Installed without a worker, `media convert --wait` is the honest way to
run one (it converts here and prints the link).

## Notes

- The agent surface (`tools.py`, so Illiana can compose a conversion) is
  **not** in 0.1.0 on purpose: a plugin's tool cannot yet declare its
  expected effect to the project's `tests/core/test_tools.py` bookkeeping,
  nor be granted to the seeded agent. That is a framework ticket, tracked
  in `docs/tickets/`, not something to ship half-wired.
- The framework's template still carries an empty arq-only `media` queue
  stub; this plugin renders its own over it. Removing the stub is a
  framework ticket.

## Development

```bash
make install
make check           # ruff + the spec tests
```

The template's own tests (`src/aegis_stack_media/templates/.../tests/`) run
inside a generated project, not here: they import `app`. To run them, add
the plugin to a scratch stack and run its suite there.

## Tickets

The remaining work - more verbs, the agent surface, large uploads, other
worker backends, docs and publishing - is in `docs/tickets/`, each with
what "done" means.

## License

MIT.
