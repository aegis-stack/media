# 11 — PDF to images, by delegating to the documents service

**Repo:** `aegis-stack-media`

## Why

"PDF to images" is on the list, and the framework already has the engine:
`app/services/documents/domains/extraction/pdf.py` (`PdfPages`,
`render_png`) and `pages.py`, which store page PNGs through
`app.core.storage`. A second PDF renderer in this plugin would be a
duplicate — precisely the defect `plan-framework-change` exists to prevent.

## Scope

- A profile kind `pdf-pages` (and `pdf-thumbnail`), which:
  - uses `documents.domains.extraction.pdf` **when the documents service is
    installed** (import guarded; the plugin's `required_services` must stay
    empty so a project can have media without documents);
  - otherwise fails the job with a clear reason ("install the documents
    service") rather than shipping a second renderer or a silent no-op.
- Output: one object per page under the job, plus a `MediaJob` row per page
  (or a `children` count on the row — decide and pin it in a test; the
  Results table then shows "12 pages" with a link to the first).
- `max_pages` cap in the profile, refused above it before rendering.

## Done when

- A PDF with a text layer and a scan both convert (one page each is enough).
- A project without `documents` gets the clear refusal, not an ImportError.
- No `pypdfium2` import in this plugin.
