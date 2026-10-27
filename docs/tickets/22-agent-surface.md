# 22 — Illiana composes a conversion: `tools.py` and its grant

**Filed:** [lbedner/aegis-stack#1868](https://github.com/lbedner/aegis-stack/issues/1868) - tracker #1872

**Repo:** `aegis-stack-media` · **Depends on:** framework ticket 01

## Why

The second interface in the pitch: "make me a GIF of this from 0:05 to
0:12 under 5 MB" should be a job spec the agent composes, and the person
approves. That needs a tool the agent can call, granted and visible, and
it needs the size/trim overrides ticket 10 adds to the profile.

0.1.0 ships no `tools.py` on purpose (see 01): a registered tool the
project's own test suite rejects is worse than none.

## Scope

Once 01 lands:

- `app/services/media/tools.py`: one `register_tool("media", effect="writes")`
  taking `{source: storage key, profile: str, start?: float, end?: float,
  max_bytes?: int}` and returning `{id, status, profile}` — figures, never
  rows (the `figures.py` rule).
- The tool creates the row and calls `start_conversion`; it does **not**
  hold the request open for the conversion.
- Named in the agent's map (`app/core/ontology/summary.py`) and the prompt
  so Illiana knows the profiles by name rather than guessing.
- `EXPECTED_EFFECTS` / the plugin grant from 01 covers it; the Overview
  shows the tool as the agent's way in.

## Done when

- In a generated project with media and AI: "make me a gif of job 3, 5 to
  12 seconds, under 3 MB" produces a `MediaJob` row whose profile is the
  base profile plus the overrides, and a link.
- The tool refuses an unknown profile with the list of known ones (the
  agent should not have to guess).
- `patterns check` and the project's `test_tools.py` are green.
