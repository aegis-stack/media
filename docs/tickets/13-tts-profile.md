# 13 — A TTS profile, and audio that is not a conversion

**Repo:** `aegis-stack-media`

## Why

Text-to-speech is the one verb that takes **text** in rather than a file.
It belongs on the same surface because the result is the same: bytes in the
bucket and a row with a link — which is what the face page tests for
Illiana need.

## Scope

- A `speak` action (not a profile kind) on the Convert section: a textarea,
  a voice picker from the AI service's TTS voices, and the same job row.
- `MediaJob.source_key` becomes nullable for this action (no source
  object); `source_bytes` 0; the text is kept in a `text` column (see 12) so
  the job can be re-run without the person retyping it.
- Uses the AI service's TTS; refuses with a reason when there is no `ai`.
- Migration: `source_key` nullable, `text` added — one revision, both paths
  (Postgres and SQLite) exercised.

## Done when

- "Speak" produces an MP3 row with a link from the page and from the CLI
  (`media speak "..." --voice ...`).
- A project without `ai` does not render the textarea.
- The migration applies to an existing project with rows in it.

## Depends on

12 for the `text` column and the AI-service seam; the column can land first
if 12 is split.
