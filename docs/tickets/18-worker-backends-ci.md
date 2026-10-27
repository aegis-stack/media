# 18 — CI covers TaskIQ and Dramatiq stacks

**Repo:** `aegis-stack-media`

## Why

The queue module has three branches and only arq has ever run: the machine
that generated the test stack defaults to arq. A branch that does not import
is a stack where every conversion is queued to nothing — and
`test_media_jobs.py` only pins the task's name, not that the branch
imports.

## Scope

- `.github/workflows/test.yml`: a matrix over `arq`, `taskiq`, `dramatiq`:
  generate a stack (`aegis init --dev -c worker,storage,htmx -c ...` with
  the backend flag), `aegis add media`, run the media tests, then enqueue
  one conversion and wait for the row to leave `queued`.
- The task name (`convert_media_task`) stays the contract between
  `jobs.start_conversion` and every branch: a test per backend that imports
  the module and asserts the function exists.
- A Redis service container for the enqueue/consume step.

## Done when

- All three backends are green in CI.
- A deliberately renamed task in one branch fails a test in that branch.
- The workflow documents how to run one backend locally.
