# 23 — Pillow for the image pipeline (decision + design)

**Repo:** `aegis-stack-media` · **Status:** proposed, evidence attached

## The question

Should `image`/`thumbnail` run through Pillow in-process instead of through
the ffmpeg subprocess? The plugin currently uses ffmpeg for all five kinds,
which costs one dep (`imageio-ffmpeg`, 21–27 MB: it is ~all binary) and
spawns a child process even to resize a JPEG.

## Evidence (measured, this repo's box)

8 × (open a 3.4 MB JPEG → LANCZOS resize to 1200×900 → encode JPEG q85):

| | wall time |
|---|---|
| sequential, 8 images | 317 ms |
| 8 threads, same images | **59 ms** (5.4×) |

Interpreter: CPython **3.11.14**, `sys._is_gil_enabled() == True`. So
Pillow's hot paths — libjpeg/libpng/zlib codec work and the resample kernels
— release the GIL, and **a plain thread pool parallelizes them on every
stack we support today**. No free-threaded interpreter needed.

### What 3.14t does and does not add

- Pillow 13 ships `cp314t` wheels (and `cp315t`; 12.3 dropped 3.13t), so it
  installs and runs on a free-threaded build.
- It adds no speed here: the codec work was never GIL-bound.
- Pillow 13.0.0 release notes, "Thread safety for free-threaded Python":
  *"Critical sections now protect most operations on core image objects,
  such as conversion, pasting, filtering and pixel access"* — i.e. under
  3.14t those calls take a lock to be safe. Thread **safety**, not thread
  **speedup**; possibly slower in a batch.
- 12.2 added the same protection for FreeType font objects. `Image.quantize`
  (libimagequant) is not covered by those notes — verify before relying on
  it concurrently.

Conclusion: `freerange` / free-threading is a stack-wide bet for services
that run real Python bytecode. Media is not one: its parallel speedup comes
from C releasing the GIL, present on 3.11 already.

## Decision

Adopt **Pillow for the image pipeline**, keep **ffmpeg for video and audio**:

| kind | engine | why |
|---|---|---|
| `image` | Pillow | no temp files, lower peak, no child process for the common case |
| `thumbnail` (image source) | Pillow | same, plus EXIF orientation is one call |
| `thumbnail` (video source) | ffmpeg | a frame from a video is a decode |
| `gif`, `audio`, `video` | ffmpeg | not Pillow's job |

Cost: `pillow>=13,<14` in `pyproject_deps` (+4.9 MB — it is already an
aegis-stack dependency on the render side, and already present in stacks with
the documents service; it is **not** present in the app container otherwise,
because the template only ships it under `include_documents`).

## Design

- `adapters/pillow.py`: pure functions over bytes —
  `resize(data, *, width, height=None, format, quality) -> bytes` and
  `thumbnail(data, *, at=None, width) -> bytes`; decode with
  `Image.open(io.BytesIO(...))`, encode into a `BytesIO`. No temp files.
- **EXIF orientation** via `ImageOps.exif_transpose` — a phone photo that
  comes out sideways is the classic bug, and ffmpeg happened to handle it.
- **Decompression bombs:** `Image.MAX_IMAGE_PIXELS` at the app's honest
  ceiling (a 40 MP photo, say), and turn `DecompressionBombWarning` into the
  job's error text. A bomb must be a `failed` row, not a dead worker.
- **Fan-out:** `asyncio.to_thread` behind a module-level `asyncio.Semaphore`
  (2–4), because threads share one address space: 4 concurrent 2400×1800
  decodes is 4 × ~17 MB of buffers, times however many worker processes.
  Not `app.core.concurrency.cpu_bound` — it serializes to one at a time on
  the assumption "that's all the GIL runs anyway", which is false for Pillow.
- **No kill switch.** A thread cannot be cancelled (same caveat as
  `freerange`'s timeout note). The semaphore bounds it; a pathological filter
  holds a slot until it returns. This is the residual argument for keeping
  ffmpeg on anything large or untrusted.
- **Kind routing:** `domains/convert.py` chooses the engine from the profile's
  kind *and* the source's actual format (magic bytes, not the filename),
  so a `.png` renamed `.mp4` still goes the image way. A kind no engine can
  serve fails with both names in the message.
- `health.py` reports the PIL version beside the ffmpeg one, and the
  Overview says which engine each profile uses.

## Done when

- A JPEG, a PNG and a 40 MP photo all convert without a subprocess (assert
  no child was spawned), and the 40 MP one is refused by the bomb guard when
  `MAX_IMAGE_PIXELS` is lowered in the test.
- A sideways phone JPEG comes out upright (fixture with EXIF orientation 6).
- The batch test shows the semaphore's ceiling is respected and the pool is
  not the event loop's (the loop stays responsive while converting).
- A stack **without** the documents service still has Pillow available (the
  dep is declared, not inherited), and one with it does not pin it twice.
- ffmpeg is still required for `gif`/`audio`/`video`; the health check says
  so when it is missing, and those profiles are hidden from the picker.
