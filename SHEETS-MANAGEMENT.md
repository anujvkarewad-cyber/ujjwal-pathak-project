# UPM Sheets management — 19 October 2026

## Delivery and boundaries

**Control Centre:** https://docs.google.com/spreadsheets/d/1hMm8bGen63fMq8dLXgsPVhbV0S1lFWD_hhihctAxNYM/edit

Created as a separate native Google spreadsheet; permissions verified: **one owner only**, no public/domain sharing. Five pages: Start Here, Workbook Directory, Main Tab Directory, Data Health, App Source Map. Metadata and aggregate counts, not credential values or raw activity records. It is a dated audit snapshot, **not an automatically updating dashboard**.

Inventory covers 14 original spreadsheets. Detailed primary-workbook inventory covers 80 tabs: 59 individual-student tabs and 21 operational tabs. Not every external/individual/untitled workbook has received a content audit. No originals were renamed, merged, moved, archived or deleted.

## Applied in Google Sheets

Only the primary `Students` tab received presentation edits:
- A1:Q1: navy header, bold white 11pt text, wrapping, left/middle alignment.
- Row 1 height: 48px.
- Columns A:G width: 190px.
- Existing basic filter, alternating bands, column order, names and sharing retained.

An additional frozen-column request was rejected by the connector/API because nullable grid counts were serialized as a reset. It was **not retried**. Read-back confirmed the original 972 rows, 26 columns, one frozen header row and no frozen columns. No rows were deleted. Do not repeat the nullable-grid request on a source workbook.

### Preservation verification

Private before/after XLSX snapshots were compared without printing cell values. **Students and Form responses 1 values and formulas were identical.** 78 of 80 tabs were identical. Two differences appeared during the audit: PasswordLog gained row 986 (five cells), and Mentor Dashboard E15's exported formula representation changed. No write targeted either location and neither was overwritten. Therefore this is not a claim that the entire live workbook remained byte-for-byte/static throughout the audit.

Original snapshots contain sensitive records and must stay private; they are **not** part of the evidence ZIP, this repository or the Control Centre. Only metadata/aggregate results belong in shared reports.

## Verified findings

### Urgent: public credential-bearing workbook

The main workbook has `anyone / reader` link access. Credential-related columns and administrative tabs exist in the same file. No credential values have been reproduced in the report or client code. Hiding/protecting a tab does not prevent reads.

**No permission changes or credential rotation were performed.** Current tracker readers use unauthenticated Google Visualization requests, so revoking public access without migration could break reads. Recommended controlled next work:
1. Inventory authentication, roster, OTP, token and log consumers; avoid public copies of secrets.
2. Prepare authenticated server-side Sheets access and a private credential/log store; retain only necessary non-sensitive projections.
3. Test login, recovery, successful web/Android sync, group membership and tracker reads with restricted access.
4. Obtain explicit approval for the production cutover/public-access removal and credential/session rotation. Preserve authorized mentor access and a rollback plan.
5. Re-check public access and monitoring after cutover. No mass student messages automatically.

The new mentor page links only to the **private Control Centre**. Direct source-workbook IDs and individual student-tab names were deliberately excluded from its client bundle; a UI route guard alone is not data confidentiality.

### Roster and query typing

170 unique IDs; Group 1 78, Group 2 55, Both 37. Batch totals: Before Result Batch 1 89, Before Result Batch 2 46, Super 30 35. These are the **whole roster**, not the January cohort or the current eligible leaderboard population.

Attempt contains 135 date cells and 35 text cells (`Sept 2026`). Google Visualization emitted null for the text minority in a grouped query. Those 35 attempts are **not genuinely blank**. The original values were not normalized or overwritten. Typed-source reading and consumer parity still need testing before any migration.

### Other source boundaries

- Main Students A/B/E/F/G is the recovered backend's roster contract; the student gateway also has a positional A:I reader. Do not reorder columns.
- Study Date is column L in the tracker form; preserve exact header spelling and trailing spaces.
- Students J:N and O:Q contain separate access-control aliases. Precedence review is pending; no conflict or redundant block is assumed.
- MCQ, Attendance and Leaderboard tabs were header-only in the primary export. This does **not** imply zero runtime activity: backend/Mongo and stored snapshots are also involved.
- Notification and resource workbooks were inventoried, but their current runtime connections were not verified. Notification workbook timezone is America/Los_Angeles; left unchanged to avoid altering schedule semantics.
- Three untitled and older/individual workbooks are preserved pending purpose confirmation. The older July tracker is not the recovered code's current default.

## Local application changes — not deployed

- `backend/routers/student_dashboard.py`: empty roster results now truthfully report `Mongo fallback`, matching existing data fallback behavior. No roster membership, scoring formula, period, attendance or snapshot-storage logic changed.
- New mentor `/sheet-sources` page inside the existing auth guard, with sidebar and page title. Only source descriptions and private-directory navigation; no new credential/data endpoint.
- `SheetSourceStatus` on Daily Tracker and Leaderboard surfaces API source metadata. Explicit failure/fallback warns that counts/ranks may be incomplete and that missing data must not imply absence. Missing metadata is unknown, not healthy. Successful read is labeled for that response, not as verified device sync.
- Student web and Android source-path audit was started, but no student-client code was changed and end-to-end parity is **not yet verified**.

## Verification

- Targeted backend: **85 passed** (includes four new source-label cases plus tracker, group-board, leaderboard and individual-MCQ regressions).
- UI: **19 passed** (status logic, server rendering, private-link checks, route/source wiring and modified-file JSX syntax).
- Full backend: **380 passed / 4 failed**. Same four pre-existing failures as the prior 376-pass baseline: midnight push job, two quiet-gate push cases, published-bank cache.
- UI verification is not a full frontend production build, browser/authenticated E2E session or device test.
- Backend tests use memory DB and the outbound-network-blocking pytest plugin; no live student API actions.

No deployment, Git push, APK build, OTA activation, message/poster send, historical podium rewrite, secret reset or source sharing change. Prior 40/30/30, unarmed MCQ cutover, immutable-podium requirements, sync 422/401 blockers and true-OTA constraints remain in force.

## Evidence and rollback

Workspace: `/home/user/sheets-management/`. `evidence/remote-changes.json` records exact remote edits and the rejected freeze request; `content-preservation.json` records comparison limits. Private source snapshots are under `private/` and excluded from deliverable evidence.

Undo only the three specific formatting/size changes using original style/dimension metadata in the private pre-change export. **Do not replace/import an entire old workbook:** ongoing logs/submissions may have changed. Local app changes are a separate Git commit/patch after `c2ae98d69ae47176cd74a091e2d190ed75dc9eab` and can be reverted independently.
