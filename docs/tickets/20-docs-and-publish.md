# 20 — Docs page and the first PyPI release

**Repo:** `aegis-stack-media`

## Why

The plugin installs from a local path today. Everything about "one place I
know works" assumes it can be installed on a fresh stack on a VPS with one
command, which means a published package and a page that says what it does.

## Scope

- Plugin docs: `docs/` in this repo rendered on aegis-stack.io/plugins
  (front matter, screenshots of the three sections, the profile reference
  from 17), plus a `docs_path` in the spec once the page exists.
- `docs/plugins/publishing.md`'s flow: build, `twine check`, TestPyPI,
  then the real package under the `aegis-stack-plugin` keyword so the
  directory lists it.
- `CHANGELOG.md` per release; 0.1.0's entry written from what shipped.
- A first-run walkthrough that a stranger can follow: `aegis init` with
  storage+worker+htmx, `aegis add media`, the page, a conversion, the link.

## Done when

- `uv add aegis-stack-media` on a fresh stack and `aegis add media` works
  with no local path and no manual `pip install`.
- The docs page renders and links back to this repo.
- Publishing instructions and the version bump are in the repo, not in a
  chat.
