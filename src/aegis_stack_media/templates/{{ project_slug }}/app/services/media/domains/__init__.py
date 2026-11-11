"""Converting media: a profile applied to a stored source.

The domains own the recipe (``recipe``), the job's life (``convert``:
queued, running, done or failed) and what it has been doing
(``activity``); the adapters own ffmpeg and the profiles file;
``queries`` owns the reads.
"""
