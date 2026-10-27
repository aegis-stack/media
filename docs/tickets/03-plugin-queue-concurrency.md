# 03 — A plugin queue's concurrency is declarable

**Filed:** [lbedner/aegis-stack#1870](https://github.com/lbedner/aegis-stack/issues/1870) - tracker #1872

**Repo:** `aegis-stack` (framework)

## Why

`WORKER_QUEUES` defaults live in `app/core/queue_workers.py`
(`DEFAULT_QUEUES`), and a queue not listed gets `WORKER_QUEUE_DEFAULT`
(concurrency **10**). For `media` that is ten simultaneous ffmpeg runs on
one box — the fastest way to make a VPS unresponsive.

A project can override it (`WORKER_QUEUES='{"media": {"concurrency": 2}}'`),
but a plugin cannot ship that default, so every install starts wrong.

## Scope

- One of:
  - `PluginSpec.worker_queues` becomes `list[str | WorkerQueueDefault]`
    (`name`, `concurrency`, `max_wait_seconds`), rendered into
    `DEFAULT_QUEUES`; or
  - the plugin's own compose block (`worker_<queue>`) carries
    `WORKER_QUEUES` in its environment, which needs no shared-file edit.
- The `media` plugin then declares concurrency 2 (one conversion per core is
  what ffmpeg wants; a second slot for a small resize is fine).

## Done when

- A stack with the plugin runs `worker-media` with the declared concurrency,
  visible on Overseer > Worker.
- An explicit `WORKER_QUEUES` env still wins over the plugin's default.
