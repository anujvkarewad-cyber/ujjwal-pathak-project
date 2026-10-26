# OTA compatibility checkpoint — build 49

26 October 2026, IST. Read-only compatibility investigation; no OTA publication, merge, new APK or deployment.

## Verified from genuine records and artifact
- Successful GitHub build run: 40115021829; source commit: 7504f26e880a0994089e14b9cff543db818a63ba.
- Authenticated artifact 12569265853 downloaded to transient verification cache. Archive digest matches GitHub metadata; contained APK SHA-256 matches the compiled verification log: 08fb4d9ba2c8b841bba918fe0d9be867ec2e9c69c91a4d1a04fd54a53d4b47e7. APK ZIP CRC checks pass.
- APK embedded configuration: version 1.15.4/build 49; EAS project fc2cb9eb-e3f0-40b2-9a74-7c996902602c; runtime 31d36d8dea1b99e818124af6cb36678a6804fdee.
- Compiled verification log for these exact APK bytes reports OTA enabled, production channel, original signing certificate, embedded baseline enabled and anti-bricking enabled. The log explicitly says device acceptance pending.
- Current package.json, lockfile, app.json, app.config.js, eas.json, fingerprint-ignore policy and OTA policy exactly match genuine build-49 source. Six directly checkable native-input files match the recorded fingerprint source hashes.
- Restored mobile dependencies with npm ci --ignore-scripts, without lockfile edits or native build. Actual runtime inspection after reconciliation produces the SAME runtime and project as the authenticated APK.

## Fresh regression and integrity result
The first fresh mobile run failed (351 pass, 36 fail, 15 cancelled). Investigation found nine source files missing or matching preserved earlier versions, rather than the retained tested patch ledger. Cause of source drift is not established.

Preserved existing versions, refused unknown/concurrent drift and reconstructed only exact recorded patches. Combined two-batch ledger now verifies 54/54 scoped SHA-256 hashes. The fresh full mobile rerun is **411 PASS / 0 FAIL / 0 skipped** (`mobile-fresh-reconciled.log`). The initial failed run remains retained. Backend 591-pass and other earlier suite counts are retained results, not fresh executions in this checkpoint.

The previous Git save was a source checkpoint, NOT a release candidate. Corrected source and retained patches must be saved to the existing save branches before any release consideration.

## Decision
**Native runtime compatibility is supported for this exact original build-49 APK and current inspected source.** This does not prove which APK or subsequently received update is installed on the owner's phone. It also does not prove authenticated Targets/Study Log durability or backend readiness.

Do not set deviceValidated=true or bypass the release guard. The baseline ledger remains unchanged. No production channel publication may be described as an owner-only test: other compatible installations can receive it.

## Remaining acceptance
1. Confirm the owner's phone is the intended build/update, then complete explicit device acceptance.
2. Authenticate real Targets and Study Log/progress flows and verify save ACK plus reopen/readback; deploy required backend/web changes separately with approval.
3. Check release/rollback and channel audience before authorized publication.
4. Backup restore remains a separate owner-PC diagnostic gate; no production data migration/deletion is authorized by this compatibility check.
