# 22 — The agent's tool takes a trim and a size cap

**Repo:** `aegis-stack-media`

## Why

"Make me a GIF of this, the last 7 seconds, under 3 MB" should be a job the
agent composes and the person approves. The `media` tool (`tools.py`,
granted with `effect="writes"`) queues a conversion of a stored object
with a profile, and nothing else: no trim, no cap, so the agent can only
ask for what a profile already says.

## Scope

- `media(source, profile, end?)`: the job's own trim, the same
  `MediaJob.end` the page and the CLI set (the first N seconds, or negative
  for the last N), refused on a still by `profiles.checked` as everywhere
  else.
- A per-job size cap (`max_bytes`) and a trim from the middle ("5 to 12
  seconds") need columns on `media_job` first (a migration); until then
  the cap is the profile's and a trim is the first or last seconds.

## Done when

- In a generated project with media and AI: "make me a gif of job 3, the
  last 7 seconds" produces a `MediaJob` row with `end=-7` and a link.
- A trim on a still is refused with the message the page and the CLI give.
- `patterns check` and the project's `test_tools.py` are green.
