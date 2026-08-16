# RUN — Local + GitHub Actions

Ye doc batata hai kaise pipeline ko **local** aur **GitHub Actions** dono jagah chalana hai.

---

## 1) Local quick start (Windows / Mac / Linux)

### Pre-requisites
- Node.js >= 20 (`node -v`)
- Google Cloud Service Account JSON (Drive API enabled)
- OpenAI API key (ya Anthropic / Gemini)

### Steps

```bash
# 1. Repo clone ke baad
cp .env.example content-pipeline/.env
# ya root me hai to:
cp .env.example .env
# .env edit karo — OPENAI_API_KEY + Drive folder IDs bharo

# 2. Service account key place karo
mkdir -p content-pipeline/secrets
# service-account.json yahan rakho
# Google Drive folders ko us SA email se Viewer share karo

# 3. Install
cd content-pipeline
npm install

# 4. Ingest (catalog → Drive → extract → normalize → map)
npm run ingest
# ya root se:
./run.sh ingest        # Linux/Mac/WSL
run.bat ingest         # Windows

# Mapping report check
cat state/mapping.json | grep blocked

# 5. Generation — dry-run first (cost estimate, no AI calls)
npm run stage:generate -- --dry-run
./run.sh generate -- --dry-run

# One chapter test
npm run stage:generate -- --chapter=advanced-accounting-1
./run.sh generate -- --chapter=advanced-accounting-1

# Full generation (resumable — failed chapters ko individually rerun kar sakte ho)
npm run stage:generate
./run.sh generate

# 6. Validate
npm run stage:validate-schema
npm run stage:validate-content
npm run stage:duplicates
npm run stage:coverage
# ya
./run.sh validate

# 7. Mentor review queue me stage karo
npm run stage:stage
./run.sh stage
# Ab dashboard → AI Content → Review Queue me dikhega (backend chahiye)

# 8. Publish (only after approvals — gate will block drafts)
npm run stage:publish -- --chapter=advanced-accounting-1
npm run stage:verify
./run.sh publish --chapter=advanced-accounting-1

# Bundles: content-pipeline/dist/
```

`run.sh` / `run.bat` kya karta hai:
- Node version check, .env presence check
- `npm install` agar `node_modules` missing
- Saare `stage:*` commands ka wrapper, extra args forward
- `--chapter=ID` aur `--dry-run` dono supported

---

## 2) GitHub Actions

Workflow file: `.github/workflows/generate-mcqs.yml`

### Triggers
- `push` / `pull_request` on `content-pipeline/**` → runs **test job only** (PR-safe)
- `workflow_dispatch` (manual) → runs **full ingest → generate → validate → stage**

### Manual run (GitHub UI se)
1. GitHub repo → Actions tab → `ca-inter-mcq-pipeline` → Run workflow
2. Inputs:
   - **chapter**: e.g. `advanced-accounting-1` (empty = all non-blocked)
   - **dry_run**: ✅ tick karo to sirf cost estimate, no AI calls
   - **stage**: `full` | `ingest-only` | `generate-only` | `validate-only` | `test-only`
   - **openai_model**: override, e.g. `gpt-4o-mini`

### Required GitHub Secrets & Vars

**Secrets** (Settings → Secrets and variables → Actions → Secrets):
| Name | Value | Notes |
|---|---|---|
| `OPENAI_API_KEY` | `sk-proj-...` | Mandatory for generation |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | full JSON content of SA key | Base64 bhi chalega, plain JSON bhi. File `secrets/service-account.json` ban jayegi |
| `ANTHROPIC_API_KEY` (optional) | ... | If using Anthropic |
| `GEMINI_API_KEY` (optional) | ... | If using Gemini |

**Variables** (Settings → Variables):
| Name | Example |
|---|---|
| `DRIVE_FOLDER_MODULES` | Drive folder ID |
| `DRIVE_FOLDER_RTP` | optional |
| `DRIVE_FOLDER_MTP` | optional |
| `DRIVE_FOLDER_PYQ` | optional |
| `OPENAI_MODEL` | `gpt-4o-mini` |
| `AI_PROVIDER` | `openai` |

> Tip: `GOOGLE_SERVICE_ACCOUNT_JSON` ko plain copy-paste karo, workflow khud handle karta hai base64 decode ka fallback.

### Artifacts
Har run ke baad **Artifacts** me milega:
- `state/` → `mapping.json`, `extraction.json`, `content-validation.json`, `similarity.json`, `coverage.json`
- `dist/` → published chapter bundles (agar publish hua)
- `.cache/drive/*.json` → drive file list cache

Retention 14 days.

### Fail-closed behavior (important)
- Agar Service Account secret missing → Stage-1 warning dega, PR jobs fail nahi honge
- Agar `OPENAI_API_KEY` missing → Stage-5 fail karega (expected)
- Agar chapter `BLOCKED` (module PDF nahi mila) → pipeline us chapter ko SKIP karta hai, guess nahi karta
- Publish gate: sirf tabhi pass jab 30 plain + 5 scenarios + 20 linked MCQs approved + no blocking validation errors

### Local vs Actions parity
- Local me `MONGO_URL=memory://` + `MEMORY_DB_FILE=state/dev-db.json` se bina real MongoDB ke review queue chal jata hai
- Actions me bhi same `memory://` default hai
- Backend review ke liye local backend chahiye: `backend/.env.example` dekho, `python -m dev_server`

---

## 3) Common Troubleshooting

| Problem | Fix |
|---|---|
| `stage-1` credentials error | `content-pipeline/secrets/service-account.json` missing ya Drive folder share nahi hai SA email ke saath |
| `BLOCKED` chapter in mapping | Modules folder me us chapter ka PDF nahi hai / extraction fail (`state/extraction.json` dekho) |
| `OPENAI_API_KEY` error | `.env` me key missing, ya GitHub Secret missing |
| Similarity blocks in stage-8 | Question ICAI source se bahut similar — auto-rejected, dobara generate karo (different prompt seed / adjust temp via prompt) |
| Publish refuses | Coverage gate fail — `state/coverage.json` + dashboard Chapter Coverage panel dekho |
| `run.sh: permission denied` | `chmod +x run.sh` |
| Workflow artifact empty | Agar `ingest-only` run kiya to dist empty hoga — `full` run karo ya `generate-only` |

---

## 4) Cost estimate
- Per chapter ≈ 35-40 AI calls (30 plain + 5 scenario)
- 94 chapters ≈ 3500 calls
- Pehle 1 chapter karke measure karo, fir poora chalao

---

## 5) What to upload to GitHub (aap khud karoge)

Zip `ca-inter-mcq-pipeline.zip` me ye included hai:
```
ca-inter-mcq-pipeline/
├── content-pipeline/            # full pipeline source
│   ├── config/chapters.json     # 94 chapters catalog
│   ├── src/                     # stages 0-12 + lib + ai adapters
│   ├── package.json / package-lock.json
│   ├── RUNNING.md               # step-by-step old doc
│   └── ...
├── .github/workflows/generate-mcqs.yml
├── .env.example
├── run.sh
├── run.bat
└── RUN_ACTIONS.md               # ye file
```

Root me ye files rakho, push karo, Actions tab se trigger karo.
