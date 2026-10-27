# 15 — A JSON API for other clients

**Repo:** `aegis-stack-media`

## Why

The page and the CLI are enough for the person at the desk. A phone
shortcut, a `curl` from another machine, or a browser extension needs a
stable HTTP surface that is not an htmx partial, and it makes the plugin
usable from a script without importing `app`.

## Scope

- `app/components/backend/api/media/router.py`, mounted via
  `wiring.routers` at `/api/v1/media`:
  - `POST /jobs` — submit by **storage key** (the file is already in the
    bucket, which is the normal case for another service) or multipart;
    returns `{id, status}`;
  - `GET /jobs/{id}` — the row: profile, status, sizes, `result_url`
    (presigned), `error`;
  - `GET /jobs` — recent, paged by `before_id`;
  - `GET /profiles` — name, kind, description.
- Auth: the project's standard API auth (whatever `route_requires_auth`
  expects for a service router), not the Overseer gate.
- Schemas in `app/services/media/schemas.py` (frozen, `extra="forbid"`);
  the route stays thin (the `route.thin` pattern).
- `docs/` in the plugin repo: the four calls with request/response shapes.

## Done when

- `curl` submits a stored key and follows the job to `done` with a working
  link.
- `patterns check` reports no new `route.*` findings for the new router.
- The page uses the service layer, not the API (no htmx calling its own
  JSON).
