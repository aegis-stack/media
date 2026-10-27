# 19 — Retention, activity events and figures

**Repo:** `aegis-stack-media`

## Why

Nothing ever deletes a result, so the bucket only grows; nothing shows on
Overseer's activity feed, so a conversion is invisible unless you open the
Media page; and the plugin declares no aggregates, so an agent (or the
Overview) cannot say what the project's media adds up to beyond the counts
it computes itself.

## Scope

- A `scheduled_jobs.py` with `JOBS`: delete objects (and flip the rows to
  `expired`) older than `MEDIA_RETENTION_DAYS` (default: never — a project
  opts in), in batches, never in a request.
- `add_event(component="media", event_type="convert", ...)` on completion
  and on failure, as every in-tree service does.
- `aggregates.py` with `AGGREGATES`: jobs, done, failed, bytes stored, the
  busiest profile — figures only, frozen models, read by `aggregate`.
- The Overview's figures read from the same place as the aggregate (one
  home, `queries.totals`).

## Done when

- A retention run deletes only what it should (an object still referenced by
  a `done` row inside the window survives).
- The activity feed shows a conversion.
- `aggregate` returns the plugin's figures in a generated project with
  media installed, and `patterns check` shows no new findings.
