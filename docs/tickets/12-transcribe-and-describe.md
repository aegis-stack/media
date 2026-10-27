# 12 — Transcribe and describe, through the AI service

**Repo:** `aegis-stack-media`

## Why

"Same job surface, different executable" was the pitch: extracting the
audio and transcribing it is the same user intent as any other conversion.
The AI service already has the providers —
`app/services/ai/domains/voice/stt/providers.py` (`openai_whisper`,
`whisper_local`, `faster_whisper`, groq) and the vision path the documents
service uses for scans. This plugin should not call a model vendor itself.

## Scope

- Profile kinds `transcript` and `describe`:
  - `transcript` runs the existing `audio` plan first (mp3 is accepted by
    every STT provider), then hands the bytes to the AI service's STT
    service on the project's session;
  - `describe` sends a thumbnail-sized frame to the vision reader.
- Results are stored as text next to the bytes: a `text` column on
  `MediaJob` (or an output object with `text/plain` — pick one, pin it).
- Gated: without the `ai` service the job fails with a reason, and the
  profile is hidden from the picker (`when` on the profile — today the page
  lists every profile, so the picker needs a "needs AI" flag).
- No vendor SDK in this plugin's dependencies: the AI service owns them.

## Done when

- A generated stack with `ai` + media transcribes a short generated clip
  (a fixture, no network) and stores the text on the row.
- A stack without `ai` shows the profiles as unavailable, with the reason.
- `patterns check` reports no read outside `queries.py`.
