# 10 — The remaining verbs: WebP out, quality, height, a crop

**Repo:** `aegis-stack-media`

## Why

The kinds a project has (`profiles.Kind`) cover a GIF, a video, the audio,
a frame, a thumbnail and a smaller JPEG, and the page trims the first or
last seconds. The conversions still done by hand: a WebP out, a quality
for the lossy formats, a height as the other half of `width`, and a square
crop (an avatar).

## Scope

- `adapters/profiles.py`: `Profile` gains `format` (`png`/`jpeg`/`webp`
  for `image`/`thumbnail`), `quality` for the lossy formats, and `height`;
  each in `FIELDS` for the kinds that take it.
- `domains/recipe.py`: the argv per format; `KINDS` becomes a
  per-(kind, format) suffix/content-type lookup instead of one row per
  kind.
- Profiles shipped: `webp`, `square-avatar` (a crop, via
  `scale=..:force_original_aspect_ratio=increase,crop=..`).

## Done when

- `Plan` tests cover each format.
- A real conversion test: PNG → WebP, and the avatar is square.
- The Convert form works with the JavaScript off (a plain form post).
