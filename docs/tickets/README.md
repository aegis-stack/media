# Tickets

The plugin's 0.1.0 slice is in: profiles as data, one conversion pipeline
(gif, image, audio, thumbnail, video), the media queue on three worker
backends, the Overseer page (Overview / Convert / Results), the CLI, and
the tests that hold the layout and the policy.

What is left, each with what "done" means. Framework tickets are work in
`aegis-stack` itself and block a plugin-only ticket where noted.

## Framework (`aegis-stack`)

Filed as one batch: **tracker #1872**, shared label `plugin-system`.

| # | GitHub |
|---|---|
| 01 | #1868 |
| 02 | #1869 |
| 03 | #1870 |
| 04 | #1871 |
| -- | #1873 deploy+database without scheduler breaks `app.services.system` (found by this plugin's verification) |


| # | Ticket | Blocks |
|---|---|---|
| 01 | [A plugin's tools can be granted, and declare their effect](01-plugin-tool-grants.md) | 22 |
| 02 | [Delete the dead `media` queue stub from the template](02-remove-dead-media-queue-stub.md) | - |
| 03 | [A plugin queue's concurrency is declarable](03-plugin-queue-concurrency.md) | - |
| 04 | [Plugins must be able to change the container image](04-plugin-dockerfile-hook.md) | - |

## Verbs and services

| # | Ticket | Depends on |
|---|---|---|
| 10 | [The remaining verbs: image formats, resize, trim in the UI](10-remaining-verbs.md) | - |
| 11 | [PDF to images, by delegating to the documents service](11-pdf-to-images.md) | - |
| 12 | [Transcribe and describe, through the AI service](12-transcribe-and-describe.md) | - |
| 13 | [A TTS profile, and audio that is not a conversion](13-tts-profile.md) | 12 |

## Surface

| # | Ticket | Depends on |
|---|---|---|
| 14 | [Large uploads: presigned PUT, drag and drop, progress](14-large-uploads.md) | - |
| 15 | [A JSON API for other clients](15-json-api.md) | - |
| 16 | [The page from a phone](16-mobile-surface.md) | 14 |
| 17 | [A profile library, and `media profiles --check`](17-profile-library.md) | - |
| 23 | [Pillow for the image pipeline (decision + design)](23-pillow-image-path.md) | - |

## Operations

| # | Ticket | Depends on |
|---|---|---|
| 18 | [CI covers TaskIQ and Dramatiq stacks](18-worker-backends-ci.md) | - |
| 19 | [Retention, activity events and figures](19-retention-and-events.md) | - |
| 20 | [Docs page and the first PyPI release](20-docs-and-publish.md) | - |

## Agent

| # | Ticket | Depends on |
|---|---|---|
| 22 | [Illiana composes a conversion: `tools.py` and its grant](22-agent-surface.md) | 01 |
