# Workbook integration finished locally — release remains HOLD

**26 October 2026 · IST**

The remaining local workbook-authoring/integration batch is implemented and tested. **“Everything is done; only push remains” is not yet supported.** Authenticated live acceptance, real content approval, recovery and device gates below remain open.

## Completed in this batch

- Mentor controls for written, MCQ, blanks/approved aliases and one-to-one matching, with explicit mark allocation. Invalid or duplicate objective keys fail before creation. Question/key/reference/source edits invalidate source verification; cloning preserves marks and keys but clears verification. An unsupported clone does not overwrite the current draft.
- Workbook-only backend integration in **both root and release-candidate source**, plus mentor `/workbooks` navigation within the existing authenticated layout. Existing cohort tools/navigation were retained; the new global workbook link does not silently inherit a cohort.
- Distinct authenticated **`/api/practice/workbooks/session`** transport for student web and native workbook bridge. The existing receipt session and receipt-only router were not broadened. Candidate tests prove a non-owner workbook login cannot bypass the receipt test-account allowlist. No duplicate practice method/path registrations.
- Strict draft-save and availability ACKs: acknowledged database write, matched target where applicable, and matching readback. The UI does not report success from HTTP 200 alone. Changed keys/marks/audience, missing readback and malformed acknowledgements are rejected without clearing the draft.
- Same draft request uses a mentor-scoped, non-authenticating idempotency key. Replaying that intent returns the existing matching draft rather than creating a duplicate; conflicting content or an already-published intent is refused. No additional stored schema field, collection or index was introduced for replay handling. A manual list-refresh control reviews saved workbooks without submitting or clearing the current draft.
- Objective grading retains assignment, authentication and confirmation checks; it uses approved keys without provider/usage/feedback writes. Written feedback remains provisional; no real academic calibration is claimed.
- Restored **verification-only** `ffprobe` dependencies by authenticated package download and extraction into the transient workspace cache. No system package installation or production configuration change. The two earlier audio-validator environment failures now pass with real local `ffprobe`; provider responses in those tests remain synthetic.

## Final verification

All results below are local; Python API tests use an in-memory database and the no-network plugin. Counts overlap across copied source trees and suites; do not add them into a unique-test total.

| Check | Final result | Evidence file in this folder |
|---|---:|---|
| Root backend full suite | **591 PASS** | `root-release-hold-final.log` |
| Candidate workbook/auth/isolation/write-ACK suite — not full candidate regression | **87 PASS** | `candidate-release-hold-final.log` |
| Standalone prototype workbook + audio-validator + write-ACK suite | **91 PASS** | `prototype-release-hold-final.log` |
| Candidate isolated Smart Targets | **42 PASS** | `targets-final.log` |
| Mobile full suite | **411 PASS** | `mobile-integrated-final.log` |
| Student web full suite | **333 PASS** | `web-integrated-final.log` |
| Student web workflows | **21 PASS** | `web-workflows-final.log` |
| Actual React mentor component/helper/readback tests | **35 PASS per source tree** | `authoring-*-strict-final.log` |
| Mentor route/layout/link syntax and protected mount checks | **6 files PASS** | `frontend-mount-syntax.log` |

Actual authoring-helper payloads were validated through the authenticated local API, student projection and deterministic objective grade route. Matching synthetic payload fixtures are included with backend tests. Fault-injection tests cover unacknowledged/unmatched writes and wrong readbacks. Earlier failed runs remain preserved; none was converted into a skip. Deprecation/bcrypt metadata warnings remain recorded. Production frontend bundle/native build and physical-device acceptance were not performed.

## Change integrity

`changed-files.json` and `CHANGES.patch` capture **40 scoped application/test files**, with originals under `before/` and intermediate pre-hardening checkpoints under `before-strict-ack/`. `final-integrity.json` confirms all final recorded SHA-256 hashes.

Of the preceding batch’s 16 files, **14 remain byte-identical**. Only `student-app/workbook.html` and the prototype `routers/practice_tools.py` were deliberately superseded here, and both preceding hashes match this batch’s original checkpoints. Authoring code and payload fixtures agree across all three trees; root/candidate workbook-only routers are byte-identical. The existing candidate receipt router was not edited.

## Gates still open — not “just push”

| Gate | Evidence still required |
|---|---|
| Targets in the actual app | Authenticated live POST through the real gateway/backend and intended installed app, with correct persisted/read-back result. The last available cloud credential check returned 401; no fresh authenticated live acceptance was obtained. Local 42-pass routing tests are not installed-app proof. |
| Sync 422 / progress 401 | Real endpoint authenticated save/readback and durable retry acceptance. Local strict-ACK tests do not prove production persistence. |
| Recovery | Successful owner-local restore and verified coverage/consistency. The underlying Windows GPG error/cause remains unconfirmed; no passphrase blame or blind retry was introduced. |
| Real Audit/SM workbook content | Complete question/source-page mapping, approved model answers, marks and objective keys, plus written/OCR/SM calibration. Drive source files were found and text was read, but returned text was truncated and several answer blocks were absent from the visible extraction. No omitted content was inferred, no marks fabricated, and no real workbook was saved or published. |
| Private file/proof access | Real server/service-account PDF access, assigned-student proof/upload/read chain and denial checks. Owner connector access is not server access proof. |
| Mentor assignment | Local group/batch and role guards pass; live deployment-role/current-enrollment enforcement still needs acceptance. |
| Release/device/capacity | Production build, original-signing in-place update, Android/DualApp checks and capacity acceptance. No APK/OTA/version/signing action taken. |
| Ranking/rollout | Existing HOLD remains. No ranking activation, scheduler, board rollout or expired notification campaign was revived. |

## Actions deliberately not taken

No Git push, deployment, APK/OTA publication, feature activation, real student-data write, live collection/index/TTL change, restore, paid service, notification campaign or trigger. No live credentials were copied into evidence. The encrypted owner-local backup and existing release constraints remain unchanged.

**Accurate handover:** local workbook authoring, compatible source integration and ACK/readback hardening are complete with passing local checks. Overall app/release readiness is still conditional on the open gates above.
