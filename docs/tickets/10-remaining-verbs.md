# 10 — The remaining verbs: image formats, resize, trim in the UI

**Repo:** `aegis-stack-media`

## Why

0.1.0 ships five kinds — `gif`, `image`, `audio`, `thumbnail`, `video` — and
every one of them is a *whole file*. The conversions that actually get done
by hand also need: a target format (JPEG/WebP instead of PNG), a resize that
can also shrink, and a trim you can see (start/end) rather than write in the
YAML.

## Scope

- `adapters/profiles.py`: `Profile` gains `format` (`png`/`jpeg`/`webp` for
  `image`/`thumbnail`), `quality` for the lossy formats, and `height` as the
  other half of `width`.
- `domains/convert.py`: the argv per format; the `KINDS` table becomes a
  per-(kind, format) suffix/content-type lookup instead of one row per kind.
- The Convert section: optional `start`/`end` fields (seconds), parsed and
  passed as overrides, so a trim does not need a new profile.
- A `trim` kind is **not** needed if overrides work: prefer the override.
- Profiles shipped: `jpg`, `webp`, `square-avatar` (a crop, via
  `scale=..:force_original_aspect_ratio=increase,crop=..`).

## Done when

- `Plan` tests cover each format and each override.
- A real conversion test: PNG → JPEG, and a GIF trimmed to 1s is shorter
  than the untrimmed one (compare `output_bytes`).
- The Convert form works with the JavaScript off (a plain form post).
