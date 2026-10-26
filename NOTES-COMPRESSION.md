# Mentor notes compression — local implementation

**19 October 2026 · Built and tested locally · NOT deployed**

Scope confirmed by owner: **mentor notes only**. WhatsApp work is deferred. Student proofs, answer sheets, existing published files, Drive Inbox publishing, student web/Android source code, scoring and accounts are unchanged.

## New upload experience

1. Select PDFs or a folder using the existing Notes page.
2. Choose **Balanced** (default) or **Original**.
3. Balanced: click **Prepare PDFs**. This does **not** publish a note, write to Drive/Sheets/Mongo or send a notification.
4. Review each file's original → selected size, reduction percentage, original preview and optimized preview. Use **“Use original for this file”** for diagrams/small text when preferred.
5. Click the existing **Upload** action. The selected bytes go through the existing chunk uploader with the same filename, title, audience, group and subject metadata. A successful-upload summary retains the original and uploaded sizes.

Original mode bypasses the preparation service completely. If the service is unavailable, a PDF is encrypted/form-bearing/signed, or optimization is not beneficial, the local original is retained with a visible explanation. Auth failures stop preparation instead of being silently treated as a successful fallback. Balanced uploads remain locked until preparation completes for the current file selection.

The existing uploader is **PDF-only**; standalone JPEG/PNG uploads have not been introduced. Images embedded in scanned PDFs are supported conservatively.

## Compression and document safety

- Uses pikepdf/qpdf stream compression and object packing; no Ghostscript or whole-page rasterization.
- Eligible 8-bit RGB/grayscale image XObjects may be re-encoded at JPEG quality 90, without resizing, reducing resolution or changing page geometry.
- Small diagrams, CMYK/indexed images, masks, transparency and unsupported image filters are not lossily re-encoded.
- Text and page drawing streams remain unchanged. Reopened output is checked for page geometry, drawing-stream hashes and link attributes.
- Tests also verify searchable text with an independent parser, internal links, bookmarks and document title metadata.
- Encrypted PDFs, forms and signature indicators retain the exact original bytes. This is **compression, not PDF sanitization or a guarantee of perfect visual quality**.
- Output must save at least **3% and 1 KB**; otherwise the original is selected. Individual images must also meet a meaningful saving threshold.
- Originals are never overwritten. A mentor should review a representative small-text/formula page before publishing.

## Bounds, privacy and permissions

`POST /api/mentor/notes/prepare?quality=balanced|original`

- Uses the existing mentor authentication dependency; no new auth bypass or public upload endpoint.
- Raw `application/pdf` body, at most 20 MB; actual streamed bytes are capped even without Content-Length.
- One preparation slot per server process; busy requests receive 429.
- Transfer deadline: 60 seconds. Isolated worker wall timeout: 25 seconds; CPU limit: 20 seconds; Linux address-space cap: 384 MiB; output-file cap: 64 MiB.
- Optimization limit: 400 pages, 12 million pixels per eligible image, 40 million eligible pixels per PDF.
- Browser preparation batch capped at 25 files / 100 MB to bound retained previews. Original mode keeps the existing upload behavior.
- Temporary files are in a private temporary directory and removed after success/failure. Worker stdout/stderr are discarded; PDF content and exception details are not logged.
- PDF responses use `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`; preview object URLs are revoked when removed/unmounted.

## Important bandwidth trade-off

The current publisher uses Apps Script chunk uploads. Therefore server preparation first transfers the original PDF to the backend, returns the selected PDF to the browser for review, and then the browser uploads those selected bytes through the existing publisher.

**This reduces the stored PDF and student download size, and often final chunk count. It does not guarantee lower total mentor bandwidth or faster end-to-end upload.** No change to the existing publisher or student download URLs is required.

## Verification

- **26 backend compression checks passed**, including a real bounded worker, auth protection, stream limits, timeout/failure cleanup, byte-identical fallback, text, links/bookmarks, image dimensions and metadata.
- **22 frontend checks passed**, including actual Notes component interaction tests: preparation never publishes, selected compressed bytes reach the existing uploader, original overrides work, authentication failure keeps Upload locked, and stale-file results cannot be reused.
- Full offline backend comparison on the same dependency environment and complete content fixtures: baseline **383 passed / 1 failed** → after **409 passed / 1 failed**. The unchanged failure is `test_student_content::test_bank_json_only_serves_published` (cache-control expectation). This is not a fully green suite, nor a claim that older unrelated intermittent failures were fixed.
- Frontend production build succeeded. Existing unrelated lint warning remains in `McqScores.jsx` (`reloadKey` dependency).
- Synthetic scan fixture: **3,241,106 → 94,303 bytes (97.09% reduction)**, while retaining searchable text and links. This intentionally uncompressed fixture is **not a prediction of real-note savings**; already optimized PDFs may remain unchanged.
- No real mentor PDF or phone PDF-viewer acceptance test has been performed yet. No live Drive upload, publication or push was performed.

Tested libraries: pikepdf 10.17.0, Pillow 12.3.0; verification-only pypdf 6.21.1. Runtime dependencies are declared in `backend/requirements.txt`, test dependencies in `backend/requirements-dev.txt`.

## Files and operational notes

- Backend: `note_pdf_optimizer.py`, `note_pdf_worker.py`, `routers/note_compression.py`; route registered in `server.py`.
- Frontend: `api/notePreparation.js`, `components/notes/NotesPreparation.jsx`, Notes page integration; chunk progress now accounts for base64 padding accurately.
- Jest's `@` alias now matches the existing webpack alias for component testing.
- Tests: `backend/tests/test_note_compression.py`, `frontend/src/api/notePreparation.test.js`, `frontend/src/pages/Notes.compression.test.jsx`.
- Workspace evidence: `/home/user/notes-compression/evidence/`.

Before rollout: test representative real PDFs (scans, formulas, colour diagrams and already-compressed files), preview on actual Android/web PDF viewers, load-test memory against the target Cloud Run configuration, and confirm authenticated preparation + existing final publish in staging. The final publisher retains its existing publication/notification behavior; testing that live requires explicit permission.

**Production deploy, data-changing operation or student-facing message still requires explicit approval.** No APK is needed for students to read the resulting standard PDFs. If a future student APK is separately built, the standing true-OTA requirement still applies.

## Rollback

The notes-only patch is based on local commit `48931df4d646f19022175ab7ba30e5069f8ac667`. Revert its separate feature commit to remove this preparation flow; existing stored notes and uploaded original files are unaffected. Do not replace the entire backend with the archived baseline. Earlier local MCQ/Sheet Source changes remain separate and are not activated or deployed by this work.
