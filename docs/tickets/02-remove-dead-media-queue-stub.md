# 02 — Delete the dead `media` queue stub from the template

**Filed:** [lbedner/aegis-stack#1869](https://github.com/lbedner/aegis-stack/issues/1869) - tracker #1872

**Repo:** `aegis-stack` (framework)

## Why

`aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/worker/queues/media.py`
ships in every **arq** stack: a `WorkerSettings` with `functions = []` and
the tasks commented out, `QueueName.MEDIA` in `app/core/constants.py`, and
no container — compose renders `worker-<queue>` only for **plugin**-declared
queues (`docker-compose.yml.jinja` iterates `_plugins`). So the stub is a
process configuration that never runs, and a name a plugin cannot own
cleanly.

`aegis-stack-media` renders its own `media.py` over it, which works but
means `aegis add` reports "Replaced 1 locally-modified file(s)" for a file
the user never touched, and `aegis remove` deletes a file the framework
generated.

## Scope

- Remove `queues/media.py` from the template and `QueueName.MEDIA` from
  `app/core/constants.py` (check `queue_workers.py`'s docstring example and
  any test that enumerates the shipped queues).
- `docs/components/worker.md`: the queue list if it names media.
- A generation test that no stack ships a queue module with no tasks.

## Done when

- A fresh arq+worker stack has `queues/system.py` and `queues/load_test.py`
  and no `media.py`.
- `aegis add media` into that stack renders its own queue with no
  "locally-modified" notice.
