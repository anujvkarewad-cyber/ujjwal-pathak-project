# Individual MCQ ranking policy — local implementation

Date: 19 October 2026 (owner-local date). No deployment or activation.

> **Later owner requirement — 20 October 2026:** ranking credit is limited to official Daily MCQ sets with all 10 questions answered/submitted; points are accuracy-based, not conditional on 10/10 correctness. Practice/unlimited and incomplete daily sets earn no ranking credit. The implementation described below predates this restriction and is NOT sufficient for release. See `NEXT-APK-MASTER-CHECKLIST.md` and the standing rules. No scoring activation or weekly formula change occurred.

## Source successfully recovered

The connected Drive contained `UPM-handover.bundle` (4,083,951 bytes).

- SHA-256: `6fde1089505bdf4c24614a2c40e6c4bd00a57b112b265e96d1c127fe25dd6053`, matching the handover prefix.
- Handover HEAD: `3b3c69acdc8633229c932b2beac0f79f75f33f7c`.
- Handover HEAD tree: `1fa64d9ea445833c858519a9a1e28c0991a1c19b`.
- Working repository: `/home/user/backend`.
- This is the actual uploaded handover source, not the older `5ded88f` reference. It includes `group_bucket`, attendance, Sunday–Saturday weeks and newer group-board routes. Whether it exactly matches today's deployed service has not been reverified.

### Git-history caveat

Normal `git clone` failed: commit `8e1c4049eb74d544a6c25741e886fe74c1de7c8d` references missing ancestor `c57202957d983e7470c779b0baffee3731129f81`. `git bundle verify` reports a complete bundle but does not prove every ancestor object exists.

Recovery imported the original pack into an empty local repository, verified that the entire original HEAD tree can be archived, then checked out that exact HEAD. No missing source or commit was invented. The HEAD source is complete; older Git history remains incomplete. Preserve the original bundle and the local patch; do not claim that a normal full-history clone now works.

## Owner-requested behavior implemented

For the new **individual-mcq-v1** policy:

- No 60% cohort-participation requirement. The MCQ component is enabled even at 0%, 10%, 50% or 100% coverage.
- A solver receives the existing performance/volume credit independently of peers.
- Defaults remain **hours 40 / MCQ 30 / attendance 30**. With no MCQ, MCQ points are zero; hours and attendance are not renormalized to 100.
- The question-volume formula and weekly threshold of 20 are unchanged. This is not an unconditional rule that every solver ranks above every non-solver.
- Coverage remains informational.
- Legacy `RANKING_MCQ_MODE=off/auto` and coverage thresholds cannot override an active individual policy.
- Mentor API metadata identifies the policy, reports MCQ mode ON, sets the coverage threshold to null, and includes each segment's actual effective weights.
- The shared backend scoring path feeds the installed student web and Android projections; no APK is needed for this server-side scoring change alone. Their full explanatory UI work remains separate.

Changed source:

1. `backend/routers/ranking.py`: versioned individual policy, explicit Sunday cutover, active-policy branch before the old coverage decision.
2. `backend/routers/student_dashboard.py`: truthful policy metadata and per-segment effective weights.
3. `backend/tests/test_mcq_individual_policy.py`: 31 new policy checks.
4. `backend/tests/test_leaderboard.py`: 2 new endpoint/history checks, including the student projection.

## Activation is deliberately UNARMED

**Do not confuse implemented code with an active production policy.**

`RANKING_INDIVIDUAL_MCQ_FROM` is intentionally unset. Without an approved cutover date, the existing policy continues to run. The new policy was activated only inside synthetic tests.

At release, a separately approved Sunday `YYYY-MM-DD` must be supplied in this setting. Invalid or non-Sunday dates fail configuration validation. No production date has been chosen, no environment has been changed, and no activation command was run. `2026-10-25` in tests is only a fixture, not permission to activate on that date.

Why retain the old code branch? Deleting it unconditionally would change prior weekly-top calculations when the existing history endpoint recomputes them. Windows ending before the approved cutover retain their legacy calculations. The 60% rule is removed **from the new policy**, not destructively removed from historical calculation support.

Monthly/overall live views use the policy of the window's as-of week; they must never be used to regenerate a previously published artifact. This behavior is documented and tested.

## Verification

All executions used `MONGO_URL=memory://`, `DB_NAME=test_db`, persistence disabled, synthetic accounts and the existing test login flow. An external pytest plugin blocked real IPv4/IPv6 network connections. No real Sheet, production account, push delivery or production database was used. The production report hold/settings were not changed.

| Check | Before | After |
|---|---:|---:|
| Full backend suite, same standard offline harness | 343 passed / 4 failed | 376 passed / 4 failed |
| Targeted policy, ranking, leaderboard and group-board suites | — | **92 passed** |
| New tests | — | **33 passed** |
| `git diff --check` | clean | clean |

The same four failures existed before any source change:

- `test_push_midnight_glitch.py::test_a_fresh_morning_tick_still_runs_its_job`
- `test_push_quiet_gate.py::test_evening_nudge_skips_a_student_whose_day_is_done`
- `test_push_quiet_gate.py::test_evening_nudge_still_warms_up_a_zero_day`
- `test_student_content.py::test_bank_json_only_serves_published`

They were not altered or hidden. The three push assertions observed empty mock-send lists; their broader root causes were not investigated in this change. The content test expects `no-store` while the response carries a public cache policy; that mismatch is also noted in the handover.

An initial safety-heavy baseline additionally set scheduler OFF/report HOLD in the *test process*, producing 7 failures because some tests expect scheduled mock calls. It is retained as `baseline.log`; the comparison above uses `baseline-standard.log` and `after-mcq.log`, with matching clean test environments and the network blocker. No live scheduler was enabled: server startup skips scheduler startup for `test_db`.

Evidence: `/home/user/verification/backend-recovery/` contains baseline/after logs and JUnit XML, targeted logs, the no-network pytest plugin, and source-recovery evidence.

Example synthetic results:

- 10 students, 1 solver with 20/20: solver gets 30 MCQ points; the other 9 get 0. All use 40/30/30.
- Full hours + full attendance + no MCQ: 70/100, not a renormalized 100.
- A peer syncing across 60% coverage does not change another student's component scores. Rank may still legitimately move when that peer earns points.
- Active policy reaches the mentor endpoint and stored student projection with matching MCQ components.
- Pre-cutover weekly-top payloads remain identical with unchanged fixture inputs, including batch/group segmentation.

## Release blockers still apply

This is a narrow policy implementation, not completion of the full audit remediation:

1. Fix and verify restore/sync 422 and progress-sync 401 on the actual client/backend path before awarding production credit through this policy.
2. Repair selected-period MCQ inputs, server-verification and repeat-question inflation. Current adapter/store still has the audited trust/aggregation issues; these tests do not certify real attempts as verified.
3. Preserve already-published podiums from authoritative artifacts and add immutable snapshots before release. The current recovered weekly-top endpoint still recomputes history. A cutover test proves no policy-only change for fixed historical inputs, **not** immutability against later data or configuration changes.
4. Approve and lock a future effective week before it starts, plus rollout/rollback steps. Do not backdate the cutover.
5. Complete applicable board explanations and the outstanding excused/zero-hour work with regression tests; do not bundle silent scoring changes into this patch.
6. Resolve or explicitly disposition baseline failures before a production release gate is claimed green.

No deployment, student push/message, environment mutation, APK build or OTA publication occurred. Every future student APK must still satisfy the mandatory true-OTA requirement.

## Recovery / rollback

The original uploaded bundle remains unchanged at `/home/user/google_drive/UPM-handover.bundle`. A byte-for-byte HEAD source archive was verified at `/home/user/verification/backend-recovery/handover-tip.tar`.

The delivered patch applies to handover HEAD `3b3c69ac`; check the target revision before applying. Local rollback is a revert of the policy commit; it is not permission to change already-published scores. If a future live rollout needs rollback, preserve finalized snapshots and pause publication first rather than switching weights midweek.


## 21 October candidate reconciliation

This deferred tree remains the historical individual-v1 patch. A narrowly reconciled and extended module now lives in `/home/user/workbook-receipts/project/backend`, with server-issued Full-10 verification, verified per-period inputs, and the unarmed `individual-daily-full10-v2` policy. Do not deploy this older tree wholesale or treat its old unrestricted fixtures as current eligibility acceptance. See `apk-preparation/HANDOVER.md`; no activation/deployment occurred.
