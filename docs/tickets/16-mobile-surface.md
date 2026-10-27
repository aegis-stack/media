# 16 — The page from a phone

**Repo:** `aegis-stack-media`

## Why

"I can use it from anywhere" is the point of putting it on a VPS. The
sections render at phone width today (the Overseer shell has a mobile
header and rail), but the one thing done on a phone — pick a video, get a
GIF — is exactly the thing the form does worst: a native file picker, a
150-character profile description in a `<select>`, and no feedback until
the redirect.

## Scope

- Convert, at phone width: one column, the profile picker as a list of
  cards (name + "under 5 MB"), the chosen file shown with its size, a
  progress state while 14 lands.
- The results table collapses to rows (profile, status, link) instead of
  scrolling sideways; the "Open" link is the row's primary target.
- iOS/Android share sheet reachability: the page is installed from the
  browser, so the Convert route accepts `POST` from a share shortcut
  (multipart, no JS) — the form as it is today is the fallback.
- A `media-src` friendly `Content-Type` on the presigned link (the bucket
  owns it; document the requirement).

## Done when

- Convert and Results are usable at 390 px wide with no horizontal scroll
  (a Playwright screenshot test in `tests/web`).
- The no-JS form path still works.
- Uploading from an iPhone produces a job and a playable link.

## Depends on

14 for the upload path a big phone video needs.
