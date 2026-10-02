# Koyeb migration (replaces the disabled Vercel deployment)

**Why:** the Vercel deployment started answering every request with
`HTTP 402 … DEPLOYMENT_DISABLED` (account/plan level — nothing in this repo
can fix it). Koyeb runs the FastAPI app as a real long-running container,
which this backend needs anyway (startup import, in-process store,
background persistence).

One container serves everything:

| Path     | Served by                                                |
|----------|----------------------------------------------------------|
| `/api/*` | FastAPI (mentor + student APIs)                           |
| `/*`     | the CRA mentor SPA, built into the image, same-origin API |

Files: [`Dockerfile`](../Dockerfile) (repo root), [`.dockerignore`](../.dockerignore).

---

## 1. Create the Koyeb service

1. <https://app.koyeb.com> → **Create Service** → **GitHub**.
2. Repository `anujvkarewad-cyber/ujjwal-pathak-project`, branch `main`
   (deploy from this PR's branch first if you want to verify before merge).
3. **Builder: Dockerfile** — Dockerfile location `./Dockerfile`,
   work directory = repository root. *(Do not pick Buildpack; the Dockerfile
   builds the SPA too.)*
4. **Instance:** Free / `nano` is enough to start. **Regions:** `fra` or `sin`
   (Singapore is closest to India).
5. **Exposed port:** `8000`, protocol HTTP, path `/`.
   Koyeb injects `$PORT`; the image honours it.
6. **Health check:** HTTP, port `8000`, path `/api/health`,
   grace period ≈ 60 s (first boot imports content).
7. **Scaling:** min 1 instance — keep it from scaling to zero, otherwise the
   first student login after an idle period waits for a cold start.

Deploy, then smoke-test:

```bash
curl https://<app>.koyeb.app/api/health
curl https://<app>.koyeb.app/api/content/chapters | head -c 300
```

---

## 2. Environment variables — plain vs **encrypted secret**

In Koyeb, each variable row has a **type** dropdown: `Plaintext` or `Secret`.
Choose **Secret** for anything in the "Encrypted" column below — Koyeb stores
those encrypted at rest, hides the value in the UI/logs after saving, and
injects it into the container at runtime. You can also pre-create them in
**Koyeb → Secrets** and reference them from the service.

| Variable | Encrypted? | Value |
|---|---|---|
| `MONGO_URL` | **Yes — Secret** | MongoDB Atlas SRV URI (`mongodb+srv://user:pass@cluster/...`). Contains a password → never plaintext. |
| `DB_NAME` | No | `ujjwal_pathak` |
| `JWT_SECRET` | **Yes — Secret** | 32+ random chars: `openssl rand -hex 32` |
| `MENTOR_ACCOUNTS` | **Yes — Secret** | `mentor@ujjwalpathak.in:YourPass,admin@…:OtherPass` |
| `MENTOR_PASSWORD_HASH` | **Yes — Secret** | Optional bcrypt hash alternative to `MENTOR_ACCOUNTS` |
| `DEV_AUTH_BYPASS` | No | `0` — **must be 0 in production** |
| `STUDENT_IMPORT_KEY` | **Yes — Secret** | Shared secret for the Students-sheet import (`X-UMP-Import` header) |
| `SYNC_SECRET` | **Yes — Secret** | HMAC key for `/api/progress-sync` |
| `ACCOUNT_RESET_SHEET_PASSWORDS` | **Yes — Secret** | The four Sheet passwords, see §3. Delete after the reset has run. |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID` | **Yes — Secret** | WhatsApp provider credentials |
| `WHATSAPP_PROVIDER`, `WHATSAPP_MENTOR_NUMBER` | No | `meta` / `msg91` / `simulate`, and the mentor's number |
| `IMPORT_GENERATED` | No | `1` |
| `GENERATED_DIR` | No | `../content-pipeline/generated` |
| `CORS_ORIGINS` | No | `https://<app>.koyeb.app` (SPA is same-origin; widen only if another origin needs the API) |
| `ACCESS_MIN_ATTEMPT` | No | `2027-01` (default) |
| `JAN_2027_ACCESS_THROUGH` | No | `2027-01-20` (default) |

Rules of thumb: anything that is a password, token, connection string or
signing key → **Secret**. Toggles, paths and public URLs → plaintext.
Changing a variable triggers a redeploy; secrets are not printed in build or
runtime logs.

MongoDB Atlas: Network Access → allow `0.0.0.0/0` (Koyeb egress IPs are not
static on the free plan) and rely on the SRV credentials, or use Atlas
private endpoints on a paid tier.

---

## 3. The four-account emergency reset on Koyeb

Scope: **UMP0043, UMP0081, UMP0088, UMP0090** only. Each goes back to its
existing **Students-sheet password** and is forced to choose a new one at
first login. Every other field (name, email, CA level, group, attempt, batch,
phone, address, joinedOn, WhatsApp) and every other account, MCQ attempt and
analytics record is untouched.

The reset runs automatically on the first production boot and writes an
idempotency marker (`migrations.key = account_reset_2026_10_four_accounts`),
so later redeploys never re-run it — a student who has already chosen a new
password is never pushed back to the Sheet password.

**Option A — supply the Sheet passwords (instant fix).**
Add the encrypted secret and redeploy:

```
ACCOUNT_RESET_SHEET_PASSWORDS = {"UMP0043":"<sheet pw>","UMP0081":"<sheet pw>","UMP0088":"<sheet pw>","UMP0090":"<sheet pw>"}
```

`UMP0043:pw,UMP0081:pw,…` is accepted too. Copy the values straight from the
Students sheet. **Delete the secret once the marker exists** — it is no longer
read, and that keeps the passwords out of the service config.

**Option B — no secret (sheet re-sync).**
Leave the variable unset. The four accounts are flagged
`sheetPasswordResyncPending`, and the next Students-sheet import
(`POST /api/student-auth/import`, which already carries Sheet passwords)
restores each password. The forced password change still applies.

**Verify / trigger manually** (mentor JWT required):

```bash
TOKEN=$(curl -s -X POST https://<app>.koyeb.app/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"mentor@ujjwalpathak.in","password":"<mentor pw>"}' | jq -r .token)

# did it run?
curl -s https://<app>.koyeb.app/api/student-auth/account-reset-status \
  -H "Authorization: Bearer $TOKEN" | jq

# run it now (idempotent; add ?force=true only to deliberately re-run)
curl -s -X POST https://<app>.koyeb.app/api/student-auth/account-reset \
  -H "Authorization: Bearer $TOKEN" | jq
```

Or from a one-off shell in the image: `python account_reset.py`.

Student-side check: log in as UMP0043 with the Sheet password → the app
reports `forcePasswordChange: true` → the student sets a new password →
subsequent logins use the new password only.

---

## 4. Cut-over checklist

1. Deploy on Koyeb, confirm `/api/health` is `ok`.
2. Set the encrypted secrets from §2, redeploy, confirm `/api/health` again.
3. Run/verify the account reset (§3) and have the four students log in.
4. Point the domain at Koyeb (Koyeb → Domains → add `app.ujjwalpathak.in` →
   create the `CNAME` to `<app>.koyeb.app`; TLS is issued automatically).
5. Update the Apps Script `STUDENT_AUTH_URL` / proxy target to the Koyeb URL.
6. Keep `render.yaml` as-is: Render remains a working fallback host.
