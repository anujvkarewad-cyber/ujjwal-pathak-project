# MCQ Generation — Step-by-Step Guide

Run these on a machine that can reach **googleapis.com** and your AI provider
(the sandbox where this was built blocks Google, so Drive sync runs from your
laptop/server — the pipeline itself is plain Node.js, no other dependencies).

## 1 · One-time setup

1. **Service account key**
   Google Cloud → enable Drive API → IAM → Service Accounts → Create → Key (JSON).
   Save as `content-pipeline/secrets/service-account.json` (gitignored).

2. **Share the Drive folders** with the service-account email as **Viewer**:
   - Modules folder → `DRIVE_FOLDER_MODULES`
   - RTP / MTP / PYQ folders → their variables (optional at first — see note)

3. **`.env`** — copy values from `.env.example` (the real `.env` is gitignored):
   ```
   OPENAI_API_KEY=sk-…
   MONGO_URL=memory://          # or a real MongoDB URL
   MEMORY_DB_FILE=state/dev-db.json   # persists the review queue locally
   STUDENT_REPO_PATH=/path/to/student-dashboard-frontend
   ```

4. `npm install`

> **Note on calibration folders:** RTP/MTP/PYQ folders can be added later.
> Without them, ingestion still works, but generated questions lack calibration
> refs and **content validation (stage-7) will block them** until the folders
> are configured and the chapter is regenerated. Modules are mandatory.

## 2 · Ingest sources (stages 0–4)

```bash
npm run ingest
```

What happens: catalog authority check (94 chapters) → Drive download + cache →
PDF/DOCX extraction → chapter segmentation → mapping.

Then read `state/mapping.json`:
- chapters with `"blocked": false` are ready for generation
- `"blocked": true` chapters list the missing module source — fix the Drive
  folders first (the pipeline will never guess)

## 3 · Generate (stage 5) — start small

```bash
# cost estimate, no AI calls
npm run stage:generate -- --dry-run

# one chapter first, review the quality
npm run stage:generate -- --chapter=advanced-accounting-1

# then the rest (resumable — failed chapters can be rerun individually)
npm run stage:generate
```

Each chapter = 30 plain MCQs + 5 scenarios × 4 linked MCQs. Rough cost:
≈35–40 AI calls per chapter → ~3,500 calls for 94 chapters (a few hundred
rupees per chapter with mid-tier models; measure one chapter first).

## 4 · Validate (stages 6–9)

```bash
npm run stage:validate-schema
npm run stage:validate-content
npm run stage:duplicates
npm run stage:coverage
```

Items with errors or similarity blocks are excluded automatically.
Reports: `state/content-validation.json`, `state/similarity.json`, `state/coverage.json`.

## 5 · Stage to the mentor review queue (stage 10)

```bash
npm run stage:stage
```

Questions now appear in the mentor dashboard → **AI Content → Review Queue**.

## 6 · Mentor review & publish (backend + dashboard)

1. Start the backend (see `backend/.env.example`): `python -m dev_server`
2. Review/edit/approve in the dashboard.
3. A chapter is publishable only when 30 plain + 5 scenarios + 20 linked MCQs
   are all approved with no blocking errors.
4. Publish (gated — refuses drafts):

```bash
npm run stage:publish -- --chapter=advanced-accounting-1
npm run stage:verify
```

Bundles land in `content-pipeline/dist/` and are served to students by the
backend at `/api/content/student/*`. Daily MCQ data is never touched.

## Troubleshooting

| Problem | Fix |
|---|---|
| stage-1 fails on credentials | `secrets/service-account.json` missing, or the folder isn't shared with the SA email |
| A chapter is BLOCKED in mapping | Its module PDF isn't in the Modules folder (or the file failed extraction — see `state/extraction.json`) |
| stage-5 fails on API key | Set `OPENAI_API_KEY` in `.env` |
| stage-8 blocks items | Too similar to ICAI source text or existing questions — those items are auto-rejected; regenerate with a different prompt seed |
| stage-11 refuses to publish | The chapter gate failed — check `state/` reports and the dashboard's Chapter Coverage gate panel |
