# 17 — A profile library, and `media profiles --check`

**Repo:** `aegis-stack-media`

## Why

Six profiles ship; a project that uses this thing daily will write its own,
and today the only feedback on a new one is the first conversion that goes
wrong. The pitch's line — "profiles as data" — is only half true until the
data can be checked without running a job, and until there are more than
the six.

## Scope

- `media profiles --check` (and a button on the Overview): every profile,
  its plan rendered as argv (dry run, no process), and the fields that are
  ignored for its kind (`max_bytes` on an `audio` profile is a mistake, say
  so).
- A library of documented profiles worth shipping: `readme-gif`, `web-gif`,
  `social-square`, `story-vertical`, `podcast-mp3`, `waveform-preview`
  (a GIF of a waveform is the one people ask for), `thumb-grid`.
- `docs/profiles.md`: every field, per kind, with one example — the page a
  project reads before writing its own.
- The Overview lists the profiles with the command to check them.

## Done when

- A profile with a meaningless key for its kind is reported by `--check`.
- Every shipped profile is converted once in a test (a fixture per kind).
- `docs/profiles.md` is generated from the model's fields, or pinned to
  them by a test (the docs cannot drift).
