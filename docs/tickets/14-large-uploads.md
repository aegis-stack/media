# 14 — Large uploads: presigned PUT, drag and drop, progress

**Repo:** `aegis-stack-media`

## Why

`POST /partials/overseer/media/convert` reads the file into memory and caps
it at 200 MB (`MAX_UPLOAD_BYTES`). That is honest for a phone clip and
wrong for a screen recording: the bytes cross the webserver twice (in, then
into the bucket), and the worker's memory is the limit.

`app/core/storage.py` already offers `presigned_url(key)`; the S3 backend
can sign a PUT too, which is how the browser should send the bytes
straight to the bucket.

## Scope

- A presigned **PUT** path (S3 backend only, `FilesystemStorage` keeps the
  form path as the fallback):
  1. the page asks for an upload slot (job row, `status="uploading"`,
     content-addressed key unknown until the bytes arrive);
  2. the browser PUTs the file straight to the bucket, with progress;
  3. the page tells the plugin the upload is done, which verifies
     `exists(key)` and enqueues the conversion.
- A real drop zone: dragover state, paste from the clipboard, the chosen
  file's name and size before submit.
- The content-addressed key means the "slot" cannot know the digest: either
  the bucket's key is derived on completion (`copy` to the content key on
  the server side) or the job stores the temporary key and the row's key is
  rewritten after — pick one and pin it.
- `MAX_UPLOAD_BYTES` becomes the *fallback* path's cap, not the feature's.

## Also in scope: the result side

`adapters/ffmpeg.py` returns the output as `bytes` (`output_path.read_bytes()`),
so a 1 GB result is 1 GB in the worker's memory before it is stored, on top of
the source bytes it read from the bucket. Stream the output into
`ObjectStorage` (a file handle for the filesystem backend, a multipart upload
for S3) and keep only the size and the key in memory. The 200 MB cap protects
the input path; nothing protects this one.

## Done when

- A 500 MB file converts on a stack with S3, with the webserver's
  memory flat during the upload.
- Killing the tab mid-upload leaves a row `uploading` that the page offers
  to discard (not a job stuck forever).
- The filesystem backend still works for a small file.
