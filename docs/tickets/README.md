# Tickets

What has shipped is in the [README](../../README.md). The framework
tickets this plugin needed (tracker lbedner/aegis-stack#1872) are closed.

What is left, each with what "done" means.

## Verbs and services

| # | Ticket | Depends on |
|---|---|---|
| 10 | [The remaining verbs: WebP out, quality, height, a crop](10-remaining-verbs.md) | - |
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
| 22 | [The agent's tool takes a trim and a size cap](22-agent-surface.md) | - |
