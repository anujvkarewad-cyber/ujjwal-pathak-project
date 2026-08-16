# Codespaces — mentor dashboard chalane ka tarika

Yeh repo ek GitHub Codespace me **do commands** se poora chal jata hai: FastAPI
mentor backend (port **8010**) + React mentor dashboard (port **3000**), aur
backend me **94 chapters ka real generated content** (30 plain MCQ + 5 scenario
× 4 linked MCQ = 50 questions per chapter) auto-import ho jata hai. Saara
`SEED_DEMO` wala DEMO data import ke waqt delete ho jata hai.

---

## 1. Codespace kholna

GitHub repo → **Code ▾ → Codespaces → Create codespace on
`arena/01a00b42-ujjwal-pathak-project`**.

Pehli baar container ban-ne me ~3–5 min lagte hain. `.devcontainer/devcontainer.json`
ka `postCreateCommand` ye sab khud kar deta hai:

| Step | Kya install hota hai |
|------|----------------------|
| Python venv `.venv` | `backend/requirements-dev.txt` (FastAPI, uvicorn, motor, mongomock-motor, pytest …) |
| `frontend/` | `npm ci` (CRA + craco + Radix UI) |
| `content-pipeline/` | `npm install` (optional) |
| Sibling repo | `student-dashboard-frontend` best-effort clone (generated JSON ka source) |

Terminal me `✅ setup complete` dikhe to aage badho.

---

## 2. Ye 2 commands chalao

```bash
# Terminal 1 — backend (port 8010): content import + API
./run-backend.sh

# Terminal 2 — frontend (port 3000): mentor dashboard
./run-frontend.sh
```

Bas itna hi. Backend start hote hi console me ye dikhega:

```
[run-backend] generated content : /workspaces/student-dashboard-frontend/content-pipeline/generated
[import] json files     : 94 (catalog: 94 chapters)
[import] demo records deleted: 112 {...}
[import] chapters: 94 | questions +4700 ~0 =0 | scenarios +470 ~0 =0
INFO:     Uvicorn running on http://0.0.0.0:8010
```

---

## 3. Kaunsa URL kholna hai

Codespaces me **PORTS** tab kholo → port **3000** ke aage globe icon (Open in
Browser) dabao. URL aisa hoga:

```
https://<codespace-name>-3000.app.github.dev
```

Mentor ke liye seedha kaam ke pages:

| Page | Path | Kya milta hai |
|------|------|----------------|
| **Review queue** | `/ai-content/queue` | 4,700 questions, filters: subject / chapter / type / difficulty / status |
| Question review | `/ai-content/questions` | Prompt, 4 options, correct answer, explanation, edit + approve / reject / changes |
| Scenario review | `/ai-content/scenarios` | Passage + 4 linked MCQs, poora block ek saath approve |
| Chapter coverage | `/ai-content/coverage` | 30 / 5 / 20 target vs approved, chapter publish gate |
| References | `/ai-content/references` | ICAI module + RTP/MTP/PYQ calibration refs |
| Audit history | `/ai-content/audit` | Kisne kya approve/reject kiya, kab |
| Analytics | `/analytics` | Student mastery bands (consent ke saath) |

Backend khud dekhna ho to port **8010** → `/docs` (Swagger) ya
`/api/content/queue?limit=5`.

---

## 4. Mentor kaise access karega

- **Codespace me (dev):** `run-backend.sh` `DEV_AUTH_BYPASS=1` set karta hai,
  isliye login screen nahi aata — dashboard seedha khulta hai. Yeh sirf local /
  Codespaces dev ke liye hai.
- **Doosre mentor ko dikhana hai?** PORTS tab me port **3000** pe right-click →
  *Port Visibility* → **Public** → link share kar do. (Port 8010 public karne ki
  zarurat nahi — frontend `/api` ko apne dev-server proxy se 8010 pe bhejta hai.)
- **Production / real deployment:** `DEV_AUTH_BYPASS` hata do aur
  `MENTOR_EMAIL` + `MENTOR_PASSWORD_HASH` set karo (`backend/.env`), phir mentor
  JWT login (`POST /api/auth/login`) se aayega. Hash banane ke liye:
  ```bash
  .venv/bin/python -c "from passlib.context import CryptContext; \
      print(CryptContext(schemes=['bcrypt']).hash('your-password'))"
  ```

---

## 5. Content import ke details

Script: **`backend/import_original.py`**

- **Source:** `../student-dashboard-frontend/content-pipeline/generated/**/*.json`
  (auto-detect: sibling folder → `/workspaces` → `$HOME` → `/app` → is repo ka
  `content-pipeline/generated`; override `GENERATED_DIR=`)
- **Mapping (source → backend document):**

  | Source | Backend |
  |--------|---------|
  | `plain[30]` | `content_questions`, `questionType: "mcq"`, `scenario: null` |
  | `scenarios[5].linkedMcqs[4]` | `content_questions`, `questionType: "scenario_mcq"` + `scenario: {scenarioId, seq, blockTotal: 4}` |
  | `scenarios[5].passage` | `content_scenarios` doc + `questionIds[4]` |
  | `options: ["…"×4]` | `options: [{id:"A"…"D", text}]` |
  | `answerIndex: 0-3` | `correctOptionId: "A"–"D"` |
  | `difficulty: Easy/Medium/Hard` | `difficulty: easy/moderate/hard` |
  | `conceptTags` / `tags` | `conceptTags` (khali ho to chapter slug) |
  | chapter meta | `content-pipeline/config/chapters.json` (94-chapter ICAI catalog) se `subject/paper/module/chapterNumber/chapterTitle/group` + `catalogMatch` |
  | — | `icaiSourceRefs`, `calibrationRefs`, `generationMeta`, `validation`, `similarity`, `status: "needs_review"`, `statusHistory` (generated → auto_validated → needs_review) |

  IDs: `adp_q_<chapterId>_<nnn>` aur `adp_s_<chapterId>_<nn>` (schema ka `^adp_`
  pattern match karte hain).

- **Refs:** jaha generated JSON me ICAI/calibration ref nahi hota, importer
  chapter-level ref derive karta hai (`derivedAtImport: true`) aur question pe
  warning laga deta hai — *"verify before approval"*. Derive band karna ho:
  `--no-derive-refs`.
- **DEMO cleanup:** `seed_demo.py` ke saare records delete —
  `ch-acc-01` / `ch-law-03` questions + scenarios + chapters, `generationMeta.model = demo-seed`,
  demo students (S-1001…S-1006) ke consent/summaries/trends, demo follow-ups, demo audit rows.
- **Re-run safe:** har question `id` se upsert hota hai. Jo content badla nahi
  usse skip, aur jo mentor already approve/reject/changes-request kar chuka hai
  usse chhua nahi jata (`--force` se override).

Manual chalane ke commands:

```bash
# kaunsi generated dir detect hui
.venv/bin/python backend/import_original.py --print-dir

# sirf convert + validate, DB me kuch mat likho
.venv/bin/python backend/import_original.py --dry-run

# ek hi chapter
.venv/bin/python backend/import_original.py --chapter advanced-accounting-1

# JSON report
.venv/bin/python backend/import_original.py --json
```

> **Note:** default `MONGO_URL=memory://` (koi MongoDB server nahi chahiye), aur
> yeh store process ke andar rehta hai — isiliye `run-backend.sh` import ko
> server ke **usi process** me startup pe chalata hai (`IMPORT_GENERATED=1`).
> Data permanently rakhna ho to `MONGO_URL=mongodb://…` set karke
> `./run-backend.sh` chalao; phir standalone import command bhi persist karega.

---

## 6. Env knobs

| Variable | Default | Kaam |
|----------|---------|------|
| `PORT` | 8010 / 3000 | server port |
| `MONGO_URL` | `memory://` | `mongodb://…` do to real Mongo |
| `DEV_AUTH_BYPASS` | `1` | 0 karo to JWT login zaroori |
| `GENERATED_DIR` | auto-detect | generated JSON folder |
| `IMPORT_GENERATED` | `1` | 0 karo to import skip |
| `KEEP_DEMO` | unset | `1` → DEMO records delete mat karo |
| `IMPORT_FORCE` | unset | `1` → mentor-touched docs bhi overwrite |
| `SEED_DEMO` | unset | `1` → purana demo data seed (dev only) |
| `REACT_APP_MENTOR_API_URL` | Codespaces me `same-origin`, warna `http://localhost:8010` | dashboard kis API se baat kare |
| `MENTOR_API_PROXY_TARGET` | `http://localhost:8010` | CRA dev-server `/api` proxy target |

`REACT_APP_MENTOR_API_URL` ki values: `""` = mock data, `same-origin` (ya
`proxy`) = dev-server proxy / same-origin deployment, ya poora URL
(`http://localhost:8010`). Codespaces browser me `localhost:8010` reachable
nahi hota, isliye script wahan khud `same-origin` chun leti hai.

---

## 7. Troubleshooting

| Problem | Fix |
|---------|-----|
| `[run-backend] WARNING: no generated content found` | `student-dashboard-frontend` repo clone karo repo ke bagal me, ya `GENERATED_DIR=/path/... ./run-backend.sh` |
| Queue khali / mock data dikh raha | Frontend ko backend mila nahi — dekho `run-frontend.sh` ka log line "mentor API"; backend port 8010 chal raha hai? `curl localhost:8010/api/content/chapters` |
| Port 3000 pe 401 / login screen | `DEV_AUTH_BYPASS=1 ./run-backend.sh` |
| Codespace restart ke baad content gayab | `memory://` store process ke saath jata hai — bas `./run-backend.sh` dubara chala do (import ~15 sec) |
| Tests | `cd backend && ../.venv/bin/python -m pytest -q` (36 + 5 import tests) |
